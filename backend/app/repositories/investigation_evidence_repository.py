"""The bounded, server-authorized evidence reader for investigations.

This module intentionally does not reuse the normal trace repository.  An
investigation has a selected backend and an empty or failed query on that
backend is evidence coverage, never permission to fall back to another store.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from backend.config import settings
from backend.app.models.investigation import EvidenceContext, FindingRef, FindingSnapshot, finding_key
from backend.app.repositories.db_context import get_connection
from backend.app.services.investigation_evidence import (
    SourceError,
    _safe_reason,
    build_snapshot,
    parse_bounded_json,
)


QUERY_SETTINGS = {
    "max_execution_time": 2,
    "max_rows_to_read": 100000,
    "max_result_rows": 1000,
    "max_memory_usage": 67108864,
    "read_overflow_mode": "throw",
    "result_overflow_mode": "throw",
}


class InvestigationEvidenceRepository:
    def __init__(self, db_path: str | None = None, settings_obj: Any = settings,
                 connection_factory: Any = None, http_client: Any = None,
                 clock: Any = None):
        self.db_path = db_path
        self.settings = settings_obj
        self._connection_factory = connection_factory or get_connection
        self.http_client = http_client
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.query_count = 0
        self.source_query_count = 0
        self._context_query_counts: dict[str, int] = {}
        self._contexts: dict[str, EvidenceContext] = {}
        self.backend = "elasticsearch" if self._es_configured() else "clickhouse"

    def _es_configured(self) -> bool:
        return self.settings.storage_backend in ("elasticsearch", "elk") or bool(self.settings.elasticsearch_url)

    def register_context(self, context: EvidenceContext) -> None:
        if not isinstance(context, EvidenceContext):
            raise ValueError("server-created evidence context required")
        context_id = str(context.context_id)
        existing = self._contexts.get(context_id)
        if existing is not None and existing is not context:
            raise ValueError("evidence context ID is already registered")
        self._contexts[context_id] = context
        self._context_query_counts.setdefault(context_id, 0)

    @contextmanager
    def _client(self) -> Iterator[Any]:
        with self._connection_factory(self.db_path) as connection:
            yield connection.client

    def _query(self, sql: str, params: dict[str, Any], context: EvidenceContext | None = None) -> Any:
        if context is None:
            self.source_query_count += 1
            if self.source_query_count > 6:
                raise SourceError("source_query_budget", "source query budget exhausted")
        else:
            context_id = str(context.context_id)
            self._context_query_counts[context_id] = self._context_query_counts.get(context_id, 0) + 1
            if self._context_query_counts[context_id] > 12:
                raise SourceError("evidence_query_budget", "evidence query budget exhausted")
        self.query_count += 1
        with self._client() as client:
            return client.query(sql, parameters=params, settings=QUERY_SETTINGS)

    @staticmethod
    def _rows(result: Any) -> list[dict[str, Any]]:
        columns = list(getattr(result, "column_names", ()))
        rows = getattr(result, "result_rows", ())
        return [dict(zip(columns, row)) for row in rows]

    def _check_context(self, context: EvidenceContext, window: str, limit: int, maximum: int) -> tuple[int, int]:
        if not isinstance(context, EvidenceContext) or self._contexts.get(str(context.context_id)) is not context:
            raise ValueError("server-created evidence context required")
        if window not in {"focus", "surrounding", "history"} or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
            raise ValueError("invalid evidence request")
        if context.deadline_ms <= self.clock():
            raise SourceError("evidence_deadline", "evidence deadline exceeded")
        if window == "focus":
            start, end = context.focus_start_ms, context.focus_end_ms
        elif window == "surrounding":
            start, end = context.start_ms, context.end_ms
        else:
            start, end = max(0, context.focus_start_ms - 7 * 86_400_000), context.focus_start_ms
        return start, max(start + 1, end)

    @staticmethod
    def _where_dimensions(context: EvidenceContext, columns: dict[str, str]) -> tuple[list[str], dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        for key, column in columns.items():
            value = getattr(context, key, None)
            if value:
                clauses.append("{} = {{{}:String}}".format(column, key))
                params[key] = value
        return clauses, params

    def load_source(self, ref: FindingRef, now_ms: int | None = None) -> tuple[FindingSnapshot, str, str] | None:
        if not hasattr(ref, "kind"):
            raise ValueError("validated finding reference required")
        # Each exact source read is its own bounded admission/check budget;
        # repeated lifecycle checks must not exhaust a long-lived worker.
        self.source_query_count = 0
        kind, identifier = finding_key(ref)
        if kind == "anomaly_event":
            sql = "SELECT * FROM anomaly_events FINAL WHERE id = {finding_id:UInt64} LIMIT 2"
            params = {"finding_id": int(identifier)}
        elif kind == "principal_change_event":
            sql = "SELECT * FROM principal_change_events FINAL WHERE id = {finding_id:UInt64} LIMIT 2"
            params = {"finding_id": int(identifier)}
        else:
            sql = "SELECT * FROM incidents FINAL WHERE incident_id = {finding_id:String} LIMIT 2"
            params = {"finding_id": identifier}
        rows = self._rows(self._query(sql, params))
        if not rows:
            return None
        if kind == "principal_change_event":
            fingerprints = {str(row.get("fingerprint", "")) for row in rows}
            if len(fingerprints) > 1:
                raise SourceError("invalid_source", "source ID is associated with multiple change fingerprints")
        return build_snapshot(ref, rows[0], now_ms)

    def related_changes(self, context: EvidenceContext, snapshot: FindingSnapshot,
                        window: str = "focus", limit: int = 20) -> list[dict[str, Any]]:
        if snapshot.source_version != context.finding_version or finding_key(snapshot.ref) != (context.finding_kind, context.finding_id):
            raise SourceError("source_changed", "evidence snapshot does not match context")
        start, end = self._check_context(context, window, limit, 20)
        clauses = ["detected_at >= {start:UInt64}", "detected_at < {end:UInt64}"]
        params: dict[str, Any] = {"start": start, "end": end, "limit": limit}
        if context.finding_kind == "incident":
            member_ids = [str(value) for value in snapshot.source_facts.get("contributing_event_ids", []) if str(value).isdigit()][:10]
            clauses.append("(incident_id = {incident_id:String} OR has({member_ids:Array(String)}, toString(id)))")
            params.update({"incident_id": context.finding_id or "", "member_ids": member_ids})
        else:
            dimensions, dimension_params = self._where_dimensions(context, {
                "principal_name": "principal_name", "environment": "environment",
                "caller_service": "caller_service", "target_service": "target_service",
                "operation": "operation", "source_ip": "source_ip",
            })
            clauses.extend(dimensions)
            params.update(dimension_params)
        sql = """SELECT id,fingerprint,principal_id,principal_name,environment,change_type,score,severity,status,
            caller_service,target_service,operation,source_ip,old_value,new_value,first_observed,detected_at,updated_at,
            reliability,reason_json FROM principal_change_events FINAL WHERE __WHERE__
            ORDER BY detected_at ASC,id ASC LIMIT {limit:UInt8}""".replace("__WHERE__", " AND ".join(clauses))
        result = self._query(sql, params, context)
        output: list[dict[str, Any]] = []
        for row in self._rows(result):
            raw_reason = row.pop("reason_json", None)
            reason = {}
            if raw_reason not in (None, ""):
                reason = _safe_reason(parse_bounded_json(raw_reason, "reason_json"), [])
            row["id"] = str(row.get("id"))
            row["type"] = row.pop("change_type", None)
            if context.finding_kind == "incident":
                member_ids = {str(value) for value in snapshot.source_facts.get("contributing_event_ids", [])}
                row["correlation_scope"] = "contributing" if row["id"] in member_ids else "incident_related"
            row["reason"] = reason
            output.append(row)
        return output

    def related_traces(self, context: EvidenceContext, window: str = "focus", limit: int = 20,
                       selection: str = "recent") -> list[dict[str, Any]]:
        start, end = self._check_context(context, window, limit, 20)
        if selection not in {"recent", "errors"}:
            raise ValueError("invalid trace selection")
        # This API returns bounded relationship summaries. Exact span records
        # belong to internal processing and are never fetched by the UI request.
        if context.environment or context.source_ip:
            return []
        clauses = ["bucket_size = {bucket_size:UInt32}",
                   "bucket_start * 1000 >= {start:UInt64}",
                   "bucket_start * 1000 < {end:UInt64}"]
        params: dict[str, Any] = {
            "bucket_size": 300, "start": start, "end": end, "limit": limit,
        }
        dimensions, dimension_params = self._where_dimensions(context, {
            "principal_name": "principal_name", "caller_service": "caller_service",
            "target_service": "target_service", "operation": "operation",
        })
        clauses.extend(dimensions)
        params.update(dimension_params)
        if selection == "errors":
            clauses.append("error_count > 0")
        sql = """SELECT bucket_start * 1000 AS timestamp_ms,principal_name,caller_service,
            target_service,operation,sum(request_count) AS request_count,sum(error_count) AS error_count,
            max(latency_p95) AS latency_p95_ms,sum(request_bytes) AS request_bytes,
            sum(response_bytes) AS response_bytes
            FROM metric_buckets FINAL WHERE __WHERE__
            GROUP BY bucket_start,principal_name,caller_service,target_service,operation
            ORDER BY bucket_start DESC LIMIT {limit:UInt8}""".replace("__WHERE__", " AND ".join(clauses))
        return [{**row, "record_type": "worker_metric_rollup", "trace_id": None,
                 "evidence_provenance": "metric_buckets"}
                for row in self._rows(self._query(sql, params, context))]

    def window_metrics(self, context: EvidenceContext, window: str = "focus", limit: int = 90,
                       bucket_size: int = 60) -> list[dict[str, Any]]:
        start, end = self._check_context(context, window, limit, 90)
        if bucket_size not in {60, 300}:
            raise ValueError("invalid metric bucket size")
        clauses = ["bucket_start >= {start:UInt64}", "bucket_start < {end:UInt64}", "bucket_size = {bucket_size:UInt32}"]
        params: dict[str, Any] = {"start": start // 1000, "end": end // 1000, "bucket_size": bucket_size, "limit": limit}
        dimensions, dimension_params = self._where_dimensions(context, {
            "principal_name": "principal_name", "caller_service": "caller_service",
            "target_service": "target_service", "operation": "operation",
        })
        clauses.extend(dimensions)
        params.update(dimension_params)
        sql = """SELECT bucket_start * 1000 AS bucket_start_ms,bucket_size AS bucket_size_sec,
            sum(request_count) AS request_count,sum(error_count) AS error_count,
            if(sum(request_count)=0,NULL,sum(error_count)/sum(request_count)) AS error_rate_fraction,
            sum(request_count)/toFloat64(bucket_size) AS rps,if(sum(request_count)=0,NULL,sum(latency_sum)/sum(request_count)) AS latency_avg_ms,
            max(latency_p95) AS max_bucket_p95_ms,count() AS observed_bucket_count
            FROM metric_buckets FINAL WHERE __WHERE__ GROUP BY bucket_start,bucket_size
            ORDER BY bucket_start ASC LIMIT {limit:UInt8}""".replace("__WHERE__", " AND ".join(clauses))
        return self._rows(self._query(sql, params, context))

    def attached_baseline(self, context: EvidenceContext, snapshot: FindingSnapshot) -> list[dict[str, Any]]:
        if snapshot.source_version != context.finding_version or finding_key(snapshot.ref) != (context.finding_kind, context.finding_id):
            raise SourceError("source_changed", "evidence snapshot does not match context")
        self._check_context(context, "focus", 1, 90)
        facts = snapshot.source_facts
        values: list[dict[str, Any]] = []
        for metric in ("baseline", "current", "delta_percentage", "confidence"):
            if metric in facts:
                values.append({"dimension": "finding", "metric": metric, "value": facts[metric],
                               "provenance": "source_snapshot", "source_version": snapshot.source_version})
        if context.target_service and not context.environment:
            dt_ms = snapshot.observation_window.start_ms if snapshot.observation_window else None
            if dt_ms is not None:
                import datetime as datetime_module
                dt = datetime_module.datetime.fromtimestamp(dt_ms / 1000.0, tz=datetime_module.timezone.utc)
                result = self._query("""SELECT dimension_type,dimension_key,hour_of_day,day_of_week,sample_count,
                    rps_median,rps_mad,latency_p95_median,latency_p95_mad,error_rate_median,error_rate_mad
                    FROM baseline_metrics FINAL WHERE dimension_type = 'service' AND dimension_key = {dimension_key:String}
                      AND hour_of_day = {hour:UInt8} AND day_of_week = {day:UInt8} LIMIT 1""",
                    {"dimension_key": context.target_service, "hour": dt.hour, "day": dt.weekday()}, context)
                for row in self._rows(result):
                    values.append({"dimension": row.get("dimension_type"), "metric": "rps", "value": row.get("rps_median"),
                                   "median": row.get("rps_median"), "mad": row.get("rps_mad"), "sample_count": row.get("sample_count"),
                                   "hour": row.get("hour_of_day"), "day": row.get("day_of_week"),
                                   "provenance": "reference_as_of_read", "reference_as_of_read": self.clock()})
        return values[:10]

    def principal_history(self, context: EvidenceContext, limit: int = 24) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], str]:
        self._check_context(context, "history", limit, 24)
        if not context.principal_name:
            return []
        if context.environment:
            return [], "environment_unqualified_aggregate_omitted"
        start, end = max(0, context.focus_start_ms - 7 * 86_400_000), context.focus_start_ms
        result = self._query("""SELECT day_start AS day_start_ms,observation_count AS observations,
            error_count AS errors,unique_callers,unique_sources,unique_targets,unique_operations
            FROM principal_daily_stats FINAL WHERE principal_name = {principal_name:String}
              AND day_start >= {start:UInt64} AND day_start < {end:UInt64}
            ORDER BY day_start ASC LIMIT {limit:UInt8}""",
            {"principal_name": context.principal_name, "start": start, "end": end, "limit": limit}, context)
        rows = self._rows(result)
        if not context.environment:
            rows = [{**row, "scope": "environment_unqualified"} for row in rows]
        return rows

    def service_context(self, context: EvidenceContext, limit: int = 10) -> list[dict[str, Any]]:
        self._check_context(context, "surrounding", limit, 10)
        if context.environment:
            return []
        clauses = ["bucket_start >= {start:UInt64}", "bucket_start < {end:UInt64}", "bucket_size = 60"]
        params: dict[str, Any] = {"start": context.start_ms // 1000, "end": context.end_ms // 1000, "limit": limit}
        if context.target_service:
            clauses.append("target_service = {target_service:String}")
            params["target_service"] = context.target_service
        sql = """SELECT caller_service,target_service,sum(request_count) AS request_count,
            if(sum(request_count)=0,NULL,sum(error_count)/sum(request_count)) AS error_rate_fraction,
            arraySlice(groupUniqArray(operation),1,10) AS operations,
            arraySlice(groupUniqArray(principal_name),1,10) AS principals
            FROM metric_buckets FINAL WHERE __WHERE__ GROUP BY caller_service,target_service
            ORDER BY request_count DESC LIMIT {limit:UInt8}""".replace("__WHERE__", " AND ".join(clauses))
        return [{**row, "scope": "environment_unqualified"} for row in self._rows(self._query(sql, params, context))]

    def data_quality(self, context: EvidenceContext, limit: int = 60) -> list[dict[str, Any]]:
        start, end = self._check_context(context, "focus", limit, 90)
        if self.backend == "elasticsearch":
            return []
        result = self._query("""SELECT window_start_sec * 1000 AS start_ms,window_end_sec * 1000 AS end_ms,
            total_spans,counted_requests,caller_linkage_rate,username_extraction_rate,is_collection_gap,sampling_ratio,created_at
            FROM telemetry_quality_windows FINAL WHERE window_end_sec >= {start_sec:UInt32}
              AND window_start_sec < {end_sec:UInt32} ORDER BY window_start_sec ASC LIMIT {limit:UInt8}""",
            {"start_sec": start // 1000, "end_sec": end // 1000, "limit": limit}, context)
        return [{**row, "scope": "global"} for row in self._rows(result)]
