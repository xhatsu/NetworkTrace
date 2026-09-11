from __future__ import annotations
import math
from typing import Any, Dict, List, Optional
from backend.app.models.aggregate import MetricBucket
from backend.app.models.topology import ServiceEdge, PrincipalServiceEdge
from backend.app.repositories.db_context import get_connection, db_transaction
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.topology_repository import TopologyRepository

def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    values.sort()
    idx = int((len(values) - 1) * q)
    return values[min(idx, len(values) - 1)]

import json
import time

def aggregate_traces(
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    db_path: Optional[str] = None
) -> Dict[str, int]:
    agg_repo = AggregateRepository(db_path)
    top_repo = TopologyRepository(db_path)

    with get_connection(db_path) as db:
        if start_ms is None or end_ms is None:
            min_max = db.execute("SELECT (SELECT MIN(timestamp_ms) FROM traces), (SELECT MAX(timestamp_ms) FROM traces)").fetchone()
            if not min_max or min_max[0] is None:
                return {"1m_buckets": 0, "5m_buckets": 0, "service_edges": 0, "principal_edges": 0}

            chk_row = db.execute("SELECT cursor_json FROM checkpoints WHERE source='aggregation_cursor'").fetchone()
            if chk_row:
                try:
                    cursor_data = json.loads(chk_row[0])
                    cursor_ts = int(cursor_data.get("last_ts", min_max[0]))
                    start_ms = start_ms or max(min_max[0], cursor_ts - 300_000)
                except Exception:
                    start_ms = start_ms or min_max[0]
            else:
                start_ms = start_ms or min_max[0]
            end_ms = end_ms or (min_max[1] + 1000)

        # Recompute complete affected five-minute windows. Partial-window updates
        # would otherwise replace an existing 5m bucket with only the new rows.
        start_ms = (start_ms // 300_000) * 300_000
        end_ms = ((end_ms + 299_999) // 300_000) * 300_000

        # Pull raw traces grouped by 60-second window
        rows = db.execute("""
            SELECT
              (intDiv(timestamp_ms, 60000) * 60) as bucket_start,
              COALESCE(caller_service, '') as caller_service,
              target_service,
              COALESCE(principal_name, 'unknown') as principal_name,
              operation,
              duration_ms,
              CASE WHEN http_status >= 400 OR outcome = 'failure' THEN 1 ELSE 0 END as is_error
            FROM traces
            WHERE timestamp_ms >= ? AND timestamp_ms < ?
        """, (start_ms, end_ms)).fetchall()

    # In-memory grouping for exact percentile calculations
    groups: Dict[tuple, Dict[str, Any]] = {}
    groups_5m: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        b_start_int = int(r["bucket_start"])
        key = (b_start_int, r["caller_service"], r["target_service"], r["principal_name"], r["operation"])
        if key not in groups:
            groups[key] = {
                "count": 0,
                "errors": 0,
                "durations": []
            }
        g = groups[key]
        g["count"] += 1
        if r["is_error"]:
            g["errors"] += 1
        g["durations"].append(r["duration_ms"])
        key_5m = (
            (b_start_int // 300) * 300,
            r["caller_service"], r["target_service"],
            r["principal_name"], r["operation"],
        )
        g5 = groups_5m.setdefault(
            key_5m, {"count": 0, "errors": 0, "durations": []}
        )
        g5["count"] += 1
        g5["errors"] += r["is_error"]
        g5["durations"].append(r["duration_ms"])

    buckets_1m: List[MetricBucket] = []
    edges_map: Dict[tuple, Dict[str, Any]] = {}
    pe_map: Dict[tuple, Dict[str, Any]] = {}

    for (b_start, caller, target, principal, op), data in groups.items():
        durations = data["durations"]
        durations.sort()
        d_sum = sum(durations)
        cnt = data["count"]
        p50 = percentile(durations, 0.50)
        p95 = percentile(durations, 0.95)
        p99 = percentile(durations, 0.99)

        bucket = MetricBucket(
            bucket_start=int(b_start),
            bucket_size=60,
            caller_service=caller,
            target_service=target,
            principal_name=principal,
            operation=op,
            request_count=cnt,
            error_count=data["errors"],
            latency_sum=round(d_sum, 2),
            latency_avg=round(d_sum / max(1, cnt), 2),
            latency_min=round(durations[0], 2) if durations else 0.0,
            latency_max=round(durations[-1], 2) if durations else 0.0,
            latency_p50=round(p50, 2),
            latency_p95=round(p95, 2),
            latency_p99=round(p99, 2),
        )
        buckets_1m.append(bucket)

        # Collect service edges
        if caller and target:
            edge_key = (caller, target)
            if edge_key not in edges_map:
                edges_map[edge_key] = {
                    "first_seen": b_start, "last_seen": b_start,
                    "count": 0, "errors": 0, "d_sum": 0.0,
                    "p95": 0.0, "principals": set(), "operations": set()
                }
            em = edges_map[edge_key]
            em["first_seen"] = min(em["first_seen"], b_start)
            em["last_seen"] = max(em["last_seen"], b_start)
            em["count"] += cnt
            em["errors"] += data["errors"]
            em["d_sum"] += d_sum
            em["p95"] = max(em["p95"], p95)
            em["principals"].add(principal)
            em["operations"].add(op)

            # Collect principal service edges
            pe_key = (principal, caller, target)
            if pe_key not in pe_map:
                pe_map[pe_key] = {
                    "first_seen": b_start, "last_seen": b_start,
                    "count": 0, "errors": 0, "p95": 0.0
                }
            pm = pe_map[pe_key]
            pm["first_seen"] = min(pm["first_seen"], b_start)
            pm["last_seen"] = max(pm["last_seen"], b_start)
            pm["count"] += cnt
            pm["errors"] += data["errors"]
            pm["p95"] = max(pm["p95"], p95)

    # Save 1m buckets
    agg_repo.save_buckets(buckets_1m)

    # Roll up the raw samples so 5m p50/p95/p99 remain exact.
    buckets_5m: List[MetricBucket] = []
    for (b5_start, caller, target, principal, op), g5 in groups_5m.items():
        cnt = g5["count"]
        durations = g5["durations"]
        durations.sort()
        latency_sum = sum(durations)
        buckets_5m.append(MetricBucket(
            bucket_start=int(b5_start),
            bucket_size=300,
            caller_service=caller,
            target_service=target,
            principal_name=principal,
            operation=op,
            request_count=cnt,
            error_count=g5["errors"],
            latency_sum=round(latency_sum, 2),
            latency_avg=round(latency_sum / max(1, cnt), 2),
            latency_min=round(durations[0], 2) if durations else 0.0,
            latency_max=round(durations[-1], 2) if durations else 0.0,
            latency_p50=round(percentile(durations, 0.50), 2),
            latency_p95=round(percentile(durations, 0.95), 2),
            latency_p99=round(percentile(durations, 0.99), 2)
        ))

    agg_repo.save_buckets(buckets_5m)

    # Save edges
    service_edges = [
        ServiceEdge(
            caller_service=c,
            target_service=t,
            first_seen=val["first_seen"],
            last_seen=val["last_seen"],
            request_count=val["count"],
            error_count=val["errors"],
            error_rate=round(val["errors"] / max(1, val["count"]), 4),
            avg_latency=round(val["d_sum"] / max(1, val["count"]), 2),
            p95_latency=round(val["p95"], 2),
            principal_count=len(val["principals"]),
            operation_count=len(val["operations"])
        ) for (c, t), val in edges_map.items()
    ]

    principal_edges = [
        PrincipalServiceEdge(
            principal_name=p,
            caller_service=c,
            target_service=t,
            first_seen=val["first_seen"],
            last_seen=val["last_seen"],
            request_count=val["count"],
            error_rate=round(val["errors"] / max(1, val["count"]), 4),
            p95_latency=round(val["p95"], 2)
        ) for (p, c, t), val in pe_map.items()
    ]

    top_repo.save_edges(service_edges, principal_edges)

    with db_transaction(db_path) as db:
        now_ms = int(time.time() * 1000)
        db.execute("""
            INSERT INTO checkpoints (source, cursor_json, updated_at_ms)
            VALUES ('aggregation_cursor', ?, ?)
            ON CONFLICT(source) DO UPDATE SET cursor_json=excluded.cursor_json, updated_at_ms=excluded.updated_at_ms
        """, (json.dumps({"last_ts": end_ms}), now_ms))

    return {
        "1m_buckets": len(buckets_1m),
        "5m_buckets": len(buckets_5m),
        "service_edges": len(service_edges),
        "principal_edges": len(principal_edges)
    }
