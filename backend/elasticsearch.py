from __future__ import annotations

import os
from typing import Any, Iterator, Optional

import httpx

from backend.config import settings
from .app.repositories.db_context import db_transaction, get_connection
from .app.repositories.trace_repository import TraceRepository
from .app.services.normalization import normalize_otel_record


class ElasticsearchReader:
    """Optional read-only, incremental connector. It never logs request headers or bodies."""
    def __init__(self):
        self.url = (os.environ.get("OTEL_ES_URL") or getattr(settings, "elasticsearch_url", "")).rstrip("/")
        self.index = os.environ.get("OTEL_ES_INDEX") or getattr(settings, "elasticsearch_index", "apm-*,traces-apm*")
        self.api_key = os.environ.get("OTEL_ES_API_KEY") or getattr(settings, "elasticsearch_api_key", "")
        self.user = os.environ.get("OTEL_ES_USER") or getattr(settings, "elasticsearch_user", "")
        self.password = os.environ.get("OTEL_ES_PASSWORD") or getattr(settings, "elasticsearch_password", "")
        self.verify = (os.environ.get("OTEL_ES_VERIFY_TLS") or str(getattr(settings, "elasticsearch_verify_tls", False))).lower() == "true"

    def pages(self, cursor: list[Any] | None=None, batch_size: int=1000) -> Iterator[tuple[list[dict[str,Any]],list[Any]|None]]:
        if not self.url: raise RuntimeError("Elasticsearch connector is not configured")
        search_after=cursor
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        auth = (self.user, self.password) if not self.api_key and self.user and self.password else None
        with httpx.Client(base_url=self.url,verify=self.verify,timeout=30,headers=headers,auth=auth) as client:
            start_time_ms = getattr(settings, "worker_start_time_ms", None)
            while True:
                filters: list[dict[str, Any]] = [{"terms": {"processor.event": ["transaction", "span"]}}]
                if search_after is None and start_time_ms is not None:
                    filters.append({"range": {"@timestamp": {"gte": start_time_ms}}})
                body = {
                    "size": min(batch_size, 5000),
                    "sort": [{"@timestamp": "asc"}, {"_id": "asc"}],
                    "query": {"bool": {"filter": filters}},
                }
                if search_after:
                    body["search_after"] = search_after
                response = client.post(f"/{self.index}/_search", json=body)
                response.raise_for_status(); hits = response.json().get("hits", {}).get("hits", [])
                if not hits:
                    break
                search_after = hits[-1].get("sort"); yield hits, search_after

    def sync(self, force: bool = False, db_path: Optional[str] = None) -> dict[str, Any]:
        sync_enabled = os.environ.get("OTEL_ES_SYNC_ENABLED", "").lower() in ("true", "1", "yes")
        if settings.clickhouse_only_agent_traces and not force and not sync_enabled:
            return {
                "status": "skipped",
                "message": "Elasticsearch sync skipped: OTel trace data already resides in Elasticsearch; ClickHouse only stores agent trace data.",
                "read": 0,
                "inserted": 0,
            }
        import json, time
        with get_connection(db_path) as db:
            row = db.execute("SELECT cursor_json FROM checkpoints FINAL WHERE source='elasticsearch'").fetchone()
        cursor = json.loads(row[0]) if row and row[0] else None
        totals = {"read": 0, "inserted": 0, "duplicates": 0, "rejected": 0}
        repository = TraceRepository(db_path=db_path)
        for hits, cursor in self.pages(cursor):
            traces = []
            for hit in hits:
                totals["read"] += 1
                trace = normalize_otel_record(hit)
                if trace is None:
                    totals["rejected"] += 1
                else:
                    traces.append(trace)
            inserted = repository.insert_traces(traces)
            totals["inserted"] += inserted
            totals["duplicates"] += len(traces) - inserted
            with db_transaction(db_path) as db:
                db.execute(
                    "INSERT INTO checkpoints(source,cursor_json,updated_at_ms) VALUES('elasticsearch',?,?)",
                    (json.dumps(cursor, separators=(",", ":")), int(time.time() * 1000)),
                )
        return totals
