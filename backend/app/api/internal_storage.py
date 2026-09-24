"""Authenticated internal persistence APIs for role-isolated workloads.

These routes are hidden from OpenAPI because they are a deployment boundary,
not a public product surface. They preserve a single trusted write policy even
when ingest and agent receivers scale separately against ClickHouse.
"""
from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from backend.config import settings
from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.agent_stats_repository import AgentStatsRepository
from backend.app.repositories.db_context import get_connection
from backend.repository import StorageRepository
from backend.app.services.ingest_writer import (
    IngestCommitTimeout,
    IngestQueueFull,
    ingest_writer,
)

router = APIRouter(prefix="/internal/v1", tags=["internal"], include_in_schema=False)

# Keep this router private: external callers must traverse the validated public APIs.


def require_internal_token(
    token: Annotated[str | None, Header(alias="X-TraceScope-Internal-Token")] = None,
) -> None:
    expected = settings.internal_api_token
    if not expected:
        raise HTTPException(status_code=503, detail="Internal storage API is disabled")
    if token is None or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid internal service token")


class TraceCommitRequest(BaseModel):
    traces: list[NormalizedTrace] = Field(max_length=10_000)
    batch_id: str = Field(default="", max_length=512)
    node: str = Field(default="unknown", max_length=512)


@router.get("/readyz")
async def internal_ready(
    token: Annotated[str | None, Header(alias="X-TraceScope-Internal-Token")] = None,
) -> dict[str, str]:
    require_internal_token(token)
    with get_connection() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ready"}


@router.post("/traces/commit")
async def commit_traces(
    payload: TraceCommitRequest,
    token: Annotated[str | None, Header(alias="X-TraceScope-Internal-Token")] = None,
) -> dict[str, Any]:
    require_internal_token(token)
    try:
        result = await ingest_writer.submit_async(payload.traces, payload.batch_id, payload.node)
    except IngestQueueFull:
        raise HTTPException(429, "Ingestion queue is full; retry with backoff", headers={"Retry-After": "1"}) from None
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(503, "Storage commit is unavailable; retry with the same X-Batch-Id", headers={"Retry-After": "1"}) from None
    return {"inserted": result.inserted, "duplicate": result.duplicate}


@router.get("/ingestion/status")
async def ingestion_status(
    token: Annotated[str | None, Header(alias="X-TraceScope-Internal-Token")] = None,
) -> dict[str, Any]:
    require_internal_token(token)
    with StorageRepository().connect() as db:
        count, min_ts, max_ts = db.execute(
            "SELECT COALESCE(SUM(request_count),0),MIN(bucket_start)*1000,MAX(bucket_start+bucket_size)*1000 FROM metric_buckets FINAL WHERE bucket_size=300"
        ).fetchone()
        jobs = [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY started_at_ms DESC")]
    return {
        "events": count,
        "traces": count,
        "earliest_event_ms": min_ts,
        "latest_event_ms": max_ts,
        "latest_ingested_ms": None,
        "jobs": jobs,
        "demo_mode": settings.demo_mode,
        "sampling_coverage": "unknown",
        "ingest_writer": ingest_writer.snapshot(),
    }


@router.post("/agent-stats/samples")
async def store_agent_sample(
    body: dict[str, Any],
    token: Annotated[str | None, Header(alias="X-TraceScope-Internal-Token")] = None,
) -> dict[str, Any]:
    require_internal_token(token)
    return {"accepted": AgentStatsRepository().upsert(body)}


@router.get("/agent-stats/latest")
async def agent_latest(
    node: str | None = None,
    instance_id: str | None = None,
    token: Annotated[str | None, Header(alias="X-TraceScope-Internal-Token")] = None,
) -> dict[str, Any]:
    require_internal_token(token)
    items = AgentStatsRepository().get_latest(node, instance_id)
    return {"items": items, "count": len(items)}


@router.get("/agent-stats/history")
async def agent_history(
    node: str,
    limit: int = Query(120, ge=1, le=2880),
    instance_id: str | None = None,
    token: Annotated[str | None, Header(alias="X-TraceScope-Internal-Token")] = None,
) -> dict[str, Any]:
    require_internal_token(token)
    items = AgentStatsRepository().get_history(node, limit, instance_id)
    return {"items": items, "count": len(items)}


@router.delete("/agent-stats")
async def delete_agent(
    node: str,
    instance_id: str | None = None,
    token: Annotated[str | None, Header(alias="X-TraceScope-Internal-Token")] = None,
) -> dict[str, Any]:
    require_internal_token(token)
    return AgentStatsRepository().delete_instance(node, instance_id)
