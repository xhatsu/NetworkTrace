from __future__ import annotations
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter, Query
from backend.app.services.blast_radius import calculate_blast_radius
from backend.app.repositories.db_context import get_connection

router = APIRouter(prefix="/api/v1", tags=["blast-radius"])

@router.get("/blast-radius/{service}")
async def get_blast_radius(
    service: str,
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to")
) -> Dict[str, Any]:
    if from_time and to_time:
        start_sec = from_time if from_time < 10_000_000_000 else int(from_time / 1000)
        end_sec = to_time if to_time < 10_000_000_000 else int(to_time / 1000)
    else:
        with get_connection() as db:
            max_b = db.execute("SELECT MAX(bucket_start) FROM metric_buckets").fetchone()[0]
            if max_b:
                end_sec = max_b + 300
                start_sec = max_b - 3600
            else:
                end_sec = int(time.time())
                start_sec = end_sec - 3600

    return calculate_blast_radius(service, start_sec, end_sec)
