"""Read identity behavior from normalized evidence rather than raw credentials."""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from backend.app.repositories.principal_repository import PrincipalRepository
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.db_context import get_connection

router = APIRouter(prefix="/api/v1", tags=["principals"])

def _time_window(from_t: Optional[int], to_t: Optional[int]) -> tuple[int, int]:
    if from_t and to_t:
        start_sec = from_t if from_t < 10_000_000_000 else int(from_t / 1000)
        end_sec = to_t if to_t < 10_000_000_000 else int(to_t / 1000)
        return start_sec, end_sec
    with get_connection() as db:
        min_max = db.execute("SELECT MIN(bucket_start), MAX(bucket_start) FROM metric_buckets").fetchone()
        if min_max and min_max[1]:
            return max(min_max[0], min_max[1] - 86400), min_max[1] + 300
    now = int(time.time())
    return now - 3600, now

@router.get("/principals")
async def list_principals(
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
    limit: int = 100
) -> Dict[str, Any]:
    start_sec, end_sec = _time_window(from_time, to_time)
    repo = PrincipalRepository()
    rows = repo.list_principals(start_sec, end_sec, limit=limit)
    return {"items": rows, "count": len(rows)}

@router.get("/principals/{principal}")
async def get_principal_profile(
    principal: str,
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to")
) -> Dict[str, Any]:
    start_sec, end_sec = _time_window(from_time, to_time)
    repo = PrincipalRepository()
    prof = repo.get_principal_profile(principal, start_sec, end_sec)
    if not prof:
        raise HTTPException(status_code=404, detail="Principal not found")
    hours = [{"hour_of_day": int(h.get("hour", 0)), "requests": int(h.get("requests", 0))} for h in (prof.get("active_hours") or [])]
    prof["hourly_profile"] = hours
    prof["active_hours"] = hours
    prof["targets"] = prof.get("targets") or []
    prof["operations"] = prof.get("operations") or []
    prof["callers"] = prof.get("callers") or []
    return prof

@router.get("/principals/{principal}/metrics")
async def get_principal_metrics(
    principal: str,
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
    bucket: int = 60
) -> List[Dict[str, Any]]:
    start_sec, end_sec = _time_window(from_time, to_time)
    agg_repo = AggregateRepository()
    return agg_repo.query_series(start_sec, end_sec, bucket_size=bucket, principal=principal)

@router.get("/principals/{principal}/relationships")
async def get_principal_relationships(
    principal: str,
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to")
) -> List[Dict[str, Any]]:
    start_sec, end_sec = _time_window(from_time, to_time)
    with get_connection() as db:
        rows = [dict(r) for r in db.execute("""
            SELECT
              caller_service,
              target_service,
              SUM(request_count) as requests,
              ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) as error_rate,
              ROUND(MAX(latency_p95), 2) as p95_latency
            FROM metric_buckets
            WHERE principal_name = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
            GROUP BY caller_service, target_service
            ORDER BY requests DESC
        """, (principal, start_sec, end_sec)).fetchall()]
        return rows
