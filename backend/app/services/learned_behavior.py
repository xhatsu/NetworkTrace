"""Explainable shadow learning. Pure functions never approve or enforce access."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from typing import Any

DAY = 86_400_000
BUCKET = 300_000
UNKNOWN = {'', 'unknown', '-anonymous-', 'anonymous', 'unavailable'}
DIMENSIONS = ('source', 'environment', 'caller', 'principal', 'target', 'operation')


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def relationship_id(row: dict) -> str:
    return digest([str(row.get(k) or 'unknown') for k in DIMENSIONS])


def eligible_identity(row: dict) -> bool:
    return str(row.get('principal', '')).lower() not in UNKNOWN


def summarize_day(rows: list[dict], include_anonymous: bool = False) -> list[dict]:
    """Exact days/windows from replaceable buckets, never arrival-order increments."""
    groups: dict[str, dict[int, dict]] = defaultdict(dict)
    for row in rows:
        if (include_anonymous or eligible_identity(row)) and row['requests'] > 0:
            groups[relationship_id(row)][row['bucket_ms']] = row
    summaries = []
    for rid, windows in groups.items():
        values = sorted(windows.values(), key=lambda r: r['bucket_ms'])
        clean = [r for r in values if r.get('reference_eligible', False)]
        first = values[0]
        summaries.append({
            **{k: first[k] for k in DIMENSIONS}, 'id': rid,
            'day': first['bucket_ms'] // DAY * DAY,
            'first_seen': first['bucket_ms'], 'last_seen': values[-1]['bucket_ms'],
            'active_windows': [r['bucket_ms'] for r in values],
            'window_counts': [r['requests'] for r in values],
            'requests': sum(r['requests'] for r in values),
            'errors': sum(r.get('errors', 0) for r in values),
            'auth_failures': sum(r.get('auth_failures', 0) for r in values),
            'auth_successes': sum(r.get('auth_successes', 0) for r in values),
            'request_bytes': sum(r.get('request_bytes', 0) for r in values),
            'response_bytes': sum(r.get('response_bytes', 0) for r in values),
            'byte_samples': sum(r.get('byte_samples', 0) for r in values),
            'caller_observed': sum(r['requests'] for r in values if r.get('caller_observed')),
            'clean_counts': [r['requests'] for r in clean],
            'clean_windows': [r['bucket_ms'] for r in clean],
            'max_bucket_p95_ms': max((r.get('p95_ms', 0) for r in values), default=0),
            'observed_ips': list({ip['address']:ip for r in values for ip in r.get('observed_ips',[])}.values())[:20],
            'ip_windows': {ip: [r['bucket_ms'] for r in values if any(i['address']==ip for i in r.get('observed_ips',[]))] for ip in list(dict.fromkeys(i['address'] for r in values for i in r.get('observed_ips',[])))[:20]},
            'evidence': list(dict.fromkeys(x for r in values for x in r.get('trace_ids', [])))[:3],
        })
    return summaries


def active_contract(events: list[dict], at_ms: int) -> dict:
    eligible = [e for e in events if e['effective_at_ms'] <= at_ms]
    if not eligible:
        return {'state': 'unreviewed', 'event_id': ''}
    event = max(eligible, key=lambda e: (e['created_at'], e['event_id']))
    # Expired replacements do not revive earlier approvals.
    if event['expires_at_ms'] and event['expires_at_ms'] <= at_ms:
        return {**event, 'state': 'unreviewed', 'expired': True}
    return event


def build_profiles(days: list[dict], contracts: list[dict], now: int) -> tuple[list[dict], list[dict]]:
    by_relation: dict[str, list[dict]] = defaultdict(list)
    by_parent: dict[tuple, list[dict]] = defaultdict(list)
    by_contract: dict[str, list[dict]] = defaultdict(list)
    for d in days:
        if not eligible_identity(d):
            continue
        by_relation[d['id']].append(d)
        by_parent[(d['source'], d['environment'], d['principal'])].append(d)
    for c in contracts:
        by_contract[c['relationship_id']].append(c)
    profiles, deviations = [], []
    for rid, history in by_relation.items():
        history.sort(key=lambda d: d['day'])
        first, last = min(d['first_seen'] for d in history), max(d['last_seen'] for d in history)
        base = history[0]
        parent = by_parent[(base['source'], base['environment'], base['principal'])]
        prior = [d for d in parent if d['day'] < first // DAY * DAY]
        prior_days = len({d['day'] for d in prior})
        prior_requests = sum(d['requests'] for d in prior)
        prior_age = (first - min((d['first_seen'] for d in prior), default=first)) / DAY
        ready = prior_days >= 3 and prior_requests >= 100 and prior_age >= 7
        requests = sum(d['requests'] for d in history)
        windows = sorted({w for d in history for w in d['active_windows']})
        clean_days = {d['day'] for d in history if d['clean_windows']}
        counts = [v for d in history for v in d['clean_counts']]
        median = statistics.median(counts) if counts else None
        mad = statistics.median(abs(v - median) for v in counts) if counts else None
        mature = len(clean_days) >= 3 and len(counts) >= 5 and last - first >= 7 * DAY and sum(counts) >= 100
        familiarity = 'dormant' if now - last >= 7 * DAY else 'established' if mature else 'emerging'
        contract = active_contract(by_contract[rid], now)
        # Newly expanded, unreviewed access cannot train its own clean reference.
        if ready and contract['state'] not in {'approved', 'temporary'}:
            counts = []
            median = mad = None
            clean_days = set()
        version = digest([history, contract.get('event_id', ''), contract['state']])
        quality = 'limited' if base['environment'] == 'unknown' or base['caller'].lower() in UNKNOWN or base['source'] == 'legacy_metrics' else 'observed'
        p = {**{k: base[k] for k in DIMENSIONS}, 'id': rid, 'version': version,
             'first_seen': first, 'last_seen': last, 'training_cutoff': last + BUCKET,
             'active_days': len({d['day'] for d in history}), 'active_windows': len(windows),
             'reference_windows': len(counts), 'familiarity': familiarity, 'quality': quality,
             'requests': requests, 'errors': sum(d['errors'] for d in history),
             'share': requests / max(1, sum(d['requests'] for d in parent)),
             'caller_coverage': sum(d['caller_observed'] for d in history) / max(1, requests),
             'auth_failures': sum(d['auth_failures'] for d in history),
             'auth_successes': sum(d['auth_successes'] for d in history),
             'request_bytes': sum(d['request_bytes'] for d in history),
             'response_bytes': sum(d['response_bytes'] for d in history),
             'byte_samples': sum(d['byte_samples'] for d in history),
             'median_active_window_requests': median, 'mad_active_window_requests': mad,
             'schedule_ready': len(clean_days) >= 10 and last - first >= 28 * DAY,
             'hourly_windows': [sum(1 for w in windows if w // 3_600_000 % 24 == hour) for hour in range(24)],
             'contract': contract, 'evidence': list(dict.fromkeys(x for d in history for x in d['evidence']))[:3],
             'history': [{k: d[k] for k in ('day', 'requests', 'errors', 'max_bucket_p95_ms')} for d in history],
             'observed_ips': list({ip['address']:ip for d in history for ip in d.get('observed_ips',[])}.values())[:20],
             'graph_features': {'credential_target_fanout':len({d['target'] for d in parent}),
                'credential_api_fanout':len({(d['target'],d['operation']) for d in parent}),
                'credential_caller_fanout':len({d['caller'] for d in parent if d['caller'].lower() not in UNKNOWN}),
                'new_caller_for_credential':bool(prior) and base['caller'] not in {d['caller'] for d in prior},
                'new_api_for_credential':bool(prior) and (base['target'],base['operation']) not in {(d['target'],d['operation']) for d in prior}},
             'prior_days': prior_days, 'prior_requests': prior_requests,
             'prior_profile_version': digest(prior),
             'prior_relationships': sorted({d['id'] for d in prior})[:100],
             'prior_relationship_count': len({d['id'] for d in prior})}
        # Compare the latest three contiguous buckets with earlier *days* at the
        # same UTC hour. Current activity cannot contribute to this baseline.
        observed = sorted((w, count) for d in history for w, count in zip(d['active_windows'], d.get('window_counts', [])))
        latest = observed[-3:]
        reference = [(w, count) for d in history for w, count in zip(d['clean_windows'], d['clean_counts'])
                     if w < last // DAY * DAY and w // 3_600_000 % 24 == last // 3_600_000 % 24]
        reference_allowed = not ready or contract['state'] in {'approved','temporary'}
        if not reference_allowed:
            reference = []
        reference_days = len({w // DAY for w, _ in reference})
        baseline = statistics.median(v / 300 for _, v in reference) if reference else None
        rate_mad = statistics.median(abs(v / 300 - baseline) for _, v in reference) if reference else None
        rate_ready = len(reference) >= 12 and reference_days >= 3 and last - first >= 7 * DAY
        continuous = len(latest) == 3 and latest[-1][0] - latest[0][0] == 2 * BUCKET
        recent = now - last <= 30 * 60_000
        rate_threshold = max(baseline * 3, baseline + 6 * (rate_mad or 0), baseline + 100 / 300) if baseline is not None else None
        surge = bool(rate_ready and continuous and recent and baseline is not None and baseline > 0
                     and all(v / 300 >= rate_threshold for _, v in latest))
        hourly_baselines=[]
        for hour in range(24):
            samples=[v/300 for d in history for w,v in zip(d['clean_windows'],d['clean_counts'])
                     if w < last//DAY*DAY and w//3_600_000%24==hour]
            hourly_baselines.append(statistics.median(samples) if reference_allowed and len(samples)>=12 else None)
        p['tps'] = {'hourly_baselines':hourly_baselines,'latest': observed[-1][1] / 300 if observed else None,
                    'latest_at': last, 'baseline': baseline, 'mad': rate_mad,
                    'ready': rate_ready, 'reference_windows': len(reference), 'reference_days': reference_days,
                    'threshold': rate_threshold, 'persistent_surge': surge, 'fresh': recent,
                    'basis': 'same_utc_hour_prior_days_active_windows',
                    'reference_cutoff': last // DAY * DAY}
        profiles.append(p)
        if surge:
            deviations.append({**p, 'id': digest([rid, 'traffic_surge', last // DAY]),
                'relationship_id': rid, 'kind': 'traffic_surge', 'observed_contract': active_contract(by_contract[rid], latest[0][0]),
                'status': 'unreviewed', 'persistent': True, 'baseline_ready': True, 'severity': 'watch',
                'reference_cutoff': last // DAY * DAY, 'novelty_scope': 'volume', 'prohibited_windows': 0})
        # Explicit prohibitions are evaluated at observation time, not retroactively.
        prohibited_windows = [w for w in windows if active_contract(by_contract[rid], w)['state'] == 'prohibited']
        at_first = active_contract(by_contract[rid], first)
        kind = 'contract_violation' if prohibited_windows else 'access_expansion' if ready else 'learning_candidate'
        if kind != 'learning_candidate' and last >= now - 30 * DAY:
            d = {**p, 'id': digest([rid, kind, first]), 'relationship_id': rid, 'kind': kind,
                 'observed_contract': at_first, 'status': 'reviewed' if contract['state'] in {'approved', 'temporary'} else 'unreviewed',
                 'persistent': len(windows) >= 3, 'baseline_ready': ready,
                 'novelty_scope': 'available_history', 'first_seen': first,
                 'prohibited_windows': len(prohibited_windows),
                 'reference_cutoff': first // DAY * DAY,
                 'severity': 'needs_attention' if prohibited_windows else 'watch'}
            deviations.append(d)
    return profiles, deviations
