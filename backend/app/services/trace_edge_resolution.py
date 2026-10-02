"""Caller resolution for OTLP spans stored in ClickHouse ``traces``.

With ``OTEL_TRACE_PIPELINE_MODE=clickhouse`` nothing upstream resolves callers: OBI
eBPF spans carry no ``peer.service`` on the server side, and every span (server,
client, internal) is one stored row. Counting each row as a request would double
count calls and invent a ``unknown-downstream`` service.

Before a slice is aggregated, this module applies the same rules as the ELK path
(:mod:`backend.app.services.trace_edges`) to the slice's stored rows and records the
outcome in ``trace_edge_resolutions``. Aggregations read ``traces`` through
:func:`traces_source_sql`, which overlays that table:

* a server span takes its resolved caller (or keeps its explicit caller),
* a client span (root, or made in the middle of a request) paired with the callee's
  server span is dropped, because the server span already counts the request; an
  unpaired one is the only record of a call into an uninstrumented service and
  becomes ``caller -> peer`` (``client_retargeted`` for a root client, ``client_exit``
  for an outgoing call made while serving a request),
* internal spans and client spans with no known peer are not requests and are dropped.

Raw ``traces`` rows are never modified. User behavior does not read ``traces``: it reads
``principal_activity_5m`` (:mod:`backend.app.services.principal_activity`), which is
materialized from this overlay.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.config import settings
from backend.app.repositories.db_context import get_connection
from backend.app.services.trace_edges import (
    DEFAULT_SKEW_US,
    MAX_CORRELATED_CALL_US,
    Resolution,
    TraceDoc,
    parse_ip_map,
    resolve,
)

log = logging.getLogger("tracescope-hub")

RESOLUTION_COLUMNS = [
    "trace_id", "span_id", "timestamp_ms", "override_caller", "caller_service",
    "target_service", "method", "confidence", "skip", "updated_at_ms",
]
UNKNOWN_PEER = "unknown-downstream"
# Confidence recorded for each resolution method (shown as relationship evidence).
CONFIDENCE = {
    "trace_parent": 1.0,
    "trace_intermediary": 0.9,
    "trace_peer_match": 0.9,
    "network_ip": 0.6,
    "time_correlated": 0.5,
    "client_retargeted": 0.8,
    # Outgoing call seen only from the caller's side (callee not instrumented).
    "client_exit": 0.7,
}
_SERVER_KINDS = {"server", "consumer"}
_CLIENT_KINDS = {"client", "producer"}

_FETCH_SQL = """
SELECT trace_id, span_id, parent_span_id, service_name, span_kind, target_service,
       caller_service, timestamp_ms, duration_us, observed_ip, caller_ip
FROM traces
WHERE timestamp_ms >= {start_ms:Int64} AND timestamp_ms < {end_ms:Int64}
  AND is_agent_trace = 0
"""

_SOURCE_SQL = """(
  SELECT
    t.* EXCEPT (caller_service, target_service, caller_resolution_method, caller_confidence),
    if(r.res_override = 1, r.res_caller, t.caller_service) AS caller_service,
    if(r.res_target != '', r.res_target, t.target_service) AS target_service,
    if(r.res_method != '', r.res_method, t.caller_resolution_method) AS caller_resolution_method,
    if(r.res_method != '', r.res_confidence, t.caller_confidence) AS caller_confidence
  FROM traces AS t
  LEFT JOIN (
    -- Inner names differ from the table's columns: an alias equal to its own argument
    -- (argMax(skip, ...) AS skip) is resolved to the wrong value by ClickHouse.
    SELECT trace_id, span_id,
           argMax(override_caller, updated_at_ms) AS res_override,
           argMax(caller_service, updated_at_ms) AS res_caller,
           argMax(target_service, updated_at_ms) AS res_target,
           argMax(method, updated_at_ms) AS res_method,
           argMax(confidence, updated_at_ms) AS res_confidence,
           argMax(skip, updated_at_ms) AS res_skip
    FROM trace_edge_resolutions
    WHERE timestamp_ms >= {start_ms:Int64} AND timestamp_ms < {end_ms:Int64}
    GROUP BY trace_id, span_id
  ) AS r ON t.trace_id = r.trace_id AND t.span_id = r.span_id
  WHERE t.timestamp_ms >= {start_ms:Int64} AND t.timestamp_ms < {end_ms:Int64}
    AND r.res_skip = 0
)"""


def traces_source_sql() -> str:
    """FROM-clause source for aggregations: ``traces`` with resolved callers overlaid.

    Uses the query parameters ``start_ms`` and ``end_ms``. Without resolution it is the
    plain table, so callers behave exactly as before.
    """
    return _SOURCE_SQL if settings.trace_edge_resolution_enabled else "traces"


@dataclass
class SliceResolution:
    rows: List[List[Any]] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


def _kind(span_kind: str) -> str:
    kind = (span_kind or "").lower()
    if kind in _SERVER_KINDS:
        return "server"
    if kind in _CLIENT_KINDS:
        return "client"
    return "internal"


def _doc_from_row(row: Dict[str, Any]) -> Optional[TraceDoc]:
    trace_id = str(row["trace_id"] or "").strip().lower()
    span_id = str(row["span_id"] or "").strip()
    service = str(row["service_name"] or "").strip()
    if not (trace_id and span_id and service):
        return None
    kind = _kind(row["span_kind"])
    parent = str(row["parent_span_id"] or "").strip() or None
    target = str(row["target_service"] or "").strip()
    start_us = int(row["timestamp_ms"]) * 1000
    duration_us = int(row["duration_us"] or 0)
    peer = ""
    explicit = ""
    client_ip = ""
    if kind == "client":
        if target and target != UNKNOWN_PEER:
            peer = target.lower()
    elif kind == "server":
        explicit = str(row["caller_service"] or "").strip()
        client_ip = str(row["observed_ip"] or row["caller_ip"] or "").strip()
    return TraceDoc(
        doc_id=span_id, trace_id=trace_id, kind=kind, service=service, parent_id=parent,
        peer=peer, peer_host=target if peer else "", start_us=start_us,
        end_us=start_us + max(0, duration_us), client_ip=client_ip,
        explicit_caller=explicit, root_client=bool(kind == "client" and not parent and peer),
    )


def resolve_rows(
    rows: List[Dict[str, Any]],
    start_ms: int,
    end_ms: int,
    ip_map: Optional[List[Tuple[Any, str]]] = None,
    skew_us: int = DEFAULT_SKEW_US,
    now_ms: Optional[int] = None,
) -> SliceResolution:
    """Resolve every span with ``start_ms <= timestamp_ms < end_ms``.

    ``rows`` may extend beyond the slice: those spans only provide trace context.
    """
    updated_at = int(time.time() * 1000) if now_ms is None else now_ms
    docs: Dict[Tuple[str, str], TraceDoc] = {}
    in_scope: Dict[Tuple[str, str], int] = {}
    for row in rows:
        doc = _doc_from_row(row)
        if doc is None:
            continue
        key = (doc.trace_id, doc.doc_id)
        docs[key] = doc
        if start_ms <= int(row["timestamp_ms"]) < end_ms:
            in_scope[key] = int(row["timestamp_ms"])

    result = resolve(
        docs.values(), targets={key[1] for key in in_scope}, ip_map=ip_map, skew_us=skew_us,
        exit_clients=True,
    )
    # trace_edges keys resolutions by span ID (random 64-bit IDs), as the ELK path does.
    out = SliceResolution(stats=dict(result.stats))
    resolved_by_span = result.resolutions
    for key, timestamp_ms in in_scope.items():
        doc = docs[key]
        resolution = resolved_by_span.get(doc.doc_id)
        override, caller, target, method, skip = 0, "", "", "", 0
        if doc.kind == "server":
            if resolution is not None:
                override, caller, method = 1, resolution.caller or "", resolution.method
        elif doc.kind == "client" and doc.peer:
            if resolution is None:
                # Cannot happen for a client with a peer, but never count it twice.
                skip, method = 1, "client_unresolved"
            elif resolution.skip:
                skip, method = 1, resolution.method
            elif resolution.target:
                override, caller, target, method = 1, resolution.caller or doc.service, resolution.target, resolution.method
        else:
            skip, method = 1, "not_a_transaction"
        out.rows.append([
            doc.trace_id, doc.doc_id, timestamp_ms, override, caller, target, method,
            CONFIDENCE.get(method, 0.0), skip, updated_at,
        ])
    return out


def resolve_slice(start_ms: int, end_ms: int, db_path: Optional[str] = None) -> Dict[str, int]:
    """Resolve and persist callers for one aggregation slice. No-op when disabled."""
    if not settings.trace_edge_resolution_enabled or end_ms <= start_ms:
        return {"resolved_rows": 0}
    context_us = MAX_CORRELATED_CALL_US + DEFAULT_SKEW_US
    context_ms = context_us // 1000
    skew_us = max(0, int(settings.trace_edge_skew_ms * 1000))
    with get_connection(db_path) as db:
        result = db.client.query(
            _FETCH_SQL,
            parameters={"start_ms": start_ms - context_ms, "end_ms": end_ms + context_ms},
        )
        rows = [dict(zip(result.column_names, values)) for values in result.result_rows]
        resolution = resolve_rows(
            rows, start_ms, end_ms, ip_map=parse_ip_map(settings.service_ip_map), skew_us=skew_us,
        )
        if resolution.rows:
            db.client.insert(
                "trace_edge_resolutions", resolution.rows, column_names=RESOLUTION_COLUMNS,
            )
    log.info("trace_edge_resolution %s", {
        "slice_start_ms": start_ms, "slice_end_ms": end_ms,
        "spans": len(resolution.rows), **resolution.stats,
    })
    return {"resolved_rows": len(resolution.rows)}
