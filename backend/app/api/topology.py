from __future__ import annotations
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter, Query
from backend.app.repositories.topology_repository import TopologyRepository
from backend.app.repositories.db_context import get_connection

router = APIRouter(prefix="/api/v1", tags=["topology"])

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

@router.get("/topology")
async def get_topology(
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, Any]:
    start_sec, end_sec = _time_window(from_time, to_time)
    repo = TopologyRepository()
    return repo.get_topology(start_sec, end_sec)

@router.get("/topology/service/{service}")
async def get_service_topology(
    service: str,
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
) -> Dict[str, Any]:
    start_sec, end_sec = _time_window(from_time, to_time)
    repo = TopologyRepository()
    full_top = repo.get_topology(start_sec, end_sec)

    # filter to connected nodes & edges
    connected_edges = [
        e for e in full_top.get("edges", [])
        if e.get("caller_service") == service or e.get("target_service") == service
    ]
    connected_node_names = {service}
    for e in connected_edges:
        connected_node_names.add(e.get("caller_service"))
        connected_node_names.add(e.get("target_service"))

    connected_nodes = [n for n in full_top.get("nodes", []) if n.get("name") in connected_node_names]
    return {"nodes": connected_nodes, "edges": connected_edges}
