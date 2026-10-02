"""Per-credential five-minute activity rollup (``principal_activity_5m``).

User behavior (principal intelligence, behavioral detectors and the user/IP anomaly
detector) reads only this rollup. It is the single place where raw ``traces`` rows are
turned into user-behavior input, so behavior keeps working after the one-day raw trace
TTL and never queries spans at request or detection time.

The worker calls :func:`materialize_principal_activity` for every aggregation slice,
after caller resolution, so the rollup carries the same resolved callers and targets as
``metric_buckets``. A slice is rewritten whole. A slice whose raw traces have already
expired is left untouched, which keeps the rollup's 35-day history.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from backend.config import settings
from backend.app.repositories.db_context import get_connection
from backend.app.services.trace_edge_resolution import traces_source_sql

log = logging.getLogger("tracescope-hub")

BUCKET_MS = 300_000
ANONYMOUS_PRINCIPALS = ("unknown", "-anonymous-", "anonymous", "")
_ANONYMOUS_SQL = ", ".join(f"'{name}'" for name in ANONYMOUS_PRINCIPALS)

DIMENSIONS = (
    "environment", "principal_id", "principal_name", "caller_service", "caller_instance",
    "source_ip", "ip_resolution", "source_group", "target_service", "target_instance",
    "target_ip", "target_port", "operation", "operation_key", "http_method", "auth_evidence",
)
COLUMNS = (
    "bucket_start_ms", "row_key", *DIMENSIONS, "request_count", "error_count",
    "auth_failure_count", "auth_success_count", "first_seen_ms", "last_seen_ms",
    "last_failure_ms", "last_success_ms", "sample_trace_ids", "updated_at_ms",
)

_INSERT_SQL = f"""
INSERT INTO principal_activity_5m ({", ".join(COLUMNS)})
SELECT
  bucket_start_ms,
  cityHash64({", ".join(f"r_{name}" for name in DIMENSIONS)}) AS row_key,
  {", ".join(f"r_{name} AS {name}" for name in DIMENSIONS)},
  count() AS request_count,
  countIf(is_error) AS error_count,
  countIf(auth_outcome = 'failure') AS auth_failure_count,
  countIf(auth_outcome = 'success') AS auth_success_count,
  min(ts) AS first_seen_ms,
  max(ts) AS last_seen_ms,
  maxIf(ts, auth_outcome = 'failure') AS last_failure_ms,
  maxIf(ts, auth_outcome = 'success') AS last_success_ms,
  groupUniqArray(3)(sample_trace) AS sample_trace_ids,
  {{updated_at_ms:UInt64}} AS updated_at_ms
FROM (
  -- Every output name differs from the traces columns: an alias equal to a column it
  -- reads (ifNull(caller_service, '') AS caller_service) is ambiguous in ClickHouse.
  SELECT
    intDiv(timestamp_ms, {BUCKET_MS}) * {BUCKET_MS} AS bucket_start_ms,
    timestamp_ms AS ts,
    trace_id AS sample_trace,
    toString(auth_result) AS auth_outcome,
    if(service_environment = '', 'production', toString(service_environment)) AS r_environment,
    ifNull(nullIf(principal_id, ''), concat(r_environment, ':', toString(principal_name))) AS r_principal_id,
    toString(principal_name) AS r_principal_name,
    ifNull(caller_service, '') AS r_caller_service,
    ifNull(caller_instance, '') AS r_caller_instance,
    ifNull(caller_ip, '') AS r_source_ip,
    toString(ip_resolution) AS r_ip_resolution,
    ifNull(source_group, '') AS r_source_group,
    toString(target_service) AS r_target_service,
    ifNull(target_instance, '') AS r_target_instance,
    ifNull(target_ip, '') AS r_target_ip,
    ifNull(target_port, 0) AS r_target_port,
    operation AS r_operation,
    ifNull(nullIf(operation_key, ''), operation) AS r_operation_key,
    ifNull(http_method, '') AS r_http_method,
    toString(auth_evidence) AS r_auth_evidence,
    (ifNull(http_status, 0) >= 400 OR ifNull(outcome, '') = 'failure') AS is_error
  FROM __TRACES__
  WHERE timestamp_ms >= {{start_ms:Int64}} AND timestamp_ms < {{end_ms:Int64}}
    AND principal_name NOT IN ({_ANONYMOUS_SQL})
)
GROUP BY bucket_start_ms, {", ".join(f"r_{name}" for name in DIMENSIONS)}
"""


def _aligned(start_ms: int, end_ms: int) -> tuple[int, int]:
    return start_ms // BUCKET_MS * BUCKET_MS, -(-end_ms // BUCKET_MS) * BUCKET_MS


def materialize_principal_activity(start_ms: int, end_ms: int, db_path: Optional[str] = None) -> int:
    """Rewrite the rollup for ``[start_ms, end_ms)`` (widened to whole 5-minute buckets).

    Returns the number of rollup rows written. Does nothing when no raw trace remains in
    the window, so expired windows keep their rollup rows.
    """
    start_ms, end_ms = _aligned(int(start_ms), int(end_ms))
    if end_ms <= start_ms:
        return 0
    params = {"start_ms": start_ms, "end_ms": end_ms, "updated_at_ms": int(time.time() * 1000)}
    query_settings = {
        "max_memory_usage": settings.aggregation_max_memory_usage,
        "max_bytes_before_external_group_by": min(
            settings.aggregation_external_group_by_bytes, settings.aggregation_max_memory_usage // 2,
        ),
    }
    with get_connection(db_path) as db:
        raw = db.client.query(
            "SELECT count() FROM traces WHERE timestamp_ms >= {start_ms:Int64} AND timestamp_ms < {end_ms:Int64}",
            parameters=params,
        ).result_rows[0][0]
        if not raw:
            return 0
        db.execute(
            "DELETE FROM principal_activity_5m WHERE bucket_start_ms >= ? AND bucket_start_ms < ?",
            (start_ms, end_ms),
        )
        # Stamped after the (synchronous, possibly slow) DELETE so readers paging by
        # updated_at_ms cannot already be past this value when the rows appear.
        params["updated_at_ms"] = int(time.time() * 1000)
        db.client.command(
            _INSERT_SQL.replace("__TRACES__", traces_source_sql()),
            parameters=params, settings=query_settings,
        )
        written = db.client.query(
            "SELECT count() FROM principal_activity_5m "
            "WHERE bucket_start_ms >= {start_ms:Int64} AND bucket_start_ms < {end_ms:Int64}",
            parameters=params,
        ).result_rows[0][0]
    log.info("principal_activity_5m %s", {"slice_start_ms": start_ms, "slice_end_ms": end_ms, "rows": written})
    return int(written)
