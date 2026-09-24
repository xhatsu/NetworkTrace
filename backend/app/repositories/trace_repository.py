from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.db_context import get_connection, db_transaction
from backend.app.repositories.elasticsearch_trace_repository import ElasticsearchTraceRepository
from backend.config import settings

log = logging.getLogger("tracescope-trace-repo")

class TraceRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self._es_repo = ElasticsearchTraceRepository()

    def insert_traces(self, traces: List[NormalizedTrace], skip_dedup: bool = False) -> int:
        if not traces:
            return 0
        all_cols = [
            "event_uid", "timestamp", "timestamp_ms", "trace_id", "span_id", "parent_span_id",
            "service_name", "service_instance", "service_environment",
            "caller_service", "caller_instance", "caller_ip",
            "target_service", "target_instance", "target_ip", "target_port",
            "principal_name", "operation", "http_method", "http_route",
            "http_status", "status_class", "duration_ms", "duration_us", "outcome",
            "protocol", "span_kind", "attributes_json", "created_at",
            "environment", "principal_id", "identity_source",
            "auth_result", "auth_evidence", "caller_resolution_method", "caller_confidence",
            "network_peer_ip", "original_client_ip", "original_client_ip_trusted",
            "source_group", "operation_key", "soap_fault_code", "outcome_class",
            "sampling_context", "dedup_key", "observed_ip", "effective_client_ip",
            "ip_resolution", "client_identity_quality", "context_quality",
            "traffic_class", "is_agent_trace", "request_bytes", "response_bytes"
        ]
        with db_transaction(self.db_path) as db:
            table_info = db.execute("PRAGMA table_info(traces)").fetchall()
            existing = {row[1] for row in table_info}
            cols = [c for c in all_cols if c in existing]

            if skip_dedup:
                traces_to_insert = traces
            else:
                # Filter out traces whose dedup_key already exists
                dedup_keys = [t.dedup_key for t in traces if getattr(t, "dedup_key", None)]
                existing_keys = set()
                if dedup_keys:
                    chunk_sz = 500
                    for k in range(0, len(dedup_keys), chunk_sz):
                        dk_chunk = dedup_keys[k:k + chunk_sz]
                        placeholders = ",".join("?" for _ in dk_chunk)
                        rows = db.execute(f"SELECT dedup_key FROM traces WHERE dedup_key IN ({placeholders})", dk_chunk).fetchall()
                        existing_keys.update(r[0] for r in rows if r[0])

                traces_to_insert = [t for t in traces if not getattr(t, "dedup_key", None) or t.dedup_key not in existing_keys]
                if not traces_to_insert:
                    return 0

            sql = f"INSERT INTO traces ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
            before = db.total_changes
            db.executemany(sql, [[getattr(t, c, None) for c in cols] for t in traces_to_insert])
            inserted = db.total_changes - before
        return inserted

    def get_trace(self, trace_id: str) -> Dict[str, Any] | None:
        # Trace Explorer remains the documented temporary exception to the
        # aggregate-read boundary. Use the configured trace store, while
        # keeping all other user-facing reads on precomputed models.
        if settings.trace_storage_backend in ("elasticsearch", "elk"):
            if not self._es_repo.is_configured():
                return None
            try:
                return self._es_repo.get_trace(trace_id)
            except Exception as exc:
                log.warning("Elasticsearch get_trace failed for %s: %s", trace_id, exc)
                return None

        with get_connection(self.db_path) as db:
            rows = [dict(row) for row in db.execute(
                "SELECT * FROM traces WHERE trace_id=? ORDER BY timestamp_ms ASC LIMIT 1000",
                (trace_id,),
            )]
        if not rows:
            return None
        return {"trace_id": trace_id, "spans": rows, "count": len(rows), "backend": "clickhouse"}

    def list_traces(
        self,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        service: Optional[str] = None,
        caller: Optional[str] = None,
        target: Optional[str] = None,
        principal: Optional[str] = None,
        operation: Optional[str] = None,
        source_ip: Optional[str] = None,
        status: Optional[str] = None,
        trace_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        # Trace Explorer's raw-span list is the same documented temporary
        # exception as its waterfall lookup above.
        if settings.trace_storage_backend in ("elasticsearch", "elk"):
            if not self._es_repo.is_configured():
                return []
            try:
                return self._es_repo.list_traces(
                    start_ms=start_ms, end_ms=end_ms, service=service, caller=caller,
                    target=target, principal=principal, operation=operation, source_ip=source_ip,
                    status=status, trace_id=trace_id, limit=limit, offset=offset
                ) or []
            except Exception as exc:
                log.warning("Elasticsearch list_traces failed: %s", exc)
                return []

        clauses = []
        args: List[Any] = []
        if start_ms is not None:
            clauses.append("timestamp_ms >= ?")
            args.append(start_ms)
        if end_ms is not None:
            clauses.append("timestamp_ms < ?")
            args.append(end_ms)
        if trace_id:
            clauses.append("trace_id = ?")
            args.append(trace_id)
        if service:
            clauses.append("(service_name = ? OR target_service = ?)")
            args.extend([service, service])
        if caller:
            clauses.append("caller_service = ?")
            args.append(caller)
        if target:
            clauses.append("target_service = ?")
            args.append(target)
        if principal:
            clauses.append("principal_name = ?")
            args.append(principal)
        if source_ip:
            clauses.append("caller_ip = ?")
            args.append(source_ip)
        if operation:
            clauses.append("operation = ?")
            args.append(operation)
        if status:
            if status == "error":
                clauses.append("(http_status >= 400 OR outcome = 'failure')")
            elif status.isdigit():
                clauses.append("http_status = ?")
                args.append(int(status))

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT * FROM traces WHERE {where} ORDER BY timestamp_ms DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with get_connection(self.db_path) as db:
            return [dict(row) for row in db.execute(sql, args)]
