"""Materialize compact time buckets so analytical reads stay cheap as trace volume grows."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.config import settings
from backend.app.models.aggregate import MetricBucket
from backend.app.models.topology import PrincipalServiceEdge, ServiceEdge
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.db_context import db_transaction, get_connection
from backend.app.repositories.topology_repository import TopologyRepository
from backend.app.repositories.interactive_topology_repository import InteractiveTopologyRepository

FIVE_MINUTES_MS = 300_000
AGGREGATION_SLICE_MS = 6 * 60 * 60 * 1000
CURSOR_BATCH_SIZE = 10_000
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
log = logging.getLogger("tracescope-hub")

_BUCKET_AGGREGATION_SQL = """
SELECT
  intDiv(timestamp_ms, {bucket_ms:UInt64}) * {bucket_seconds:UInt64} AS bucket_start,
  {bucket_seconds:UInt32} AS bucket_size,
  COALESCE(caller_service, '') AS caller_service,
  target_service,
  COALESCE(principal_name, 'unknown') AS principal_name,
  operation,
  count() AS request_count,
  countIf(http_status >= 400 OR outcome = 'failure') AS error_count,
  sum(duration_ms) AS latency_sum,
  avg(duration_ms) AS latency_avg,
  min(duration_ms) AS latency_min,
  max(duration_ms) AS latency_max,
  -- ClickHouse quantilesExact selects floor(n*q) with zero-based indexing.
  -- The immediately preceding Float64 levels preserve the established Python
  -- nearest-rank ceil(n*q)-1 result when n*q is an exact integer.
  quantilesExact(
    0.49999999999999994,
    0.9499999999999998,
    0.9899999999999999
  )(duration_ms) AS latency_quantiles
FROM traces
WHERE timestamp_ms >= {start_ms:Int64} AND timestamp_ms < {end_ms:Int64}
GROUP BY
  bucket_start, bucket_size, caller_service, target_service, principal_name, operation
"""

_SHADOW_AGGREGATION_SQL = """
INSERT INTO metric_buckets_agg (
  bucket_start, bucket_size, caller_service, target_service, principal_name,
  operation, request_count_state, error_count_state, latency_sum_state,
  latency_quantiles_state
)
SELECT
  intDiv(timestamp_ms, {bucket_ms:UInt64}) * {bucket_seconds:UInt64} AS bucket_start,
  {bucket_seconds:UInt32} AS bucket_size,
  COALESCE(caller_service, '') AS caller_service,
  target_service,
  COALESCE(principal_name, 'unknown') AS principal_name,
  operation,
  sumState(toUInt64(1)) AS request_count_state,
  countIfState(toUInt8(ifNull(http_status >= 400 OR outcome = 'failure', false))) AS error_count_state,
  sumState(toFloat64(duration_ms)) AS latency_sum_state,
  quantilesTDigestState(0.5, 0.95, 0.99)(toFloat64(duration_ms)) AS latency_quantiles_state
FROM traces
WHERE timestamp_ms >= {start_ms:Int64} AND timestamp_ms < {end_ms:Int64}
GROUP BY
  bucket_start, bucket_size, caller_service, target_service, principal_name, operation
"""


def _empty_result() -> Dict[str, int]:
    return {"1m_buckets": 0, "5m_buckets": 0, "service_edges": 0, "principal_edges": 0}


def _merge_result(total: Dict[str, int], current: Dict[str, int]) -> None:
    for key in total:
        total[key] += current[key]


def _aligned_window(start_ms: int, end_ms: int) -> Tuple[int, int]:
    """Expand a raw interval to complete five-minute buckets."""
    return (
        (start_ms // FIVE_MINUTES_MS) * FIVE_MINUTES_MS,
        ((end_ms + FIVE_MINUTES_MS - 1) // FIVE_MINUTES_MS) * FIVE_MINUTES_MS,
    )


def _save_checkpoint(cursor: Dict[str, Any], db_path: Optional[str]) -> None:
    with db_transaction(db_path) as db:
        db.execute(
            """
            INSERT INTO checkpoints (source, cursor_json, updated_at_ms)
            VALUES ('aggregation_cursor', ?, ?)
            """,
            (json.dumps(cursor, separators=(",", ":")), int(time.time() * 1000)),
        )


def _aggregation_query_settings() -> Dict[str, int]:
    max_memory = settings.aggregation_max_memory_usage
    # Leave at least half of the per-query allowance for the external aggregation
    # merge phase, even if an operator supplies an over-large spill threshold.
    external_group_by = min(
        settings.aggregation_external_group_by_bytes,
        max(1, max_memory // 2),
    )
    return {
        "max_memory_usage": max_memory,
        "max_bytes_before_external_group_by": external_group_by,
    }


def _query_bucket_rows(
    db: Any, bucket_size: int, start_ms: int, end_ms: int
) -> List[Dict[str, Any]]:
    result = db.client.query(
        _BUCKET_AGGREGATION_SQL,
        parameters={
            "bucket_ms": bucket_size * 1000,
            "bucket_seconds": bucket_size,
            "start_ms": start_ms,
            "end_ms": end_ms,
        },
        settings=_aggregation_query_settings(),
    )
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def _write_shadow_slice(start_ms: int, end_ms: int, db_path: Optional[str]) -> None:
    """Replace shadow states for a bounded event-time slice.

    AggregatingMergeTree states are additive, so writing a recomputed late-data
    window on top of an older state would double count it.  The synchronous delete
    makes this a repairable recomputation path rather than an incremental MV.
    """
    if not settings.aggregation_shadow_enabled:
        return
    with get_connection(db_path) as db:
        for bucket_size in (60, 300):
            db.execute(
                "DELETE FROM metric_buckets_agg WHERE bucket_size=? "
                "AND bucket_start>=? AND bucket_start<?",
                (bucket_size, start_ms // 1000, (end_ms + 999) // 1000),
            )
            db.client.command(
                _SHADOW_AGGREGATION_SQL,
                parameters={
                    "bucket_ms": bucket_size * 1000,
                    "bucket_seconds": bucket_size,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                },
                settings=_aggregation_query_settings(),
            )


def _metric_bucket(row: Dict[str, Any]) -> MetricBucket:
    p50, p95, p99 = row["latency_quantiles"]
    return MetricBucket(
        bucket_start=int(row["bucket_start"]),
        bucket_size=int(row["bucket_size"]),
        caller_service=row["caller_service"],
        target_service=row["target_service"],
        principal_name=row["principal_name"],
        operation=row["operation"],
        request_count=int(row["request_count"]),
        error_count=int(row["error_count"]),
        latency_sum=round(float(row["latency_sum"]), 2),
        latency_avg=round(float(row["latency_avg"]), 2),
        latency_min=round(float(row["latency_min"]), 2),
        latency_max=round(float(row["latency_max"]), 2),
        latency_p50=round(float(p50), 2),
        latency_p95=round(float(p95), 2),
        latency_p99=round(float(p99), 2),
    )


def _aggregate_slice(start_ms: int, end_ms: int, db_path: Optional[str]) -> Dict[str, int]:
    """Recompute one bounded slice while fetching only SQL-completed bucket rows."""
    agg_repo = AggregateRepository(db_path)
    top_repo = TopologyRepository(db_path)
    with get_connection(db_path) as db:
        rows_1m = _query_bucket_rows(db, 60, start_ms, end_ms)
        rows_5m = _query_bucket_rows(db, 300, start_ms, end_ms)

    buckets_1m = [_metric_bucket(row) for row in rows_1m]
    buckets_5m = [_metric_bucket(row) for row in rows_5m]
    edges_map: Dict[tuple, Dict[str, Any]] = {}
    principal_edges_map: Dict[tuple, Dict[str, Any]] = {}
    for bucket in buckets_1m:
        bucket_start = bucket.bucket_start
        caller = bucket.caller_service
        target = bucket.target_service
        principal = bucket.principal_name
        operation = bucket.operation
        count = bucket.request_count
        errors = bucket.error_count
        latency_sum = bucket.latency_sum
        p95 = bucket.latency_p95
        if caller and target:
            edge = edges_map.setdefault((caller, target), {
                "first_seen": bucket_start, "last_seen": bucket_start,
                "count": 0, "errors": 0, "latency_sum": 0.0,
                "p95": 0.0, "principals": set(), "operations": set(),
            })
            edge["first_seen"] = min(edge["first_seen"], bucket_start)
            edge["last_seen"] = max(edge["last_seen"], bucket_start)
            edge["count"] += count
            edge["errors"] += errors
            edge["latency_sum"] += latency_sum
            edge["p95"] = max(edge["p95"], p95)
            edge["principals"].add(principal)
            edge["operations"].add(operation)
            principal_edge = principal_edges_map.setdefault((principal, caller, target), {
                "first_seen": bucket_start, "last_seen": bucket_start,
                "count": 0, "errors": 0, "p95": 0.0,
            })
            principal_edge["first_seen"] = min(principal_edge["first_seen"], bucket_start)
            principal_edge["last_seen"] = max(principal_edge["last_seen"], bucket_start)
            principal_edge["count"] += count
            principal_edge["errors"] += errors
            principal_edge["p95"] = max(principal_edge["p95"], p95)

    agg_repo.save_buckets(buckets_1m)
    agg_repo.save_buckets(buckets_5m)
    _write_shadow_slice(start_ms, end_ms, db_path)

    # A rollup replacement is not complete until downstream anomaly evaluation
    # can discover it.  Keep these durable event-time markers separate from the
    # ingestion cursor: late rows advance by ingest_order while revising an old
    # bucket_start.  ReplacingMergeTree collapses repeated markers per window.
    if buckets_5m:
        revised_at_ms = int(time.time() * 1000)
        with db_transaction(db_path) as db:
            db.executemany(
                "INSERT INTO dirty_buckets(bucket_ms,reason,created_at_ms) VALUES (?,?,?)",
                [
                    (bucket_start * 1000, "aggregation-revised", revised_at_ms)
                    for bucket_start in sorted({bucket.bucket_start for bucket in buckets_5m})
                ],
            )

    service_edges = [
        ServiceEdge(
            caller_service=caller, target_service=target,
            first_seen=value["first_seen"], last_seen=value["last_seen"],
            request_count=value["count"], error_count=value["errors"],
            error_rate=round(value["errors"] / max(1, value["count"]), 4),
            avg_latency=round(value["latency_sum"] / max(1, value["count"]), 2),
            p95_latency=round(value["p95"], 2),
            principal_count=len(value["principals"]), operation_count=len(value["operations"]),
        )
        for (caller, target), value in edges_map.items()
    ]
    principal_edges = [
        PrincipalServiceEdge(
            principal_name=principal, caller_service=caller, target_service=target,
            first_seen=value["first_seen"], last_seen=value["last_seen"],
            request_count=value["count"],
            error_rate=round(value["errors"] / max(1, value["count"]), 4),
            p95_latency=round(value["p95"], 2),
        )
        for (principal, caller, target), value in principal_edges_map.items()
    ]
    top_repo.save_edges(service_edges, principal_edges)
    # Interactive topology uses a separate bounded 5-minute/current materialization.
    # It is a no-op in Elasticsearch mode, where the read repository performs
    # server-side aggregations against the configured ELK index.
    InteractiveTopologyRepository(db_path).materialize_slice(start_ms, end_ms)
    raw_rows = sum(bucket.request_count for bucket in buckets_1m)
    all_bucket_rows = len(buckets_1m) + len(buckets_5m)
    log.info(json.dumps({
        "event": "aggregation_slice_complete",
        "slice_start_ms": start_ms,
        "slice_end_ms": end_ms,
        "raw_rows": raw_rows,
        "bucket_rows_1m": len(buckets_1m),
        "bucket_rows_5m": len(buckets_5m),
        "raw_to_1m_bucket_ratio": round(raw_rows / max(1, len(buckets_1m)), 3),
        "raw_to_all_bucket_ratio": round(raw_rows / max(1, all_bucket_rows), 3),
    }, separators=(",", ":")))
    return {
        "1m_buckets": len(buckets_1m), "5m_buckets": len(buckets_5m),
        "service_edges": len(service_edges), "principal_edges": len(principal_edges),
    }


def _time_slices(start_ms: int, end_ms: int) -> List[Tuple[int, int]]:
    slices: List[Tuple[int, int]] = []
    current = start_ms
    while current < end_ms:
        slice_end = min(current + AGGREGATION_SLICE_MS, end_ms)
        slices.append((current, slice_end))
        current = slice_end
    return slices


def _affected_slices(timestamp_values: List[int]) -> List[Tuple[int, int]]:
    """Coalesce touched 5m buckets without ever spanning more than one bounded slice."""
    buckets = sorted({
        (timestamp_ms // FIVE_MINUTES_MS) * FIVE_MINUTES_MS
        for timestamp_ms in timestamp_values
    })
    if not buckets:
        return []
    slices: List[Tuple[int, int]] = []
    start = previous = buckets[0]
    for bucket in buckets[1:]:
        if bucket == previous + FIVE_MINUTES_MS and bucket < start + AGGREGATION_SLICE_MS:
            previous = bucket
            continue
        slices.append((start, previous + FIVE_MINUTES_MS))
        start = previous = bucket
    slices.append((start, previous + FIVE_MINUTES_MS))
    return slices


def _run_explicit_window(start_ms: int, end_ms: int, db_path: Optional[str]) -> Dict[str, int]:
    total = _empty_result()
    aligned_start, aligned_end = _aligned_window(start_ms, end_ms)
    for slice_start, slice_end in _time_slices(aligned_start, aligned_end):
        _merge_result(total, _aggregate_slice(slice_start, slice_end, db_path))
    return total


def _start_or_resume_bootstrap(db_path: Optional[str]) -> Optional[Dict[str, Any]]:
    start_time_ms = settings.worker_start_time_ms
    with get_connection(db_path) as db:
        checkpoint_row = db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source='aggregation_cursor'"
        ).fetchone()
        if checkpoint_row:
            try:
                checkpoint = json.loads(checkpoint_row[0])
            except (TypeError, ValueError, json.JSONDecodeError):
                checkpoint = {}
            if checkpoint.get("mode") == "bootstrap":
                if start_time_ms is not None and start_time_ms > int(checkpoint.get("next_slice_start_ms", 0)):
                    checkpoint["next_slice_start_ms"] = start_time_ms
                    _save_checkpoint(checkpoint, db_path)
                return checkpoint
            if "ingest_order" in checkpoint and "row_uid" in checkpoint:
                if start_time_ms is not None and start_time_ms > int(checkpoint.get("last_ts", 0)):
                    # Fast-forward cursor past historical traces
                    past_row = db.execute(
                        "SELECT ingest_order, toString(row_uid) FROM traces "
                        "WHERE timestamp_ms < ? ORDER BY ingest_order DESC, row_uid DESC LIMIT 1",
                        (start_time_ms,),
                    ).fetchone()
                    if past_row:
                        checkpoint["ingest_order"] = max(int(checkpoint.get("ingest_order", 0)), int(past_row[0]))
                        checkpoint["row_uid"] = str(past_row[1])
                    checkpoint["last_ts"] = start_time_ms
                    _save_checkpoint(checkpoint, db_path)
                return checkpoint

        where_clause = ""
        params: List[Any] = []
        if start_time_ms is not None:
            where_clause = "WHERE timestamp_ms >= ?"
            params.append(start_time_ms)

        bounds = db.execute(f"SELECT count(), MIN(timestamp_ms), MAX(timestamp_ms) FROM traces {where_clause}", params).fetchone()
        row_count = int(bounds[0]) if bounds else 0
        if not bounds or row_count == 0 or bounds[1] is None or int(bounds[1]) == 0:
            # If start_time_ms is configured but no traces exist at or after it yet,
            # checkpoint at the current latest trace so that all past data is skipped.
            if start_time_ms is not None:
                latest = db.execute(
                    "SELECT ingest_order, toString(row_uid) FROM traces "
                    "ORDER BY ingest_order DESC, row_uid DESC LIMIT 1"
                ).fetchone()
                if latest:
                    checkpoint = {
                        "mode": "incremental",
                        "ingest_order": int(latest[0]),
                        "row_uid": str(latest[1]),
                        "last_ts": start_time_ms,
                    }
                    _save_checkpoint(checkpoint, db_path)
                    return checkpoint
            return None

        eff_start = int(bounds[1])
        if start_time_ms is not None and start_time_ms > eff_start:
            eff_start = start_time_ms

        high_water = db.execute(
            "SELECT ingest_order, toString(row_uid) FROM traces "
            "ORDER BY ingest_order DESC, row_uid DESC LIMIT 1"
        ).fetchone()

    bootstrap_start, bootstrap_end = _aligned_window(eff_start, int(bounds[2]) + 1)
    checkpoint = {
        "mode": "bootstrap", "next_slice_start_ms": bootstrap_start,
        "bootstrap_end_ms": bootstrap_end,
        "high_water_ingest_order": int(high_water[0]),
        "high_water_row_uid": str(high_water[1]),
    }
    _save_checkpoint(checkpoint, db_path)
    return checkpoint


def _run_bootstrap(checkpoint: Dict[str, Any], db_path: Optional[str]) -> Dict[str, int]:
    total = _empty_result()
    next_start = int(checkpoint["next_slice_start_ms"])
    bootstrap_end = int(checkpoint["bootstrap_end_ms"])
    for slice_start, slice_end in _time_slices(next_start, bootstrap_end):
        _merge_result(total, _aggregate_slice(slice_start, slice_end, db_path))
        checkpoint["next_slice_start_ms"] = slice_end
        _save_checkpoint(checkpoint, db_path)
    incremental_checkpoint = {
        "mode": "incremental",
        "ingest_order": int(checkpoint["high_water_ingest_order"]),
        "row_uid": str(checkpoint["high_water_row_uid"]),
        "last_ts": bootstrap_end,
    }
    _save_checkpoint(incremental_checkpoint, db_path)
    checkpoint.clear()
    checkpoint.update(incremental_checkpoint)
    return total


def _run_incremental(checkpoint: Dict[str, Any], db_path: Optional[str]) -> Dict[str, int]:
    total = _empty_result()
    cursor_order = int(checkpoint.get("ingest_order", 0))
    cursor_uid = str(checkpoint.get("row_uid", ZERO_UUID))
    last_ts = int(checkpoint.get("last_ts", 0))
    start_time_ms = settings.worker_start_time_ms
    while True:
        with get_connection(db_path) as db:
            where_sql = "WHERE (ingest_order, row_uid) > (?, toUUID(?))"
            params: List[Any] = [cursor_order, cursor_uid]
            if start_time_ms is not None:
                where_sql += " AND timestamp_ms >= ?"
                params.append(start_time_ms)
            params.append(CURSOR_BATCH_SIZE)
            rows = db.execute(
                f"SELECT ingest_order, toString(row_uid) AS cursor_uid, timestamp_ms FROM traces "
                f"{where_sql} "
                f"ORDER BY ingest_order, row_uid LIMIT ?",
                params,
            ).fetchall()
        if not rows:
            break
        timestamps = [int(row["timestamp_ms"]) for row in rows]
        for slice_start, slice_end in _affected_slices(timestamps):
            _merge_result(total, _aggregate_slice(slice_start, slice_end, db_path))
        last_row = rows[-1]
        cursor_order = int(last_row["ingest_order"])
        cursor_uid = str(last_row["cursor_uid"])
        last_ts = max(last_ts, max(timestamps) + 1)
        checkpoint.update({
            "mode": "incremental", "ingest_order": cursor_order,
            "row_uid": cursor_uid, "last_ts": last_ts,
        })
        _save_checkpoint(checkpoint, db_path)
    return total


def aggregate_traces(
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    db_path: Optional[str] = None,
) -> Dict[str, int]:
    """Build rollups in bounded slices and advance only durable aggregation cursors."""
    if (start_ms is None) != (end_ms is None):
        raise ValueError("start_ms and end_ms must be provided together")
    if start_ms is not None and end_ms is not None:
        if end_ms <= start_ms:
            return _empty_result()
        return _run_explicit_window(start_ms, end_ms, db_path)

    checkpoint = _start_or_resume_bootstrap(db_path)
    if checkpoint is None:
        return _empty_result()
    total = _empty_result()
    if checkpoint.get("mode") == "bootstrap":
        _merge_result(total, _run_bootstrap(checkpoint, db_path))
    _merge_result(total, _run_incremental(checkpoint, db_path))
    return total


def backfill_shadow_aggregates(db_path: Optional[str] = None) -> Dict[str, int]:
    """Replay raw event-time slices into shadow states with an independent cursor."""
    if not settings.aggregation_shadow_enabled:
        return {"shadow_slices": 0}
    source = "aggregation_shadow_cursor"
    with get_connection(db_path) as db:
        checkpoint_row = db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source=?", (source,)
        ).fetchone()
        bounds = db.execute("SELECT min(timestamp_ms),max(timestamp_ms) FROM traces").fetchone()
    if not bounds or bounds[0] is None:
        return {"shadow_slices": 0}
    start, end = _aligned_window(int(bounds[0]), int(bounds[1]) + 1)
    if checkpoint_row:
        try:
            cursor = json.loads(checkpoint_row[0])
            start = max(start, int(cursor.get("next_slice_start_ms", start)))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    count = 0
    for slice_start, slice_end in _time_slices(start, end):
        _write_shadow_slice(slice_start, slice_end, db_path)
        count += 1
        with db_transaction(db_path) as db:
            db.execute(
                "INSERT INTO checkpoints(source,cursor_json,updated_at_ms) VALUES(?,?,?)",
                (
                    source,
                    json.dumps({"next_slice_start_ms": slice_end}, separators=(",", ":")),
                    int(time.time() * 1000),
                ),
            )
    return {"shadow_slices": count}
