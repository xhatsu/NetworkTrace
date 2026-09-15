from __future__ import annotations

import os
from typing import Any, Iterator

import httpx

from backend.config import settings
from .app.repositories.db_context import db_transaction, get_connection
from .app.repositories.trace_repository import TraceRepository
from .app.services.normalization import normalize_otel_record


class ElasticsearchReader:
    """Optional read-only, incremental connector. It never logs request headers or bodies."""
    def __init__(self):
        self.url=os.environ.get("OTEL_ES_URL","").rstrip("/")
        self.index=os.environ.get("OTEL_ES_INDEX","traces-apm*")
        self.api_key=os.environ.get("OTEL_ES_API_KEY","")
        self.verify=os.environ.get("OTEL_ES_VERIFY_TLS","true").lower()=="true"

    def pages(self, cursor: list[Any] | None=None, batch_size: int=1000) -> Iterator[tuple[list[dict[str,Any]],list[Any]|None]]:
        if not self.url: raise RuntimeError("Elasticsearch connector is not configured")
        search_after=cursor
        with httpx.Client(base_url=self.url,verify=self.verify,timeout=30,headers={"Authorization":f"ApiKey {self.api_key}"}) as client:
            while True:
                body={"size":min(batch_size,5000),"sort":[{"@timestamp":"asc"},{"_id":"asc"}],"query":{"bool":{"filter":[{"terms":{"processor.event":["transaction","span"]}}]}}}
                if search_after: body["search_after"]=search_after
                response=client.post(f"/{self.index}/_search",json=body)
                response.raise_for_status(); hits=response.json().get("hits",{}).get("hits",[])
                if not hits: break
                search_after=hits[-1].get("sort"); yield hits,search_after

    def sync(self) -> dict[str, Any]:
        if settings.clickhouse_only_agent_traces:
            return {
                "status": "skipped",
                "message": "Elasticsearch sync skipped: OTel trace data already resides in Elasticsearch; ClickHouse only stores agent trace data.",
                "read": 0,
                "inserted": 0,
            }
        import json,time
        with get_connection() as db:
            row=db.execute("SELECT cursor_json FROM checkpoints WHERE source='elasticsearch'").fetchone()
        cursor=json.loads(row[0]) if row else None; totals={"read":0,"inserted":0,"duplicates":0,"rejected":0}
        repository = TraceRepository()
        for hits,cursor in self.pages(cursor):
            traces=[]
            for hit in hits:
                totals["read"] += 1
                trace=normalize_otel_record(hit)
                if trace is None: totals["rejected"] += 1
                else: traces.append(trace)
            inserted=repository.insert_traces(traces)
            totals["inserted"] += inserted
            totals["duplicates"] += len(traces)-inserted
            with db_transaction() as db:
                db.execute("INSERT INTO checkpoints VALUES ('elasticsearch',?,?)",(json.dumps(cursor),int(time.time()*1000)))
        return totals
