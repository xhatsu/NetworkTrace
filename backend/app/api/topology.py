"""Return dependency graphs from materialized edges for bounded interactive reads."""
from __future__ import annotations
import time
from datetime import datetime
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Query
from backend.app.repositories.topology_repository import TopologyRepository
from backend.app.repositories.interactive_topology_repository import InteractiveTopologyRepository
from backend.app.repositories.db_context import get_connection
from backend.app.models.interactive_topology import (
    PrincipalIpPageResponse,
    ServiceTopologyResponse,
    TopologyDetailResponse,
    TopologyExpansionResponse,
)

router = APIRouter(prefix="/api/v1", tags=["topology"])


def _parse_ms(value: Optional[str | int]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        number = int(value)
        return number * 1000 if number < 10_000_000_000 else number
    except (TypeError, ValueError):
        try:
            text = str(value).replace("Z", "+00:00")
            return int(datetime.fromisoformat(text).timestamp() * 1000)
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(status_code=422, detail="time must be epoch milliseconds or ISO-8601") from None


def _interactive_window(
    window: str,
    from_time: Optional[str | int],
    to_time: Optional[str | int],
) -> tuple[InteractiveTopologyRepository, Dict[str, Any]]:
    repo = InteractiveTopologyRepository()
    try:
        resolved = repo.resolve_window(window, _parse_ms(from_time), _parse_ms(to_time))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return repo, resolved

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


# ---------------------------------------------------------------------------
# Interactive service -> API -> principal topology contracts
# ---------------------------------------------------------------------------


@router.get("/topology/search")
def interactive_topology_search(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(20, ge=1, le=50),
    window: str = Query("7d"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.search_entities(q, resolved, limit)


@router.get("/topology/services", response_model=ServiceTopologyResponse)
def interactive_service_graph(
    window: str = Query("5m"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.service_graph(resolved)


@router.get("/topology/services/{service}/apis", response_model=TopologyExpansionResponse)
def interactive_service_apis(
    service: str,
    window: str = Query("5m"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.service_apis(service, resolved)


@router.get("/topology/services/{service}/api-connections", response_model=ServiceTopologyResponse)
def interactive_api_connections(
    service: str,
    api: str = Query(..., min_length=1, max_length=500),
    window: str = Query("5m"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.api_connections(service, api, resolved)


@router.get("/topology/services/{service}/apis/{api:path}/principals", response_model=TopologyExpansionResponse)
def interactive_api_principals(
    service: str,
    api: str,
    window: str = Query("5m"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.api_principals(service, api, resolved)


@router.get("/topology/services/{service}/metrics", response_model=TopologyDetailResponse)
def interactive_service_metrics(
    service: str,
    window: str = Query("5m"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.service_metrics(service, resolved)


@router.get("/topology/apis/{api:path}/metrics", response_model=TopologyDetailResponse)
def interactive_api_metrics(
    api: str,
    service: Optional[str] = Query(None),
    window: str = Query("5m"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.api_metrics(api, resolved, service)


@router.get("/topology/principals/{principal}/metrics", response_model=TopologyDetailResponse)
def interactive_principal_metrics(
    principal: str,
    window: str = Query("5m"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.principal_metrics(principal, resolved)


@router.get("/topology/principals/{principal}/services", response_model=TopologyExpansionResponse)
def interactive_principal_services(
    principal: str,
    window: str = Query("5m"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.principal_services(principal, resolved)


@router.get("/topology/principals/{principal}/services/{service}/apis", response_model=TopologyExpansionResponse)
def interactive_principal_service_apis(
    principal: str,
    service: str,
    window: str = Query("5m"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    return repo.principal_service_apis(principal, service, resolved)


@router.get("/topology/principals/{principal}/ips", response_model=PrincipalIpPageResponse)
def interactive_principal_ips(
    principal: str,
    service: Optional[str] = Query(None, max_length=200),
    api: Optional[str] = Query(None, max_length=500),
    window: str = Query("1h"),
    page_size: int = Query(50, ge=1, le=500),
    cursor: Optional[str] = Query(None, max_length=1024),
    filter_name: str = Query("all", alias="filter"),
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    repo, resolved = _interactive_window(window, from_time, to_time)
    try:
        return repo.principal_ips(principal, resolved, page_size, cursor, service, api, filter_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
