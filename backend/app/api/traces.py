from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from backend.app.repositories.trace_repository import TraceRepository

router = APIRouter(prefix="/api/v1", tags=["traces"])

@router.get("/traces")
async def list_traces(
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
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
) -> Dict[str, Any]:
    start_ms = from_time if (from_time and from_time > 10_000_000_000) else (from_time * 1000 if from_time else None)
    end_ms = to_time if (to_time and to_time > 10_000_000_000) else (to_time * 1000 if to_time else None)

    repo = TraceRepository()
    rows = repo.list_traces(
        start_ms=start_ms, end_ms=end_ms, service=service, caller=caller,
        target=target, principal=principal, operation=operation, source_ip=source_ip, status=status,
        trace_id=trace_id, limit=limit, offset=offset
    )
    return {"items": rows, "count": len(rows)}

@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str) -> Dict[str, Any]:
    repo = TraceRepository()
    res = repo.get_trace(trace_id)
    if not res:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = res.get("spans", [])
    # Reconstruct trace graph / hierarchy
    span_ids = {s["span_id"] for s in spans}
    for s in spans:
        p = s.get("parent_span_id")
        s["is_root"] = (p is None or p == "" or p not in span_ids)

    res["waterfall"] = spans
    res["items"] = spans
    res["partial"] = len(spans) == 1000
    return res
