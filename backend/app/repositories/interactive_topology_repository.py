"""Bounded query and materialization layer for the interactive topology.

ClickHouse deployments read the five-minute/current relationship tables written
by the analytics worker. Elasticsearch deployments use server-side composite
aggregations over the configured APM index and never copy application traces
into ClickHouse for this feature.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from backend.config import settings
from backend.app.repositories.db_context import db_transaction, get_connection
from backend.app.repositories.elasticsearch_trace_repository import ElasticsearchTraceRepository
from backend.app.services.normalization import classify_source_ip_role

log = logging.getLogger("tracescope-interactive-topology")

ANONYMOUS = {"", "unknown", "-anonymous-"}
MAX_LIMIT = 500
WINDOW_SECONDS = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}
EVIDENCE_DIRECT = {"OTEL_PARENT_CHILD", "OTEL_CLIENT_SERVER", "HTTP_NETWORK_OBSERVED"}


def canonical_service(value: Any) -> str:
    """Return a bounded, stable service dimension without changing its identity."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:200] or "unknown"


def canonical_principal(value: Any) -> str:
    text = str(value or "").strip()[:200]
    return "-anonymous-" if text in ANONYMOUS else text


def canonical_api(value: Any, service: str = "") -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text or text == "unknown":
        return f"{service}/unknown" if service else "unknown"
    text = re.sub(r"/[0-9a-fA-F-]{16,}(?=/|$)", "/{id}", text)
    text = re.sub(r"/\d+(?=/|$)", "/{id}", text)
    return text[:500]


def evidence_for(method: Any, confidence: Any = 0.0) -> Tuple[str, str, float]:
    method_text = str(method or "").lower()
    try:
        score = max(0.0, min(1.0, float(confidence or 0.0)))
    except (TypeError, ValueError):
        score = 0.0
    if method_text == "client_span":
        return "OTEL_CLIENT_SERVER", "OTel client span to peer service", max(score, 1.0)
    if method_text == "trace_parent":
        return "OTEL_PARENT_CHILD", "OTel parent/child service relationship", max(score, 1.0)
    if method_text == "header":
        return "HTTP_NETWORK_OBSERVED", "HTTP peer/header service relationship", max(score, 0.8)
    if method_text == "network_ip":
        return "IP_SERVICE_INFERRED", "Service inferred from network peer IP", max(score, 0.4)
    return "IP_SERVICE_INFERRED", "Relationship inferred from incomplete telemetry", score


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value or 0.0)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def encode_cursor(values: Sequence[str]) -> str:
    raw = json.dumps(list(values), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    if len(value) > 1024:
        raise ValueError("cursor is too long")
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("cursor is invalid") from None
    if not isinstance(decoded, list) or len(decoded) != 4 or not all(isinstance(x, str) for x in decoded):
        raise ValueError("cursor is invalid")
    return decoded


class InteractiveTopologyRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._es_repo = ElasticsearchTraceRepository()

    @property
    def backend(self) -> str:
        if settings.storage_backend in ("elasticsearch", "elk"):
            return "elasticsearch"
        return "clickhouse"

    def data_bounds_ms(self) -> Tuple[Optional[int], Optional[int]]:
        if self.backend == "elasticsearch":
            return self._es_bounds_ms()
        with get_connection(self.db_path) as db:
            row = db.execute(
                "SELECT min(first_seen_ms), max(last_seen_ms) FROM topology_service_edges_5m FINAL"
            ).fetchone()
            if not row or row[0] is None:
                row = db.execute("SELECT min(timestamp_ms), max(timestamp_ms) FROM traces").fetchone()
        if not row or row[0] is None:
            return None, None
        return _safe_int(row[0]), _safe_int(row[1])

    def resolve_window(
        self,
        window: str = "5m",
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        if window == "all":
            duration = None
        elif window in WINDOW_SECONDS:
            duration = WINDOW_SECONDS[window]
        else:
            raise ValueError("window must be one of 5m, 15m, 1h, 6h, 24h, 7d, 30d, all")

        bound_start, bound_end = self.data_bounds_ms()
        now_ms = int(time.time() * 1000)
        end = _safe_int(end_ms, 0) if end_ms is not None else (bound_end or now_ms)
        start = _safe_int(start_ms, 0) if start_ms is not None else 0
        if start and end and start >= end:
            raise ValueError("from must be earlier than to")
        if not start:
            if duration is None:
                start = bound_start or max(0, end - 30 * 86400 * 1000)
            else:
                start = end - duration * 1000
        if duration is not None and end - start > settings.max_range_days * 86400 * 1000:
            raise ValueError("topology time range is too large")
        return {
            "start_ms": start,
            "end_ms": end,
            "duration_seconds": max(1, int((end - start) / 1000)),
            "label": window,
            "baseline": "previous_window",
        }

    # ------------------------------------------------------------------
    # Worker-side bounded materialization
    # ------------------------------------------------------------------
    def materialize_slice(self, start_ms: int, end_ms: int) -> int:
        """Materialize one raw event-time slice; never used for ES application traces."""
        if self.backend == "elasticsearch" or end_ms <= start_ms:
            return 0
        with get_connection(self.db_path) as db:
            prior_rows = db.execute(
                "SELECT DISTINCT principal, source_ip FROM topology_principal_ip_5m FINAL WHERE bucket_start < ?",
                (start_ms // 1000,),
            ).fetchall()
            prior_ips = {(str(row[0]), str(row[1])) for row in prior_rows}
            # Use one bounded server-side aggregation and collapse the already
            # grouped result into each topology cardinality in Python.
            grouped = self._materialize_queries(db, start_ms, end_ms, prior_ips)
            now_ms = int(time.time() * 1000)
            count = 0
            for table, columns, rows in grouped:
                if not rows:
                    continue
                if table.endswith("_5m"):
                    db.execute(
                        f"DELETE FROM {table} WHERE bucket_start >= ? AND bucket_start < ?",
                        (start_ms // 1000, (end_ms + 299999) // 300000 * 300),
                    )
                db.executemany(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    [row + [now_ms] for row in rows],
                )
                count += len(rows)
        return count

    def _materialize_queries(self, db: Any, start_ms: int, end_ms: int, prior_ips: set[Tuple[str, str]]) -> List[Tuple[str, List[str], List[List[Any]]]]:
        """Run bounded ClickHouse aggregations and shape them for block inserts."""
        common = """
            intDiv(timestamp_ms, 300000) * 300 AS bucket_start,
            coalesce(nullIf(trim(caller_service), ''), '') AS caller_service,
            coalesce(nullIf(trim(target_service), ''), 'unknown') AS target_service,
            coalesce(nullIf(trim(operation_key), ''), operation) AS raw_api,
            if(principal_name IN ('', 'unknown', '-anonymous-'), '-anonymous-', principal_name) AS principal,
            if(caller_resolution_method = 'client_span', 'OTEL_CLIENT_SERVER',
               if(caller_resolution_method = 'trace_parent', 'OTEL_PARENT_CHILD',
                  if(caller_resolution_method = 'header', 'HTTP_NETWORK_OBSERVED', 'IP_SERVICE_INFERRED'))) AS evidence_type,
            if(caller_resolution_method = 'client_span', 'OTel client span to peer service',
               if(caller_resolution_method = 'trace_parent', 'OTel parent/child service relationship',
                  if(caller_resolution_method = 'header', 'HTTP peer/header service relationship', 'Service inferred from network peer IP'))) AS evidence_detail,
            greatest(0.0, least(1.0, toFloat64(caller_confidence))) AS confidence,
            if(effective_client_ip IS NULL OR effective_client_ip IN ('', 'unavailable', 'unknown'),
               ifNull(observed_ip, ''), effective_client_ip) AS source_ip
        """
        measures = """
            count() request_count,
            countIf(http_status >= 400 OR outcome = 'failure') error_count,
            countIf(http_status >= 400 AND http_status < 500) http_4xx_count,
            countIf(http_status >= 500) http_5xx_count,
            countIf(outcome = 'timeout' OR http_status = 504) timeout_count,
            countIf(outcome = 'tcp_reset') tcp_reset_count,
            countIf(outcome IN ('incomplete', 'aborted')) incomplete_count,
            sum(duration_ms) latency_sum,
            quantilesExact(0.5, 0.95, 0.99)(duration_ms) latency_quantiles,
            sum(ifNull(request_bytes, 0)) request_bytes,
            sum(ifNull(response_bytes, 0)) response_bytes,
            uniqExactIf(principal, principal != '-anonymous-') unique_principals,
            uniqExactIf(source_ip, source_ip NOT IN ('', 'unavailable', 'unknown')) unique_source_ips,
            countIf(principal = '-anonymous-') anonymous_requests,
            min(timestamp_ms) first_seen_ms, max(timestamp_ms) last_seen_ms
        """
        base = "FROM traces WHERE timestamp_ms >= {start_ms:Int64} AND timestamp_ms < {end_ms:Int64}"
        params = {"start_ms": start_ms, "end_ms": end_ms}

        def query(group_by: str) -> List[Dict[str, Any]]:
            result = db.client.query(
                f"SELECT {common}, {measures} {base} GROUP BY {group_by}",
                parameters=params,
                settings={"max_memory_usage": settings.aggregation_max_memory_usage,
                          "max_bytes_before_external_group_by": min(settings.aggregation_external_group_by_bytes, settings.aggregation_max_memory_usage // 2)},
            )
            return [dict(zip(result.column_names, row)) for row in result.result_rows]

        def normal(row: Dict[str, Any]) -> List[Any]:
            quantiles = row.get("latency_quantiles") or (0.0, 0.0, 0.0)
            return [
                _safe_int(row.get("bucket_start")), canonical_service(row.get("caller_service")),
                canonical_service(row.get("target_service")), canonical_api(row.get("raw_api"), row.get("target_service")),
                canonical_principal(row.get("principal")), _safe_int(row.get("request_count")),
                _safe_int(row.get("error_count")), _safe_int(row.get("http_4xx_count")),
                _safe_int(row.get("http_5xx_count")), _safe_int(row.get("timeout_count")),
                _safe_int(row.get("tcp_reset_count")), _safe_int(row.get("incomplete_count")),
                _safe_float(row.get("latency_sum")), _safe_float(quantiles[0]), _safe_float(quantiles[1]),
                _safe_float(quantiles[2]), _safe_int(row.get("request_bytes")), _safe_int(row.get("response_bytes")),
                _safe_int(row.get("unique_principals")), _safe_int(row.get("unique_source_ips")),
                _safe_int(row.get("anonymous_requests")), _safe_int(row.get("first_seen_ms")),
                _safe_int(row.get("last_seen_ms")), str(row.get("evidence_type") or "IP_SERVICE_INFERRED"),
                str(row.get("evidence_detail") or ""), _safe_float(row.get("confidence")),
            ]

        all_group_fields = "bucket_start, caller_service, target_service, raw_api, principal, evidence_type, evidence_detail, confidence, source_ip"
        base_rows = query(all_group_fields)
        service_rows = list(base_rows)
        # The service query should not be principal/API/IP-specific; collapse the
        # server result in Python only across already grouped bounded rows.
        service_rows = self._collapse_rows(service_rows, ["bucket_start", "caller_service", "target_service", "evidence_type", "evidence_detail", "confidence"])
        api_rows = list(base_rows)
        api_rows = self._collapse_rows(api_rows, ["bucket_start", "caller_service", "target_service", "raw_api", "evidence_type", "evidence_detail", "confidence"])
        principal_rows = list(base_rows)
        principal_rows = self._collapse_rows(principal_rows, ["bucket_start", "caller_service", "target_service", "raw_api", "principal", "evidence_type", "evidence_detail", "confidence"])
        ip_rows = list(base_rows)
        return [
            ("topology_service_edges_5m", ["bucket_start", "caller_service", "target_service", "request_count", "error_count", "http_4xx_count", "http_5xx_count", "timeout_count", "tcp_reset_count", "incomplete_count", "latency_sum", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "request_bytes", "response_bytes", "unique_principals", "unique_source_ips", "anonymous_requests", "first_seen_ms", "last_seen_ms", "evidence_type", "evidence_detail", "confidence", "updated_at_ms"], [self._service_row(row) for row in service_rows]),
            ("topology_api_edges_5m", ["bucket_start", "caller_service", "caller_api", "target_service", "target_api", "request_count", "error_count", "http_4xx_count", "http_5xx_count", "timeout_count", "tcp_reset_count", "incomplete_count", "latency_sum", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "request_bytes", "response_bytes", "unique_principals", "unique_source_ips", "anonymous_requests", "first_seen_ms", "last_seen_ms", "evidence_type", "evidence_detail", "confidence", "updated_at_ms"], [self._api_row(row) for row in api_rows]),
            ("topology_principal_edges_5m", ["bucket_start", "principal", "caller_service", "caller_api", "target_service", "target_api", "request_count", "error_count", "http_4xx_count", "http_5xx_count", "timeout_count", "tcp_reset_count", "incomplete_count", "latency_sum", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "request_bytes", "response_bytes", "unique_principals", "unique_source_ips", "anonymous_requests", "first_seen_ms", "last_seen_ms", "evidence_type", "evidence_detail", "confidence", "updated_at_ms"], [self._principal_row(row) for row in principal_rows]),
            ("topology_principal_ip_5m", ["bucket_start", "principal", "source_ip", "service", "api", "caller_service", "request_count", "error_count", "http_4xx_count", "http_5xx_count", "timeout_count", "p95_latency_ms", "request_bytes", "response_bytes", "first_seen_ms", "last_seen_ms", "is_load_balancer", "source_ip_role", "role_label", "attribution_confidence", "is_new_ip", "updated_at_ms"], [self._ip_row(row, start_ms, prior_ips) for row in ip_rows]),
            ("topology_service_current", ["bucket_start", "caller_service", "target_service", "request_count", "error_count", "http_4xx_count", "http_5xx_count", "timeout_count", "tcp_reset_count", "incomplete_count", "latency_sum", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "request_bytes", "response_bytes", "unique_principals", "unique_source_ips", "anonymous_requests", "first_seen_ms", "last_seen_ms", "evidence_type", "evidence_detail", "confidence", "updated_at_ms"], [self._service_row(row) for row in service_rows]),
            ("topology_api_current", ["bucket_start", "caller_service", "caller_api", "target_service", "target_api", "request_count", "error_count", "http_4xx_count", "http_5xx_count", "timeout_count", "tcp_reset_count", "incomplete_count", "latency_sum", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "request_bytes", "response_bytes", "unique_principals", "unique_source_ips", "anonymous_requests", "first_seen_ms", "last_seen_ms", "evidence_type", "evidence_detail", "confidence", "updated_at_ms"], [self._api_row(row) for row in api_rows]),
            ("topology_principal_current", ["bucket_start", "principal", "caller_service", "caller_api", "target_service", "target_api", "request_count", "error_count", "http_4xx_count", "http_5xx_count", "timeout_count", "tcp_reset_count", "incomplete_count", "latency_sum", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "request_bytes", "response_bytes", "unique_principals", "unique_source_ips", "anonymous_requests", "first_seen_ms", "last_seen_ms", "evidence_type", "evidence_detail", "confidence", "updated_at_ms"], [self._principal_row(row) for row in principal_rows]),
            ("topology_principal_ip_current", ["bucket_start", "principal", "source_ip", "service", "api", "caller_service", "request_count", "error_count", "http_4xx_count", "http_5xx_count", "timeout_count", "p95_latency_ms", "request_bytes", "response_bytes", "first_seen_ms", "last_seen_ms", "is_load_balancer", "source_ip_role", "role_label", "attribution_confidence", "is_new_ip", "updated_at_ms"], [self._ip_row(row, start_ms, prior_ips) for row in ip_rows]),
        ]

    @staticmethod
    def _collapse_rows(rows: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
        result: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for row in rows:
            key = tuple(row.get(k) for k in keys)
            existing = result.get(key)
            if existing is None:
                existing = dict(row)
                existing["latency_quantiles"] = list(row.get("latency_quantiles") or (0.0, 0.0, 0.0))
                result[key] = existing
                continue
            for field in ("request_count", "error_count", "http_4xx_count", "http_5xx_count", "timeout_count", "tcp_reset_count", "incomplete_count", "latency_sum", "request_bytes", "response_bytes", "anonymous_requests"):
                existing[field] = _safe_float(existing.get(field)) + _safe_float(row.get(field))
            existing["unique_principals"] = max(_safe_int(existing.get("unique_principals")), _safe_int(row.get("unique_principals")))
            existing["unique_source_ips"] = max(_safe_int(existing.get("unique_source_ips")), _safe_int(row.get("unique_source_ips")))
            existing["first_seen_ms"] = min(_safe_int(existing.get("first_seen_ms")), _safe_int(row.get("first_seen_ms")))
            existing["last_seen_ms"] = max(_safe_int(existing.get("last_seen_ms")), _safe_int(row.get("last_seen_ms")))
            old_q = existing["latency_quantiles"]
            new_q = row.get("latency_quantiles") or (0.0, 0.0, 0.0)
            existing["latency_quantiles"] = [max(_safe_float(old_q[i]), _safe_float(new_q[i])) for i in range(3)]
        return list(result.values())

    @staticmethod
    def _service_row(row: Dict[str, Any]) -> List[Any]:
        q = row.get("latency_quantiles") or (0.0, 0.0, 0.0)
        caller = str(row.get("caller_service") or "").strip()[:200]
        target = canonical_service(row.get("target_service"))
        return [_safe_int(row.get("bucket_start")), caller, target, _safe_int(row.get("request_count")), _safe_int(row.get("error_count")), _safe_int(row.get("http_4xx_count")), _safe_int(row.get("http_5xx_count")), _safe_int(row.get("timeout_count")), _safe_int(row.get("tcp_reset_count")), _safe_int(row.get("incomplete_count")), _safe_float(row.get("latency_sum")), _safe_float(q[0]), _safe_float(q[1]), _safe_float(q[2]), _safe_int(row.get("request_bytes")), _safe_int(row.get("response_bytes")), _safe_int(row.get("unique_principals")), _safe_int(row.get("unique_source_ips")), _safe_int(row.get("anonymous_requests")), _safe_int(row.get("first_seen_ms")), _safe_int(row.get("last_seen_ms")), str(row.get("evidence_type") or "IP_SERVICE_INFERRED"), str(row.get("evidence_detail") or ""), _safe_float(row.get("confidence"))]

    @staticmethod
    def _api_row(row: Dict[str, Any]) -> List[Any]:
        service_row = InteractiveTopologyRepository._service_row(row)
        return service_row[:2] + ["", service_row[2], canonical_api(row.get("raw_api"), row.get("target_service"))] + service_row[3:]

    @staticmethod
    def _principal_row(row: Dict[str, Any]) -> List[Any]:
        q = row.get("latency_quantiles") or (0.0, 0.0, 0.0)
        return [_safe_int(row.get("bucket_start")), canonical_principal(row.get("principal")), str(row.get("caller_service") or "").strip()[:200], "", canonical_service(row.get("target_service")), canonical_api(row.get("raw_api"), row.get("target_service")), _safe_int(row.get("request_count")), _safe_int(row.get("error_count")), _safe_int(row.get("http_4xx_count")), _safe_int(row.get("http_5xx_count")), _safe_int(row.get("timeout_count")), _safe_int(row.get("tcp_reset_count")), _safe_int(row.get("incomplete_count")), _safe_float(row.get("latency_sum")), _safe_float(q[0]), _safe_float(q[1]), _safe_float(q[2]), _safe_int(row.get("request_bytes")), _safe_int(row.get("response_bytes")), 1, _safe_int(row.get("unique_source_ips")), _safe_int(row.get("anonymous_requests")), _safe_int(row.get("first_seen_ms")), _safe_int(row.get("last_seen_ms")), str(row.get("evidence_type") or "IP_SERVICE_INFERRED"), str(row.get("evidence_detail") or ""), _safe_float(row.get("confidence"))]

    def _ip_row(self, row: Dict[str, Any], start_ms: int, prior_ips: set[Tuple[str, str]]) -> List[Any]:
        ip = str(row.get("source_ip") or "unknown")
        principal = canonical_principal(row.get("principal"))
        role, label, confidence = classify_source_ip_role(ip)
        return [_safe_int(row.get("bucket_start")), principal, ip[:100], canonical_service(row.get("target_service")), canonical_api(row.get("raw_api"), row.get("target_service")), str(row.get("caller_service") or "").strip()[:200], _safe_int(row.get("request_count")), _safe_int(row.get("error_count")), _safe_int(row.get("http_4xx_count")), _safe_int(row.get("http_5xx_count")), _safe_int(row.get("timeout_count")), _safe_float((row.get("latency_quantiles") or (0.0, 0.0, 0.0))[1]), _safe_int(row.get("request_bytes")), _safe_int(row.get("response_bytes")), _safe_int(row.get("first_seen_ms")), _safe_int(row.get("last_seen_ms")), 1 if role in ("load_balancer", "reverse_proxy", "nat_gateway") else 0, role, label, confidence, 0 if (principal, ip) in prior_ips else 1]

    # ------------------------------------------------------------------
    # ClickHouse query helpers and response shaping
    # ------------------------------------------------------------------
    def _query_records(self, table: str, dimensions: Sequence[str], start_ms: int, end_ms: int, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        filters = filters or {}
        clauses = ["bucket_start >= ?", "bucket_start < ?"]
        args: List[Any] = [start_ms // 1000, (end_ms + 999) // 1000]
        for field in ("caller_service", "target_service", "target_api", "principal", "source_ip", "service", "api"):
            if filters.get(field) is not None:
                clauses.append(f"{field} = ?")
                args.append(filters[field])
        if filters.get("principal") in ANONYMOUS:
            clauses.append("principal IN ('unknown', '-anonymous-', '')")
        where = " AND ".join(clauses)
        group = ", ".join(dimensions)
        selected = f"{group}," if group else ""
        sql = f"""
            SELECT {selected}
              sum(request_count) request_count, sum(error_count) error_count,
              sum(http_4xx_count) http_4xx_count, sum(http_5xx_count) http_5xx_count,
              sum(timeout_count) timeout_count, sum(tcp_reset_count) tcp_reset_count,
              sum(incomplete_count) incomplete_count, sum(latency_sum) latency_sum,
              max(p50_latency_ms) p50_latency_ms, max(p95_latency_ms) p95_latency_ms,
              max(p99_latency_ms) p99_latency_ms, sum(request_bytes) request_bytes,
              sum(response_bytes) response_bytes, sum(unique_principals) unique_principals,
              sum(unique_source_ips) unique_source_ips, sum(anonymous_requests) anonymous_requests,
              min(first_seen_ms) first_seen_ms, max(last_seen_ms) last_seen_ms,
              groupUniqArray(evidence_type) evidence_types, max(confidence) confidence
            FROM {table} FINAL WHERE {where}
            {f'GROUP BY {group}' if group else ''}
            ORDER BY request_count DESC
        """
        with get_connection(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, args)]

    def _metrics(self, row: Optional[Dict[str, Any]], duration_seconds: int) -> Dict[str, Any]:
        row = row or {}
        requests = _safe_int(row.get("request_count"))
        errors = _safe_int(row.get("error_count"))
        four = _safe_int(row.get("http_4xx_count"))
        five = _safe_int(row.get("http_5xx_count"))
        req_bytes = _safe_int(row.get("request_bytes"))
        resp_bytes = _safe_int(row.get("response_bytes"))
        evidence_types = sorted({str(x) for x in (row.get("evidence_types") or []) if x})
        direct = any(x in EVIDENCE_DIRECT for x in evidence_types)
        return {
            "tps": round(requests / max(1, duration_seconds), 3),
            "request_count": requests,
            "p50_latency_ms": round(_safe_float(row.get("p50_latency_ms")), 2),
            "p95_latency_ms": round(_safe_float(row.get("p95_latency_ms")), 2),
            "p99_latency_ms": round(_safe_float(row.get("p99_latency_ms")), 2),
            "error_rate": round(errors / max(1, requests), 4),
            "http_4xx_rate": round(four / max(1, requests), 4),
            "http_5xx_rate": round(five / max(1, requests), 4),
            "timeout_count": _safe_int(row.get("timeout_count")),
            "tcp_reset_count": _safe_int(row.get("tcp_reset_count")),
            "incomplete_count": _safe_int(row.get("incomplete_count")),
            "request_bytes": req_bytes,
            "response_bytes": resp_bytes,
            "average_request_bytes": round(req_bytes / max(1, requests), 2),
            "average_response_bytes": round(resp_bytes / max(1, requests), 2),
            "unique_principals": _safe_int(row.get("unique_principals")),
            "unique_source_ips": _safe_int(row.get("unique_source_ips")),
            "anonymous_requests": _safe_int(row.get("anonymous_requests")),
            "first_seen_ms": _safe_int(row.get("first_seen_ms")) or None,
            "last_seen_ms": _safe_int(row.get("last_seen_ms")) or None,
            "evidence_type": "direct" if direct else "inferred",
            "evidence_types": evidence_types,
            "confidence": round(_safe_float(row.get("confidence")), 3),
        }

    @staticmethod
    def _delta(current: Dict[str, Any], previous: Optional[Dict[str, Any]], available: bool) -> Dict[str, Any]:
        if not available:
            return {"status": "baseline_unavailable", "baseline": "insufficient_history"}
        previous = previous or {}
        def change(key: str) -> float:
            old = _safe_float(previous.get(key))
            new = _safe_float(current.get(key))
            return round((new - old) / old * 100.0, 2) if old else (100.0 if new else 0.0)
        old_error = _safe_float(previous.get("error_rate"))
        new_error = _safe_float(current.get("error_rate"))
        status = "unchanged"
        if not previous.get("request_count"):
            status = "new"
        elif not current.get("request_count"):
            status = "disappeared"
        elif abs(change("tps")) >= 20 or abs(change("p95_latency_ms")) >= 20 or abs(new_error - old_error) >= 0.05 or abs(change("request_bytes")) >= 20 or abs(change("anonymous_requests")) >= 20:
            status = "changed"
        return {
            "status": status,
            "baseline": "previous_window",
            "tps_change_pct": change("tps"),
            "latency_change_pct": change("p95_latency_ms"),
            "error_rate_delta": round(new_error - old_error, 4),
            "bandwidth_change_pct": change("request_bytes"),
            "anonymous_change_pct": change("anonymous_requests"),
        }

    def _records_with_changes(self, table: str, dimensions: Sequence[str], filters: Optional[Dict[str, Any]], window: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
        current_rows = self._query_records(table, dimensions, window["start_ms"], window["end_ms"], filters)
        duration = window["end_ms"] - window["start_ms"]
        previous_rows = self._query_records(table, dimensions, window["start_ms"] - duration, window["start_ms"], filters)
        previous_available = bool(previous_rows) or self._has_history_before(table, window["start_ms"])
        key = lambda row: tuple(str(row.get(d, "")) for d in dimensions)
        previous_by_key = {key(row): self._metrics(row, window["duration_seconds"]) for row in previous_rows}
        result = []
        for row in current_rows:
            metrics = self._metrics(row, window["duration_seconds"])
            metrics["change"] = self._delta(metrics, previous_by_key.get(key(row)), previous_available)
            result.append({"dimensions": {d: row.get(d) for d in dimensions}, "metrics": metrics})
        disappeared = []
        current_keys = {key(row) for row in current_rows}
        for row in previous_rows:
            if key(row) not in current_keys:
                metrics = self._metrics(row, window["duration_seconds"])
                metrics["change"] = self._delta({}, metrics, previous_available)
                disappeared.append({"dimensions": {d: row.get(d) for d in dimensions}, "metrics": metrics})
        return result, disappeared, previous_available

    def _has_history_before(self, table: str, before_ms: int) -> bool:
        if self.backend == "elasticsearch":
            return False
        with get_connection(self.db_path) as db:
            row = db.execute(f"SELECT 1 FROM {table} WHERE bucket_start < ? LIMIT 1", (before_ms // 1000,)).fetchone()
        return bool(row)

    def _anonymous_summary(self, window: Dict[str, Any]) -> Dict[str, Any]:
        total_rows = self._query_records("topology_api_edges_5m", [], window["start_ms"], window["end_ms"])
        anon_rows = self._query_records("topology_principal_edges_5m", ["target_service", "target_api"], window["start_ms"], window["end_ms"], {"principal": "-anonymous-"})
        total = _safe_int(total_rows[0].get("request_count")) if total_rows else 0
        anonymous = sum(_safe_int(row.get("request_count")) for row in anon_rows)
        by_service: Dict[str, int] = {}
        by_api: Dict[str, int] = {}
        for row in anon_rows:
            service = canonical_service(row.get("target_service"))
            api = canonical_api(row.get("target_api"), service)
            by_service[service] = by_service.get(service, 0) + _safe_int(row.get("request_count"))
            by_api[api] = by_api.get(api, 0) + _safe_int(row.get("request_count"))
        return {
            "total_requests": total,
            "identified_requests": max(0, total - anonymous),
            "anonymous_requests": anonymous,
            "identified_request_percentage": round(max(0, total - anonymous) / max(1, total) * 100, 2),
            "anonymous_request_percentage": round(anonymous / max(1, total) * 100, 2),
            "anonymous_tps": round(anonymous / max(1, window["duration_seconds"]), 3),
            "top_services": [{"name": k, "requests": v} for k, v in sorted(by_service.items(), key=lambda x: (-x[1], x[0]))[:10]],
            "top_apis": [{"name": k, "requests": v} for k, v in sorted(by_api.items(), key=lambda x: (-x[1], x[0]))[:10]],
        }

    def service_graph(self, window: Dict[str, Any]) -> Dict[str, Any]:
        if self.backend == "elasticsearch":
            return self._es_graph(window)
        records, disappeared, history = self._records_with_changes("topology_service_edges_5m", ["caller_service", "target_service"], None, window)
        node_rows = self._query_records("topology_api_edges_5m", ["target_service"], window["start_ms"], window["end_ms"])
        nodes_by_name: Dict[str, Dict[str, Any]] = {}
        for row in node_rows:
            name = canonical_service(row.get("target_service"))
            nodes_by_name[name] = {"id": f"service:{name}", "name": name, "type": "service", "service": name, "metrics": self._metrics(row, window["duration_seconds"])}
        edges = []
        for record in records:
            c = canonical_service(record["dimensions"].get("caller_service"))
            t = canonical_service(record["dimensions"].get("target_service"))
            if c not in nodes_by_name:
                nodes_by_name[c] = {"id": f"service:{c}", "name": c, "type": "service", "service": c, "metrics": record["metrics"]}
            edges.append({"id": f"service-edge:{c}->{t}", "source": f"service:{c}", "target": f"service:{t}", "source_name": c, "target_name": t, "metrics": record["metrics"], "evidence_type": record["metrics"]["evidence_type"], "direct": record["metrics"]["evidence_type"] == "direct", "inferred": record["metrics"]["evidence_type"] == "inferred"})
        return {"window": window, "nodes": sorted(nodes_by_name.values(), key=lambda x: x["name"]), "edges": edges, "changes": {"new_edges": [x for x in edges if x["metrics"]["change"].get("status") == "new"], "disappeared_edges": disappeared, "baseline": "previous_window" if history else "insufficient_history"}, "anonymous": self._anonymous_summary(window), "backend": self.backend}

    def search_entities(self, query: str, window: Dict[str, Any], limit: int = 20) -> Dict[str, Any]:
        """Search service, API, and principal nodes with enough ancestry to reveal them."""
        needle = re.sub(r"\s+", " ", query.strip()).casefold()
        if len(needle) < 2:
            return {"query": query, "items": [], "window": window, "backend": self.backend}

        if self.backend == "elasticsearch":
            target_services = self._es_rows(["target_service"], window)
            caller_services = self._es_rows(["caller_service"], window)
            api_rows = self._es_rows(["target_service", "target_api"], window)
            principal_rows = self._es_rows(["principal", "target_service", "target_api"], window)
        else:
            target_services = self._query_records("topology_api_edges_5m", ["target_service"], window["start_ms"], window["end_ms"])
            caller_services = self._query_records("topology_service_edges_5m", ["caller_service"], window["start_ms"], window["end_ms"])
            api_rows = self._query_records("topology_api_edges_5m", ["target_service", "target_api"], window["start_ms"], window["end_ms"])
            principal_rows = self._query_records("topology_principal_edges_5m", ["principal", "target_service", "target_api"], window["start_ms"], window["end_ms"])

        candidates: Dict[str, Dict[str, Any]] = {}

        def add(node: Dict[str, Any]) -> None:
            searchable = " ".join(str(node.get(key) or "") for key in ("name", "service", "api", "principal")).casefold()
            if needle not in searchable:
                return
            existing = candidates.get(node["id"])
            if existing is None or node["metrics"]["request_count"] > existing["metrics"]["request_count"]:
                candidates[node["id"]] = node

        for row, dimension in [(row, "target_service") for row in target_services] + [(row, "caller_service") for row in caller_services]:
            service = canonical_service(row.get(dimension))
            add({"id": f"service:{service}", "name": service, "type": "service", "service": service, "metrics": self._metrics(row, window["duration_seconds"])})
        for row in api_rows:
            service = canonical_service(row.get("target_service"))
            api = canonical_api(row.get("target_api"), service)
            add({"id": f"api:{service}:{api}", "name": api, "type": "api", "service": service, "api": api, "metrics": self._metrics(row, window["duration_seconds"])})
        for row in principal_rows:
            service = canonical_service(row.get("target_service"))
            api = canonical_api(row.get("target_api"), service)
            principal = canonical_principal(row.get("principal"))
            add({"id": f"principal:{principal}", "name": principal, "type": "principal", "principal": principal, "service": service, "api": api, "metrics": self._metrics(row, window["duration_seconds"])})

        type_order = {"service": 0, "api": 1, "principal": 2}
        items = sorted(candidates.values(), key=lambda node: (
            0 if node["name"].casefold() == needle else 1 if node["name"].casefold().startswith(needle) else 2,
            type_order.get(node["type"], 9),
            -node["metrics"]["request_count"],
            node["name"].casefold(),
        ))[:max(1, min(limit, 50))]
        return {"query": query, "items": items, "window": window, "backend": self.backend}

    def service_apis(self, service: str, window: Dict[str, Any]) -> Dict[str, Any]:
        service = canonical_service(service)
        if self.backend == "elasticsearch":
            return self._es_expansion("api", service, "", window)
        records, disappeared, history = self._records_with_changes("topology_api_edges_5m", ["target_api"], {"target_service": service}, window)
        nodes = [{"id": f"api:{service}:{record['dimensions'].get('target_api')}", "name": record["dimensions"].get("target_api") or "unknown", "type": "api", "service": service, "api": record["dimensions"].get("target_api"), "metrics": record["metrics"]} for record in records]
        return {"window": window, "parent": {"id": f"service:{service}", "name": service, "type": "service"}, "nodes": sorted(nodes, key=lambda x: (-x["metrics"]["request_count"], x["name"])), "edges": [], "changes": {"new_nodes": [n for n in nodes if n["metrics"]["change"].get("status") == "new"], "disappeared_nodes": disappeared, "baseline": "previous_window" if history else "insufficient_history"}, "anonymous": self._anonymous_summary(window), "backend": self.backend}

    def api_connections(self, service: str, api: str, window: Dict[str, Any]) -> Dict[str, Any]:
        """Return only observed caller-service connections for one selected API."""
        service, api = canonical_service(service), canonical_api(api, service)
        filters = {"target_service": service, "target_api": api}
        if self.backend == "elasticsearch":
            rows = self._es_rows(["caller_service", "target_service"], window, filters)
            records = [{
                "dimensions": {"caller_service": row.get("caller_service"), "target_service": row.get("target_service")},
                "metrics": self._metrics(row, window["duration_seconds"]),
            } for row in rows]
            disappeared: List[Dict[str, Any]] = []
            history = False
        else:
            records, disappeared, history = self._records_with_changes(
                "topology_api_edges_5m",
                ["caller_service", "target_service"],
                filters,
                window,
            )

        nodes_by_name: Dict[str, Dict[str, Any]] = {}
        edges = []
        for record in records:
            caller = canonical_service(record["dimensions"].get("caller_service"))
            metrics = record["metrics"]
            nodes_by_name.setdefault(caller, {
                "id": f"service:{caller}",
                "name": caller,
                "type": "service",
                "service": caller,
                "metrics": metrics,
            })
            edges.append({
                "id": f"api-service-edge:{caller}->{service}:{api}",
                "source": f"service:{caller}",
                "target": f"api:{service}:{api}",
                "source_name": caller,
                "target_name": api,
                "metrics": metrics,
                "evidence_type": metrics["evidence_type"],
                "direct": metrics["evidence_type"] == "direct",
                "inferred": metrics["evidence_type"] == "inferred",
            })
        return {
            "window": window,
            "nodes": sorted(nodes_by_name.values(), key=lambda node: node["name"]),
            "edges": edges,
            "changes": {
                "new_edges": [edge for edge in edges if edge["metrics"]["change"].get("status") == "new"],
                "disappeared_edges": disappeared,
                "baseline": "previous_window" if history else "insufficient_history",
            },
            "anonymous": self._anonymous_summary(window) if self.backend != "elasticsearch" else {},
            "backend": self.backend,
        }

    def api_principals(self, service: str, api: str, window: Dict[str, Any]) -> Dict[str, Any]:
        service, api = canonical_service(service), canonical_api(api, service)
        if self.backend == "elasticsearch":
            return self._es_expansion("principal", service, api, window)
        records, disappeared, history = self._records_with_changes("topology_principal_edges_5m", ["principal"], {"target_service": service, "target_api": api}, window)
        nodes = [{"id": f"principal:{record['dimensions'].get('principal')}", "name": record["dimensions"].get("principal") or "-anonymous-", "type": "principal", "principal": record["dimensions"].get("principal"), "service": service, "api": api, "metrics": record["metrics"]} for record in records]
        return {"window": window, "parent": {"id": f"api:{service}:{api}", "name": api, "type": "api", "service": service, "api": api}, "nodes": sorted(nodes, key=lambda x: (-x["metrics"]["request_count"], x["name"])), "edges": [], "changes": {"new_nodes": [n for n in nodes if n["metrics"]["change"].get("status") == "new"], "disappeared_nodes": disappeared, "baseline": "previous_window" if history else "insufficient_history"}, "anonymous": self._anonymous_summary(window), "backend": self.backend}

    def service_metrics(self, service: str, window: Dict[str, Any]) -> Dict[str, Any]:
        service = canonical_service(service)
        if self.backend == "elasticsearch":
            return self._es_detail("service", service, "", window)
        rows = self._query_records("topology_api_edges_5m", ["target_service"], window["start_ms"], window["end_ms"], {"target_service": service})
        previous = self._query_records("topology_api_edges_5m", ["target_service"], window["start_ms"] - (window["end_ms"] - window["start_ms"]), window["start_ms"], {"target_service": service})
        metrics = self._metrics(rows[0] if rows else None, window["duration_seconds"])
        metrics["change"] = self._delta(metrics, self._metrics(previous[0], window["duration_seconds"]) if previous else None, bool(previous) or self._has_history_before("topology_api_edges_5m", window["start_ms"]))
        callers = self._query_records("topology_service_edges_5m", ["caller_service"], window["start_ms"], window["end_ms"], {"target_service": service})
        targets = self._query_records("topology_service_edges_5m", ["target_service"], window["start_ms"], window["end_ms"], {"caller_service": service})
        apis = self._query_records("topology_api_edges_5m", ["target_api"], window["start_ms"], window["end_ms"], {"target_service": service})
        entity = {"id": f"service:{service}", "name": service, "type": "service", "service": service, "groups": {"traffic": {"tps": metrics["tps"], "request_count": metrics["request_count"], "request_bytes": metrics["request_bytes"], "response_bytes": metrics["response_bytes"], "average_request_bytes": metrics["average_request_bytes"], "average_response_bytes": metrics["average_response_bytes"]}, "performance": {k: metrics[k] for k in ("p50_latency_ms", "p95_latency_ms", "p99_latency_ms")}, "reliability": {k: metrics[k] for k in ("error_rate", "http_4xx_rate", "http_5xx_rate", "timeout_count", "tcp_reset_count", "incomplete_count")}, "dependencies": {"caller_service_count": len(callers), "target_service_count": len(targets), "api_count": len(apis), "active_principal_count": metrics["unique_principals"]}, "change": metrics["change"]}}
        return {"entity": entity, "metrics": metrics, "series": self._series("topology_api_edges_5m", {"target_service": service}, window), "changes": {"baseline": metrics["change"].get("baseline")}, "anonymous": self._anonymous_summary(window), "backend": self.backend}

    def api_metrics(self, api: str, window: Dict[str, Any], service: Optional[str] = None) -> Dict[str, Any]:
        api = canonical_api(api, service or "")
        filters = {"target_api": api}
        if service:
            filters["target_service"] = canonical_service(service)
        if self.backend == "elasticsearch":
            return self._es_detail("api", service or "", api, window)
        rows = self._query_records("topology_principal_edges_5m", ["target_service", "target_api"], window["start_ms"], window["end_ms"], filters)
        metrics = self._metrics(rows[0] if rows else None, window["duration_seconds"])
        entity = {"id": f"api:{service or '*'}:{api}", "name": api, "type": "api", "service": service, "api": api, "groups": {"traffic": {k: metrics[k] for k in ("tps", "request_count", "request_bytes", "response_bytes", "average_request_bytes", "average_response_bytes")}, "performance": {k: metrics[k] for k in ("p50_latency_ms", "p95_latency_ms", "p99_latency_ms")}, "reliability": {k: metrics[k] for k in ("error_rate", "http_4xx_rate", "http_5xx_rate", "timeout_count")}, "relationships": {"unique_principals": metrics["unique_principals"], "unique_source_ips": metrics["unique_source_ips"]}}}
        return {"entity": entity, "metrics": metrics, "series": self._series("topology_principal_edges_5m", filters, window), "changes": {"baseline": "previous_window"}, "anonymous": self._anonymous_summary(window), "backend": self.backend}

    def principal_metrics(self, principal: str, window: Dict[str, Any]) -> Dict[str, Any]:
        principal = canonical_principal(principal)
        if self.backend == "elasticsearch":
            return self._es_detail("principal", principal, "", window)
        rows = self._query_records("topology_principal_edges_5m", ["principal"], window["start_ms"], window["end_ms"], {"principal": principal})
        metrics = self._metrics(rows[0] if rows else None, window["duration_seconds"])
        services = self._query_records("topology_principal_edges_5m", ["target_service"], window["start_ms"], window["end_ms"], {"principal": principal})
        apis = self._query_records("topology_principal_edges_5m", ["target_api"], window["start_ms"], window["end_ms"], {"principal": principal})
        entity = {"id": f"principal:{principal}", "name": principal, "type": "principal", "principal": principal, "groups": {"overview": {k: metrics[k] for k in ("tps", "request_count", "p95_latency_ms", "p99_latency_ms", "error_rate", "request_bytes", "response_bytes", "unique_source_ips", "first_seen_ms", "last_seen_ms")}, "paths": {"services_used": len(services), "apis_used": len(apis)}}}
        return {"entity": entity, "metrics": metrics, "series": self._series("topology_principal_edges_5m", {"principal": principal}, window), "changes": {"baseline": "previous_window"}, "anonymous": self._anonymous_summary(window), "backend": self.backend}

    def _series(self, table: str, filters: Dict[str, Any], window: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self.backend == "elasticsearch":
            return []
        clauses = ["bucket_start >= ?", "bucket_start < ?"]
        args: List[Any] = [window["start_ms"] // 1000, window["end_ms"] // 1000]
        for key, value in filters.items():
            clauses.append(f"{key} = ?")
            args.append(value)
        with get_connection(self.db_path) as db:
            rows = db.execute(f"SELECT bucket_start, sum(request_count) request_count, max(p95_latency_ms) p95_latency_ms, sum(error_count) error_count, sum(request_bytes) request_bytes, sum(response_bytes) response_bytes FROM {table} FINAL WHERE {' AND '.join(clauses)} GROUP BY bucket_start ORDER BY bucket_start", args).fetchall()
        return [{"bucket_start": _safe_int(row["bucket_start"]), "timestamp_ms": _safe_int(row["bucket_start"]) * 1000, "tps": round(_safe_int(row["request_count"]) / 300.0, 3), "request_count": _safe_int(row["request_count"]), "p95_latency_ms": _safe_float(row["p95_latency_ms"]), "error_rate": round(_safe_int(row["error_count"]) / max(1, _safe_int(row["request_count"])), 4), "request_bytes": _safe_int(row["request_bytes"]), "response_bytes": _safe_int(row["response_bytes"])} for row in rows]

    def principal_ips(self, principal: str, window: Dict[str, Any], page_size: int, cursor: Optional[str], service: Optional[str] = None, api: Optional[str] = None, filter_name: str = "all") -> Dict[str, Any]:
        principal = canonical_principal(principal)
        decoded = decode_cursor(cursor)
        if self.backend == "elasticsearch":
            return self._es_ips(principal, window, page_size, decoded, service, api, filter_name)
        clauses = ["bucket_start >= ?", "bucket_start < ?", "principal = ?"]
        args: List[Any] = [window["start_ms"] // 1000, window["end_ms"] // 1000, principal]
        if service:
            clauses.append("service = ?")
            args.append(canonical_service(service))
        if api:
            clauses.append("api = ?")
            args.append(canonical_api(api, service or ""))
        if decoded:
            clauses.append("(source_ip > ? OR (source_ip = ? AND service > ?) OR (source_ip = ? AND service = ? AND api > ?) OR (source_ip = ? AND service = ? AND api = ? AND caller_service > ?))")
            args.extend([decoded[0], decoded[0], decoded[1], decoded[0], decoded[1], decoded[2], decoded[0], decoded[1], decoded[2], decoded[3]])
        having = ""
        if filter_name == "lb":
            having = " HAVING max(is_load_balancer) = 1"
        elif filter_name == "direct":
            having = " HAVING max(is_load_balancer) = 0"
        elif filter_name == "new_ip":
            having = " HAVING max(is_new_ip) = 1"
        elif filter_name == "high_error":
            having = " HAVING sum(error_count) / greatest(1, sum(request_count)) >= 0.1"
        elif filter_name == "inactive":
            having = " HAVING max(last_seen_ms) < ?"
            args.append(window["end_ms"] - max(300000, (window["end_ms"] - window["start_ms"])))
        elif filter_name != "all":
            raise ValueError("filter must be one of all, direct, lb, new_ip, high_error, inactive")
        sql = f"""
            SELECT source_ip, service, api, caller_service,
              sum(request_count) request_count, sum(error_count) error_count,
              max(p95_latency_ms) p95_latency_ms, sum(request_bytes) request_bytes,
              sum(response_bytes) response_bytes, min(first_seen_ms) first_seen_ms,
              max(last_seen_ms) last_seen_ms, max(is_load_balancer) is_load_balancer,
              any(source_ip_role) source_ip_role, any(role_label) role_label,
              any(attribution_confidence) attribution_confidence, max(is_new_ip) is_new_ip
            FROM topology_principal_ip_5m FINAL WHERE {' AND '.join(clauses)}
            GROUP BY source_ip, service, api, caller_service
            {having}
            ORDER BY source_ip, service, api, caller_service
            LIMIT ?
        """
        args.append(page_size + 1)
        with get_connection(self.db_path) as db:
            rows = [dict(row) for row in db.execute(sql, args)]
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        next_cursor = None
        if has_more and rows:
            row = rows[-1]
            next_cursor = encode_cursor([str(row.get("source_ip") or ""), str(row.get("service") or ""), str(row.get("api") or ""), str(row.get("caller_service") or "")])
        items = []
        for row in rows:
            requests = _safe_int(row.get("request_count"))
            items.append({**row, "request_count": requests, "tps": round(requests / max(1, window["duration_seconds"]), 3), "error_rate": round(_safe_int(row.get("error_count")) / max(1, requests), 4), "is_load_balancer": bool(row.get("is_load_balancer")), "is_new_ip": bool(row.get("is_new_ip"))})
        return {"principal": principal, "items": items, "next_cursor": next_cursor, "page_size": page_size, "window": window, "filters": {"service": service, "api": api, "filter": filter_name}, "backend": self.backend}

    # ------------------------------------------------------------------
    # Elasticsearch server-side aggregation path
    # ------------------------------------------------------------------
    def _es_bounds_ms(self) -> Tuple[Optional[int], Optional[int]]:
        if not self._es_repo.url:
            return None, None
        body = {"size": 0, "aggs": {"bounds": {"stats": {"field": "@timestamp"}}}}
        result = self._es_request(body)
        bounds = ((result or {}).get("aggregations") or {}).get("bounds") or {}
        return _safe_int(bounds.get("min")), _safe_int(bounds.get("max"))

    def _es_request(self, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._es_repo.url:
            return None
        try:
            with httpx.Client(base_url=self._es_repo.url, verify=self._es_repo.verify_tls, timeout=self._es_repo.timeout, headers=self._es_repo._get_headers(), auth=self._es_repo._get_auth()) as client:
                response = client.post(f"/{self._es_repo.index}/_search", json=body)
                if response.status_code != 200:
                    log.warning("Elasticsearch topology aggregation returned HTTP %d", response.status_code)
                    return None
                return response.json()
        except Exception as exc:
            log.warning("Elasticsearch topology aggregation failed: %s", exc)
            return None

    @staticmethod
    def _es_runtime() -> Dict[str, Any]:
        return {
            "topology.caller": {"type": "keyword", "script": {"source": "def v=params['_source']['caller_service']; if (v == null) { v=params['_source']['peer.service']; } if (v != null) emit(v.toString());"}},
            "topology.target": {"type": "keyword", "script": {"source": "def v=params['_source']['target_service']; if (v == null) { def s=params['_source']['service']; if (s instanceof Map) { v=s['name']; } } if (v != null) emit(v.toString());"}},
            "topology.api": {"type": "keyword", "script": {"source": "def v=params['_source']['operation_key']; if (v == null) { def t=params['_source']['transaction']; if (t instanceof Map) { v=t['name']; } } if (v == null) { v=params['_source']['name']; } if (v != null) emit(v.toString());"}},
            "topology.principal": {"type": "keyword", "script": {"source": "def v=params['_source']['principal_name']; if (v == null) { def u=params['_source']['enduser']; if (u instanceof Map) { v=u['id']; } } if (v == null) { def u=params['_source']['user']; if (u instanceof Map) { v=u['name']; } } if (v == null) { emit('-anonymous-'); } else { emit(v.toString()); }"}},
            "topology.duration_ms": {"type": "double", "script": {"source": "def v=params['_source']['duration_ms']; if (v == null) { def t=params['_source']['transaction']; if (t instanceof Map && t['duration'] instanceof Map) { v=t['duration']['us']; if (v != null) v=Double.parseDouble(v.toString())/1000.0; } } if (v != null) emit(Double.parseDouble(v.toString()));"}},
        }

    def _es_base_query(self, window: Dict[str, Any], filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        clauses: List[Dict[str, Any]] = [{"range": {"@timestamp": {"gte": window["start_ms"], "lt": window["end_ms"]}}}]
        filters = filters or {}
        mapping = {"target_service": "topology.target", "target_api": "topology.api", "principal": "topology.principal"}
        for key, field in mapping.items():
            if filters.get(key):
                value = filters[key]
                if key == "principal" and value in ANONYMOUS:
                    value = "-anonymous-"
                clauses.append({"term": {field: value}})
        return {"bool": {"filter": clauses}}

    def _es_rows(self, dimensions: Sequence[str], window: Dict[str, Any], filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        fields = {"caller_service": "topology.caller", "target_service": "topology.target", "target_api": "topology.api", "principal": "topology.principal"}
        sources = [{dimension: {"terms": {"field": fields[dimension]}}} for dimension in dimensions]
        body = {"size": 0, "runtime_mappings": self._es_runtime(), "query": self._es_base_query(window, filters), "aggs": {"relationships": {"composite": {"size": 500, "sources": sources}, "aggs": {"latency": {"percentiles": {"field": "topology.duration_ms", "percents": [50, 95, 99]}}, "first_seen": {"min": {"field": "@timestamp"}}, "last_seen": {"max": {"field": "@timestamp"}}, "errors": {"filter": {"bool": {"should": [{"range": {"http.response.status_code": {"gte": 400}}}, {"range": {"http_status": {"gte": 400}}}, {"term": {"event.outcome": "failure"}}], "minimum_should_match": 1}}}}}}}
        result = self._es_request(body) or {}
        buckets = (((result.get("aggregations") or {}).get("relationships") or {}).get("buckets") or [])
        rows = []
        for bucket in buckets:
            key = bucket.get("key") or {}
            percentiles = ((bucket.get("latency") or {}).get("values") or {})
            rows.append({**{d: key.get(d, "") for d in dimensions}, "request_count": bucket.get("doc_count", 0), "error_count": (bucket.get("errors") or {}).get("doc_count", 0), "p50_latency_ms": percentiles.get("50.0", 0.0), "p95_latency_ms": percentiles.get("95.0", 0.0), "p99_latency_ms": percentiles.get("99.0", 0.0), "first_seen_ms": (bucket.get("first_seen") or {}).get("value"), "last_seen_ms": (bucket.get("last_seen") or {}).get("value"), "evidence_types": ["OTEL_PARENT_CHILD"], "confidence": 1.0})
        return rows

    def _es_graph(self, window: Dict[str, Any]) -> Dict[str, Any]:
        rows = self._es_rows(["caller_service", "target_service"], window)
        nodes: Dict[str, Any] = {}
        edges = []
        for row in rows:
            c, t = canonical_service(row.get("caller_service")), canonical_service(row.get("target_service"))
            metrics = self._metrics(row, window["duration_seconds"])
            for name in (c, t):
                nodes.setdefault(name, {"id": f"service:{name}", "name": name, "type": "service", "service": name, "metrics": metrics})
            edges.append({"id": f"service-edge:{c}->{t}", "source": f"service:{c}", "target": f"service:{t}", "source_name": c, "target_name": t, "metrics": metrics, "evidence_type": "direct", "direct": True, "inferred": False})
        return {"window": window, "nodes": list(nodes.values()), "edges": edges, "changes": {"baseline": "insufficient_history", "new_edges": [], "disappeared_edges": []}, "anonymous": {"total_requests": sum(_safe_int(r.get("request_count")) for r in rows), "identified_requests": 0, "anonymous_requests": 0, "identified_request_percentage": 0.0, "anonymous_request_percentage": 0.0, "anonymous_tps": 0.0, "top_services": [], "top_apis": []}, "backend": self.backend}

    def _es_expansion(self, kind: str, service: str, api: str, window: Dict[str, Any]) -> Dict[str, Any]:
        filters = {"target_service": service}
        if api:
            filters["target_api"] = api
        dimensions = ["target_api"] if kind == "api" else ["principal"]
        rows = self._es_rows(dimensions, window, filters)
        nodes = []
        for row in rows:
            value = row.get(dimensions[0]) or ("-anonymous-" if kind == "principal" else "unknown")
            metrics = self._metrics(row, window["duration_seconds"])
            nodes.append({"id": f"{kind}:{service}:{value}", "name": value, "type": kind, "service": service, "api": api or value if kind == "api" else api, "principal": value if kind == "principal" else None, "metrics": metrics})
        parent = {"id": f"service:{service}" if kind == "api" else f"api:{service}:{api}", "name": service if kind == "api" else api, "type": "service" if kind == "api" else "api"}
        return {"window": window, "parent": parent, "nodes": nodes, "edges": [], "changes": {"baseline": "insufficient_history", "new_nodes": [], "disappeared_nodes": []}, "anonymous": {"total_requests": 0, "identified_requests": 0, "anonymous_requests": 0, "identified_request_percentage": 0.0, "anonymous_request_percentage": 0.0, "anonymous_tps": 0.0, "top_services": [], "top_apis": []}, "backend": self.backend}

    def _es_series(self, window: Dict[str, Any], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        interval, interval_seconds = "5m", 300
        body = {
            "size": 0,
            "runtime_mappings": self._es_runtime(),
            "query": self._es_base_query(window, filters),
            "aggs": {
                "timeline": {
                    "date_histogram": {"field": "@timestamp", "fixed_interval": interval, "min_doc_count": 1},
                    "aggs": {
                        "latency": {"percentiles": {"field": "topology.duration_ms", "percents": [95]}},
                        "errors": {"filter": {"bool": {"should": [
                            {"range": {"http.response.status_code": {"gte": 400}}},
                            {"range": {"http_status": {"gte": 400}}},
                            {"term": {"event.outcome": "failure"}},
                        ], "minimum_should_match": 1}}},
                    },
                }
            },
        }
        result = self._es_request(body) or {}
        buckets = (((result.get("aggregations") or {}).get("timeline") or {}).get("buckets") or [])
        series = []
        for bucket in buckets:
            timestamp_ms = _safe_int(bucket.get("key"))
            request_count = _safe_int(bucket.get("doc_count"))
            errors = _safe_int((bucket.get("errors") or {}).get("doc_count"))
            p95 = ((bucket.get("latency") or {}).get("values") or {}).get("95.0", 0.0)
            series.append({
                "bucket_start": timestamp_ms // 1000,
                "timestamp_ms": timestamp_ms,
                "tps": round(request_count / interval_seconds, 3),
                "request_count": request_count,
                "p95_latency_ms": _safe_float(p95),
                "error_rate": round(errors / max(1, request_count), 4),
                "request_bytes": 0,
                "response_bytes": 0,
            })
        return series

    def _es_detail(self, kind: str, value: str, api: str, window: Dict[str, Any]) -> Dict[str, Any]:
        filters = {"target_service": value} if kind == "service" else {"principal": value} if kind == "principal" else {"target_api": api}
        dimensions = ["target_service"] if kind == "service" else ["principal"] if kind == "principal" else ["target_api"]
        rows = self._es_rows(dimensions, window, filters)
        metrics = self._metrics(rows[0] if rows else None, window["duration_seconds"])
        return {"entity": {"name": value if kind != "api" else api, "type": kind, "service": value if kind == "service" else None, "api": api if kind == "api" else None, "principal": value if kind == "principal" else None}, "metrics": metrics, "series": self._es_series(window, filters), "changes": {"baseline": "insufficient_history"}, "anonymous": {}, "backend": self.backend}

    def _es_ips(self, principal: str, window: Dict[str, Any], page_size: int, cursor: Optional[List[str]], service: Optional[str], api: Optional[str], filter_name: str) -> Dict[str, Any]:
        # Runtime composite IP aggregation is intentionally bounded. It uses
        # ES's `after` key as the cursor and never emits source IPs as graph nodes.
        filters = {"principal": principal}
        if service:
            filters["target_service"] = service
        if api:
            filters["target_api"] = api
        body = {"size": 0, "runtime_mappings": self._es_runtime(), "query": self._es_base_query(window, filters), "aggs": {"ips": {"composite": {"size": page_size, "sources": [{"source_ip": {"terms": {"field": "client.ip.keyword"}}}], **({"after": {"source_ip": cursor[0]}} if cursor else {})}}}}
        result = self._es_request(body) or {}
        buckets = (((result.get("aggregations") or {}).get("ips") or {}).get("buckets") or [])
        items = []
        for bucket in buckets:
            ip = str((bucket.get("key") or {}).get("source_ip") or "unknown")
            role, label, confidence = classify_source_ip_role(ip)
            item = {"source_ip": ip, "request_count": bucket.get("doc_count", 0), "tps": round(_safe_int(bucket.get("doc_count")) / max(1, window["duration_seconds"]), 3), "is_load_balancer": role in ("load_balancer", "reverse_proxy", "nat_gateway"), "source_ip_role": role, "role_label": label, "attribution_confidence": confidence, "is_new_ip": False}
            if filter_name == "lb" and not item["is_load_balancer"]:
                continue
            if filter_name == "direct" and item["is_load_balancer"]:
                continue
            items.append(item)
        after = ((result.get("aggregations") or {}).get("ips") or {}).get("after_key")
        next_cursor = encode_cursor([str(after.get("source_ip")), "", "", ""]) if after else None
        return {"principal": principal, "items": items, "next_cursor": next_cursor, "page_size": page_size, "window": window, "filters": {"service": service, "api": api, "filter": filter_name}, "backend": self.backend}
