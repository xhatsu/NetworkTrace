"""Labelled offline replay benchmark for the learned-behavior engine.

Synthetic five-minute metric buckets with known injected events are replayed
through the same pure functions the worker uses (normalize -> summarize_day ->
build_profiles -> advance_graph -> graph_deviations), stepping the evaluation
day the way the live worker would see it. Nothing touches ClickHouse or ES.

Run:  .venv/bin/python -m backend.scripts.benchmark_behavior [--json] [--step 3]
"""
from __future__ import annotations
import argparse
import json
import math
import random
import time
from collections import defaultdict

from backend.app.services.behavior_graph import advance_graph, level_shift_starts, relationship_view
from backend.app.services.behavior_sources import normalize
from backend.app.services.behavior_worker import graph_deviations
from backend.app.services.learned_behavior import BUCKET, DAY, build_profiles, relationship_id, summarize_day

HOUR = 3_600_000
SOURCE = 'legacy_metrics'
ALERT_KINDS = {'traffic_surge', 'graph_tps_shift', 'graph_edge_novelty', 'access_expansion', 'contract_violation'}
GRACE_MS = 30 * 60_000
# A persistent new level must stop alerting within this time after it begins.
ADAPT_ALLOWANCE_MS = 6 * HOUR


def poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 50:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def diurnal(at):
    hour = at % DAY / HOUR
    return 0.35 + 0.65 * max(0.0, math.sin(math.pi * (hour - 6) / 14)) if 6 <= hour <= 20 else 0.35


def scenarios(eval_day):
    """Each scenario owns one relationship; `event` is the labelled interval."""
    at = lambda h: eval_day + int(h * HOUR)
    end = eval_day + DAY
    return [
        {'name': 'steady_diurnal', 'expect': 'quiet', 'principal': 'alice', 'target': 'svc-a', 'operation': 'a/read',
         'rate': lambda t: 60 * diurnal(t)},
        {'name': 'sparse_poisson', 'expect': 'quiet', 'principal': 'bob', 'target': 'svc-b', 'operation': 'b/poll',
         'rate': lambda t: 2},
        {'name': 'transient_surge_5x', 'expect': 'detect', 'principal': 'carol', 'target': 'svc-c', 'operation': 'c/pay',
         'event': (at(10), at(11)), 'rate': lambda t: 80 * (5 if at(10) <= t < at(11) else 1)},
        {'name': 'level_shift_4x', 'expect': 'detect_then_adapt', 'principal': 'dave', 'target': 'svc-d', 'operation': 'd/sync',
         'event': (at(2), end), 'rate': lambda t: 50 * (4 if t >= at(2) else 1)},
        {'name': 'new_api_for_known_credential', 'expect': 'detect', 'principal': 'erin', 'target': 'svc-e', 'operation': 'e/admin',
         'event': (at(12), end), 'rate': lambda t: 20 if t >= at(12) else 0},
        {'name': 'baseline_for_new_api', 'expect': 'quiet', 'principal': 'erin', 'target': 'svc-e', 'operation': 'e/read',
         'rate': lambda t: 40 * diurnal(t)},
        {'name': 'moderate_surge_2_5x_high_volume', 'expect': 'detect', 'principal': 'frank', 'target': 'svc-f', 'operation': 'f/bulk',
         'known_gap': 'fixed 3x material-surge floor; count-based scoring not implemented yet',
         'event': (at(15), at(17)), 'rate': lambda t: 3000 * (2.5 if at(15) <= t < at(17) else 1)},
    ]


def generate(train_days, seed):
    rng = random.Random(seed)
    start = 1_790_000_000_000 // DAY * DAY - (train_days + 1) * DAY
    eval_day = start + train_days * DAY
    cases = scenarios(eval_day)
    by_day = defaultdict(list)
    for case in cases:
        row = {'environment': 'unknown', 'caller': 'gateway', 'principal': case['principal'],
               'target': case['target'], 'operation': case['operation']}
        case['relationship_id'] = relationship_id({**row, 'source': SOURCE})
        for at in range(start, eval_day + DAY, BUCKET):
            requests = poisson(rng, case['rate'](at))
            if requests:
                by_day[at // DAY * DAY].append(normalize(SOURCE, {**row, 'bucket_ms': at, 'requests': requests}))
    return start, eval_day, cases, by_day


def replay(train_days=10, step=3, seed=7):
    start, eval_day, cases, by_day = generate(train_days, seed)
    history = [s for day in sorted(by_day) if day < eval_day for s in summarize_day(by_day[day], include_anonymous=True)]
    today = sorted(by_day[eval_day], key=lambda r: r['bucket_ms'])
    graph, alerts, started = None, defaultdict(list), time.monotonic()
    steps = 0
    for last in range(eval_day, eval_day + DAY, step * BUCKET):
        # Worst case: learnable_end falls back to complete_end=(now//BUCKET-1)*BUCKET.
        now = last + 2 * BUCKET
        days = history + summarize_day([r for r in today if r['bucket_ms'] <= last], include_anonymous=True)
        graph = advance_graph(graph, days, SOURCE)
        profiles, deviations = build_profiles(days, [], now, level_shift_starts(graph))
        for item in profiles:
            item['graph_learning'] = relationship_view(graph, item, now)
        deviations += graph_deviations(profiles, deviations, now)
        for d in deviations:
            if d['kind'] in ALERT_KINDS:
                alerts[d['relationship_id']].append((last, d['kind']))
        steps += 1
    return score(cases, alerts, eval_day), {'steps': steps, 'seconds': round(time.monotonic() - started, 2),
                                            'train_days': train_days, 'step_windows': step, 'seed': seed}


def score(cases, alerts, eval_day):
    results = []
    for case in cases:
        hits = sorted(set(alerts.get(case['relationship_id'], [])))
        times = sorted({t for t, _ in hits})
        kinds = sorted({k for _, k in hits})
        result = {'scenario': case['name'], 'expect': case['expect'], 'alert_steps': len(times), 'kinds': kinds,
                  'known_gap': case.get('known_gap')}
        if case['expect'] == 'quiet':
            result['pass'] = not times
        else:
            begin, end = case['event']
            first = next((t for t in times if begin <= t <= end + GRACE_MS), None)
            result['detected'] = first is not None
            result['delay_minutes'] = None if first is None else (first - begin) // 60_000
            allowed_end = min(end, begin + ADAPT_ALLOWANCE_MS) if case['expect'] == 'detect_then_adapt' else end
            stale = [t for t in times if not begin <= t <= allowed_end + GRACE_MS]
            result['false_or_stale_steps'] = len(stale)
            result['pass'] = first is not None and not stale
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--train-days', type=int, default=10)
    parser.add_argument('--step', type=int, default=3, help='worker cadence in five-minute windows')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    results, run = replay(args.train_days, args.step, args.seed)
    if args.json:
        print(json.dumps({'run': run, 'results': results}, indent=2))
    else:
        for r in results:
            detail = '' if r['expect'] == 'quiet' else f" delay={r['delay_minutes']}m stale={r['false_or_stale_steps']}"
            status = 'PASS' if r['pass'] else 'GAP ' if r['known_gap'] else 'FAIL'
            print(f"{status}  {r['scenario']:<34} alerts={r['alert_steps']:<3}{detail} {','.join(r['kinds'])}")
        print(f"{sum(r['pass'] for r in results)}/{len(results)} passed; {run}")
    # Known gaps are reported but do not fail the gate; a regression elsewhere does.
    raise SystemExit(0 if all(r['pass'] or r['known_gap'] for r in results) else 1)


if __name__ == '__main__':
    main()
