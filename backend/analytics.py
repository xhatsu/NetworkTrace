from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from typing import Any

from .config import settings
from .histogram import Histogram
from .repository import SQLiteRepository


def _aggregate_rows(rows: list[Any]) -> dict[str, Any]:
    hist = Histogram.empty()
    result = {"request_count": 0, "server_count": 0, "http_count": 0, "duration_sum_us": 0,
        "status_2xx": 0, "status_4xx": 0, "status_5xx": 0, "denied_count": 0, "slow_count": 0,
        "success_count": 0, "failure_count": 0, "unknown_count": 0, "sampled_count": 0, "unsampled_count": 0}
    for row in rows:
        result["request_count"] += 1
        server = row["span_kind"] == "server"
        http = server and row["http_method"] is not None
        result["server_count"] += server; result["http_count"] += http
        if server:
            result["duration_sum_us"] += row["duration_us"]; hist.add(row["duration_us"])
        status = row["status_code"] or 0
        result["status_2xx"] += 200 <= status < 300; result["status_4xx"] += 400 <= status < 500
        result["status_5xx"] += status >= 500; result["denied_count"] += status in (401,403)
        result["slow_count"] += server and row["duration_us"] >= settings.slow_threshold_us
        outcome = row["outcome"]
        result["success_count"] += server and outcome == "success"; result["failure_count"] += server and (outcome == "failure" or status >= 500)
        result["unknown_count"] += server and outcome not in ("success","failure")
        result["sampled_count"] += row["sampled"] == 1; result["unsampled_count"] += row["sampled"] == 0
    result["histogram_json"] = hist.dumps()
    return result


def rebuild_rollups(repository: SQLiteRepository) -> int:
    """Idempotently rebuild minute buckets with memory bounded to one minute of input."""
    now = int(time.time()*1000)
    with repository.transaction() as db:
        db.execute("DELETE FROM latency_rollups")
    written=0; current_bucket=None; bucket_groups: dict[tuple,list[Any]]=defaultdict(list)
    def flush() -> int:
        if not bucket_groups: return 0
        with repository.transaction() as db:
            for (bucket,service,environment,operation,account), rows in bucket_groups.items():
                agg=_aggregate_rows(rows)
                db.execute("INSERT INTO latency_rollups VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    bucket,60,service,operation,account,environment,agg["request_count"],agg["server_count"],agg["http_count"],agg["duration_sum_us"],agg["histogram_json"],agg["status_2xx"],agg["status_4xx"],agg["status_5xx"],agg["denied_count"],agg["slow_count"],agg["success_count"],agg["failure_count"],agg["unknown_count"],agg["sampled_count"],agg["unsampled_count"],now))
        count=len(bucket_groups);bucket_groups.clear();return count
    with repository.connect() as db:
        cursor=db.execute("SELECT * FROM events ORDER BY timestamp_ms")
        for event in cursor:
            bucket=event["timestamp_ms"]-event["timestamp_ms"]%60_000
            if current_bucket is not None and bucket!=current_bucket: written+=flush()
            current_bucket=bucket;base=(bucket,event["service_name"],event["environment"] or "")
            bucket_groups[(*base,"","")].append(event);bucket_groups[(*base,event["operation"],"")].append(event)
            if event["account_username"]:
                bucket_groups[(*base,"",event["account_username"])].append(event)
                bucket_groups[(*base,event["operation"],event["account_username"])].append(event)
    written+=flush();return written


def rebuild_topology(repository: SQLiteRepository) -> int:
    with repository.connect() as db:
        mappings = [dict(m) for m in db.execute("SELECT address,service_name,valid_from_ms,valid_to_ms,confidence FROM address_mappings ORDER BY confidence DESC").fetchall()]
        client_events = [dict(r) for r in db.execute("""
          SELECT c.timestamp_ms,c.service_name source_service,
                 c.peer_service,c.peer_address,c.url_domain,
                 c.duration_us,c.status_code,c.parent_id,p.transaction_id parent_match
          FROM events c LEFT JOIN events p ON p.trace_id=c.trace_id AND p.transaction_id=c.parent_id
          WHERE c.span_kind='client'
        """).fetchall()]

    def resolve_target(peer_svc: Any, peer_addr: Any, url_domain: Any, ts_ms: int) -> str | None:
        if peer_svc:
            return str(peer_svc)
        for m in mappings:
            if m["address"] in (peer_addr, url_domain) and m["valid_from_ms"] <= ts_ms and (m["valid_to_ms"] is None or m["valid_to_ms"] > ts_ms):
                return str(m["service_name"])
        return None

    rows = []
    for r in client_events:
        target_svc = resolve_target(r["peer_service"], r["peer_address"], r["url_domain"], r["timestamp_ms"])
        if not target_svc:
            continue
        rows.append({
            "timestamp_ms": r["timestamp_ms"],
            "source_service": r["source_service"],
            "target_service": target_svc,
            "explicit_peer": r["peer_service"],
            "duration_us": r["duration_us"],
            "status_code": r["status_code"],
            "parent_id": r["parent_id"],
            "parent_match": r["parent_match"],
        })
    grouped: dict[tuple, list[Any]] = defaultdict(list)
    for row in rows:
        bucket = row["timestamp_ms"] - row["timestamp_ms"]%60_000
        evidence = "confirmed" if row["parent_match"] and row["explicit_peer"] else "inferred"
        grouped[(bucket,row["source_service"],row["target_service"],evidence)].append(row)
    now = int(time.time()*1000)
    with repository.transaction() as db:
        db.execute("DELETE FROM topology_edges")
        for (bucket,source,target,evidence), items in grouped.items():
            hist=Histogram.empty()
            for item in items: hist.add(item["duration_us"])
            db.execute("INSERT INTO topology_edges VALUES (?,?,?,?,?,?,?,?,?,?)", (bucket,source,target,evidence,
                "parent-linked client span with explicit destination service" if evidence=="confirmed" else "explicit destination or time-valid address mapping; direct parent evidence incomplete",
                len(items),sum(i["duration_us"] for i in items),sum((i["status_code"] or 0)>=500 for i in items),hist.dumps(),now))
    return len(grouped)


def _robust(values: list[float]) -> tuple[float,float,float]:
    median = statistics.median(values)
    mad = statistics.median(abs(v-median) for v in values)
    spread = 3 * 1.4826 * mad
    if spread == 0:
        ordered=sorted(values); low=ordered[max(0,int(len(values)*.1)-1)]; high=ordered[min(len(values)-1,int(len(values)*.9))]
        spread=max(high-low, max(abs(median)*.1,.2))
    return median,median-spread,median+spread


def _wilson(successes: int, total: int, z: float = 1.96) -> tuple[float,float]:
    if total <= 0: return 0.0,1.0
    p=successes/total;den=1+z*z/total;centre=(p+z*z/(2*total))/den
    margin=z*math.sqrt((p*(1-p)+z*z/(4*total))/total)/den
    return max(0,centre-margin),min(1,centre+margin)


def detect_anomalies(repository: SQLiteRepository) -> int:
    with repository.connect() as db:
        services=[r[0] for r in db.execute("SELECT DISTINCT service_name FROM latency_rollups WHERE operation='' AND account_username=''")]
        estate_latest=db.execute("SELECT MAX(bucket_ms) FROM latency_rollups WHERE operation='' AND account_username=''").fetchone()[0]
    now=int(time.time()*1000); found=0
    for service in services:
        with repository.connect() as db:
            rows=db.execute("SELECT bucket_ms,server_count,http_count,histogram_json,status_5xx,slow_count,sampled_count,unsampled_count FROM latency_rollups WHERE service_name=? AND operation='' AND account_username='' ORDER BY bucket_ms",(service,)).fetchall()
        if len(rows)<10: continue
        current=rows[-1]; previous=rows[-2]
        if estate_latest is not None and current["bucket_ms"] < estate_latest-120_000: continue
        matching=[r for r in rows[:-2] if (current["bucket_ms"]-r["bucket_ms"])%604_800_000==0]
        baseline=matching[-8:] if len(matching)>=4 else (rows[-26:-2] if len(rows)>=26 else rows[:-2])
        if len(baseline)<8: continue
        rates=[r["http_count"]/60 for r in baseline]
        expected,low,high=_robust(rates); actual=current["http_count"]/60
        candidates=[]
        current_sampling=current["sampled_count"]/max(1,current["sampled_count"]+current["unsampled_count"])
        baseline_sampled=sum(r["sampled_count"] for r in baseline);baseline_unsampled=sum(r["unsampled_count"] for r in baseline)
        baseline_sampling=baseline_sampled/max(1,baseline_sampled+baseline_unsampled)
        sampling_shift=(current["sampled_count"]+current["unsampled_count"]>0 and baseline_sampled+baseline_unsampled>0 and abs(current_sampling-baseline_sampling)>.2)
        previous_rate=previous["http_count"]/60
        if not sampling_shift and current["http_count"]>=30 and previous["http_count"]>=30 and abs(actual-expected)>=max(.2,expected*.25) and (actual>high or actual<low) and ((actual>expected and previous_rate>high) or (actual<expected and previous_rate<low)):
            kind="rps_spike" if actual>expected else "rps_drop"
            candidates.append((kind,actual,expected,low,high,"requests/s",current["http_count"],sum(r["http_count"] for r in baseline),
                f"Observed RPS for {service} {'rose' if actual>expected else 'fell'} from {expected:.2f} to {actual:.2f} in this window, based on {current['http_count']:,} observed HTTP server requests."))
        if any(r["server_count"]!=r["http_count"] for r in rows):
            tps_baseline=[r["server_count"]/60 for r in baseline];tps_expected,tps_low,tps_high=_robust(tps_baseline)
            tps=current["server_count"]/60;previous_tps=previous["server_count"]/60
            if not sampling_shift and current["server_count"]>=30 and previous["server_count"]>=30 and abs(tps-tps_expected)>=max(.2,tps_expected*.25) and ((tps>tps_high and previous_tps>tps_high) or (tps<tps_low and previous_tps<tps_low)):
                kind="tps_spike" if tps>tps_expected else "tps_drop"
                candidates.append((kind,tps,tps_expected,tps_low,tps_high,"transactions/s",current["server_count"],sum(r["server_count"] for r in baseline),f"Observed TPS for {service} {'rose' if tps>tps_expected else 'fell'} from {tps_expected:.2f} to {tps:.2f}, based on {current['server_count']:,} observed server transactions."))
        current_hist=Histogram.loads(current["histogram_json"]); actual_p95=current_hist.percentile(.95)
        base_p95=[Histogram.loads(r["histogram_json"]).percentile(.95) for r in baseline if r["http_count"]]
        if base_p95:
            pexp,plow,phigh=_robust(base_p95)
            previous_p95=Histogram.loads(previous["histogram_json"]).percentile(.95)
            if current["http_count"]>=30 and previous["http_count"]>=30 and actual_p95-pexp>=max(75,pexp*.3) and actual_p95>phigh and previous_p95>phigh:
                candidates.append(("latency_regression",actual_p95,pexp,plow,phigh,"ms",current["http_count"],sum(r["http_count"] for r in baseline),
                    f"{service} p95 increased from {pexp:.0f} ms to {actual_p95:.0f} ms during this window, based on {current['http_count']:,} observed requests."))
        # Proportion detectors use count-aware Wilson intervals and absolute impact floors.
        for kind,column,label,floor in (("http_5xx_increase","status_5xx","HTTP 5xx rate",.02),("slow_request_increase","slow_count","slow-request rate",.05)):
            current_bad=current[column];current_total=current["http_count"]
            baseline_bad=sum(r[column] for r in baseline);baseline_total=sum(r["http_count"] for r in baseline)
            value=current_bad/max(1,current_total);expected=baseline_bad/max(1,baseline_total)
            _cur_low,_cur_high=_wilson(current_bad,current_total);base_low,base_high=_wilson(baseline_bad,baseline_total)
            previous_value=previous[column]/max(1,previous["http_count"])
            if current_total>=30 and previous["http_count"]>=30 and current_bad>=5 and value-expected>=floor and _cur_low>base_high and previous_value>base_high:
                candidates.append((kind,value,expected,base_low,base_high,"proportion",current_total,baseline_total,
                    f"{label} for {service} increased from {expected*100:.2f}% to {value*100:.2f}% during this window, based on {current_total:,} observed requests."))
        with repository.connect() as db:
            current_denied=db.execute("SELECT COUNT(*) FROM events WHERE service_name=? AND timestamp_ms>=? AND timestamp_ms<? AND status_code IN (401,403)",(service,current["bucket_ms"],current["bucket_ms"]+60_000)).fetchone()[0]
            baseline_denied=db.execute("SELECT COUNT(*) FROM events WHERE service_name=? AND timestamp_ms>=? AND timestamp_ms<? AND status_code IN (401,403)",(service,baseline[0]["bucket_ms"],baseline[-1]["bucket_ms"]+60_000)).fetchone()[0]
        denied_value=current_denied/max(1,current["http_count"]);denied_expected=baseline_denied/max(1,sum(r["http_count"] for r in baseline))
        cur_denied_low,_=_wilson(current_denied,current["http_count"]);_,base_denied_high=_wilson(baseline_denied,sum(r["http_count"] for r in baseline))
        if current["http_count"]>=30 and current_denied>=5 and denied_value-denied_expected>=.02 and cur_denied_low>base_denied_high:
            candidates.append(("auth_denial_increase",denied_value,denied_expected,0,base_denied_high,"proportion",current["http_count"],sum(r["http_count"] for r in baseline),
                f"HTTP 401/403 rate for {service} increased from {denied_expected*100:.2f}% to {denied_value*100:.2f}% during this window, based on {current['http_count']:,} observed requests."))
        with repository.connect() as db:
            contributors=[dict(r) for r in db.execute("SELECT COALESCE(node_name,'Unknown') instance,operation,COUNT(*) requests,ROUND(AVG(duration_us)/1000.0,1) avg_ms FROM events WHERE service_name=? AND timestamp_ms>=? AND timestamp_ms<? GROUP BY node_name,operation ORDER BY avg_ms*requests DESC LIMIT 5",(service,rows[-2]["bucket_ms"],current["bucket_ms"]+60_000))]
            trace_ids=[r[0] for r in db.execute("SELECT trace_id FROM events WHERE service_name=? AND timestamp_ms>=? AND timestamp_ms<? AND trace_id IS NOT NULL ORDER BY duration_us DESC LIMIT 5",(service,rows[-2]["bucket_ms"],current["bucket_ms"]+60_000))]
        for kind,value,expected,normal_low,normal_high,unit,samples,base_samples,explanation in candidates:
            fingerprint=f"service:{service}:{kind}"; delta=value-expected; pct=(delta/expected*100) if expected else None
            severity="critical" if abs(delta)>max(abs(expected),1) else "high" if abs(delta)>max(abs(expected)*.5,.5) else "medium"
            limitations=["Sampling coverage is unknown; values describe observed records.","No causal attribution is inferred."]
            with repository.transaction() as db:
                db.execute("""INSERT INTO anomalies(fingerprint,entity_type,entity_id,anomaly_type,first_detected_ms,last_detected_ms,window_start_ms,window_end_ms,current_value,baseline_value,normal_low,normal_high,absolute_difference,percent_change,current_samples,baseline_samples,persistence_buckets,severity,status,unit,explanation,rule,training_start_ms,training_end_ms,limitations_json,contributors_json,trace_ids_json,updated_at_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET last_detected_ms=excluded.last_detected_ms,window_start_ms=excluded.window_start_ms,window_end_ms=excluded.window_end_ms,current_value=excluded.current_value,baseline_value=excluded.baseline_value,normal_low=excluded.normal_low,normal_high=excluded.normal_high,absolute_difference=excluded.absolute_difference,percent_change=excluded.percent_change,current_samples=excluded.current_samples,baseline_samples=excluded.baseline_samples,explanation=excluded.explanation,updated_at_ms=excluded.updated_at_ms,status=CASE WHEN anomalies.status='resolved' THEN 'open' ELSE anomalies.status END""",
                (fingerprint,"service",service,kind,now,now,rows[-2]["bucket_ms"],current["bucket_ms"]+60_000,value,expected,normal_low,normal_high,delta,pct,samples,base_samples,2,severity,"open",unit,explanation,"Two consecutive buckets outside a robust matching-bucket median ± max(3×1.4826×MAD, absolute floor); minimum count and impact required. Proportions additionally use Wilson intervals.",baseline[0]["bucket_ms"],baseline[-1]["bucket_ms"]+60_000,json.dumps(limitations),json.dumps(contributors),json.dumps(trace_ids),now))
            found+=1
    from .structural_detectors import detect_structural
    return found + detect_structural(repository)


def run_jobs(repository: SQLiteRepository) -> dict[str,int]:
    started=int(time.time()*1000)
    with repository.transaction() as db: db.execute("INSERT INTO jobs(name,status,started_at_ms,detail) VALUES ('analytics','running',?,'') ON CONFLICT(name) DO UPDATE SET status='running',started_at_ms=excluded.started_at_ms,detail=''",(started,))
    retained=0
    if settings.retention_days>0:
        cutoff=int(time.time()*1000)-settings.retention_days*86_400_000
        with repository.transaction() as db:
            retained=db.execute("DELETE FROM events WHERE timestamp_ms<?",(cutoff,)).rowcount
    result={"retained_deletions":retained,"rollups":rebuild_rollups(repository),"edges":rebuild_topology(repository),"anomalies":detect_anomalies(repository)}
    with repository.connect() as db: db.execute("PRAGMA optimize")
    with repository.transaction() as db:
        db.execute("DELETE FROM dirty_buckets")
        db.execute("UPDATE jobs SET status='complete',finished_at_ms=?,detail=?,processed_count=? WHERE name='analytics'",(int(time.time()*1000),json.dumps(result),sum(result.values())))
    return result
