"""Expose derived user intelligence without leaking authentication source material."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.app.repositories.user_repository import UserRepository
from backend.app.security import require_api_key


router = APIRouter(prefix="/api/v1", tags=["user-intelligence"])


def _timestamp(value: str | int | None) -> int | None:
    if value is None or value == "": return None
    if isinstance(value, int) or str(value).isdigit():
        number = int(value)
        return number if number > 10_000_000_000 else number * 1000
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)


def _window(from_time=None, to_time=None, start=None, end=None):
    try: return _timestamp(from_time or start), _timestamp(to_time or end)
    except (ValueError, TypeError): raise HTTPException(422, "Invalid time range") from None


class ChangeUpdate(BaseModel):
    status: Literal["new", "reviewed", "expected", "ignored"]


class ChangeReview(BaseModel):
    action: Literal["expected", "investigate", "resolve", "data_quality"]
    scope: Optional[str] = None
    reason: Optional[str] = None
    operator: Optional[str] = "operator"
    expires_at: Optional[int] = None


class IncidentUpdate(BaseModel):
    status: Optional[Literal["open", "investigating", "resolved", "suppressed", "accepted"]] = None
    review_notes: Optional[str] = None
    reviewed_by: Optional[str] = "operator"


class PrincipalUpdate(BaseModel):
    principal_type: Literal["unknown", "human", "service_account", "system_account", "shared_credential", "integration_account"]


@router.get("/users")
async def users(from_time: Optional[str] = Query(None, alias="from"), to_time: Optional[str] = Query(None, alias="to"),
                start: Optional[str] = None, end: Optional[str] = None, environment: Optional[str] = None,
                q: Optional[str] = None, active: Optional[str] = None, caller: Optional[str] = None,
                target: Optional[str] = None, source_ip: Optional[str] = None, behavior_level: Optional[str] = None,
                has_recent_changes: Optional[bool] = None, first_from: Optional[int] = None,
                first_to: Optional[int] = None, last_from: Optional[int] = None, last_to: Optional[int] = None,
                sort: str = "most_active", limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                include_anonymous: bool = Query(False)):
    start_ms, end_ms = _window(from_time,to_time,start,end)
    return UserRepository().list_users(start_ms=start_ms,end_ms=end_ms,search=q,active=active,caller=caller,
        target=target,source_ip=source_ip,behavior_level=behavior_level,has_changes=has_recent_changes,
        first_from=first_from,first_to=first_to,last_from=last_from,last_to=last_to,sort=sort,
        environment=environment,limit=limit,offset=offset,include_anonymous=include_anonymous)


@router.get("/users/summary")
async def users_summary(from_time: Optional[str] = Query(None, alias="from"), to_time: Optional[str] = Query(None, alias="to"),
                        start: Optional[str] = None, end: Optional[str] = None):
    start_ms,end_ms = _window(from_time,to_time,start,end)
    return UserRepository().summary(start_ms,end_ms)


@router.get("/unknown-users")
@router.get("/users/unknown-traffic")
async def unknown_users(from_time: Optional[str] = Query(None, alias="from"), to_time: Optional[str] = Query(None, alias="to"),
                        start: Optional[str] = None, end: Optional[str] = None, limit: int = Query(50, ge=1, le=200)):
    start_ms, end_ms = _window(from_time, to_time, start, end)
    return UserRepository().unknown_users_analytics(start_ms=start_ms, end_ms=end_ms, limit=limit)


@router.get("/users/{principal}")
async def user_detail(principal: str, from_time: Optional[str] = Query(None, alias="from"),
                      to_time: Optional[str] = Query(None, alias="to"), start: Optional[str] = None,
                      end: Optional[str] = None):
    start_ms,end_ms = _window(from_time,to_time,start,end)
    result = UserRepository().profile(principal,start_ms,end_ms)
    if not result: raise HTTPException(404,"Principal not found")
    return result


@router.patch("/users/{principal}", dependencies=[Depends(require_api_key)])
async def update_user(principal: str, body: PrincipalUpdate):
    if not UserRepository().update_principal_type(principal,body.principal_type):
        raise HTTPException(404,"Principal not found")
    return {"principal_name":principal,"principal_type":body.principal_type}


@router.get("/users/{principal}/summary")
async def user_summary(principal: str, from_time: Optional[str] = Query(None, alias="from"),
                       to_time: Optional[str] = Query(None, alias="to"), start: Optional[str] = None,
                       end: Optional[str] = None):
    start_ms,end_ms = _window(from_time,to_time,start,end)
    result = UserRepository().profile(principal,start_ms,end_ms)
    if not result: raise HTTPException(404,"Principal not found")
    return {key:result[key] for key in ("principal_name","principal_type","status","first_seen","last_seen",
        "total_requests","unique_callers","unique_sources","unique_targets","unique_operations",
        "behavior_score","behavior_level","typical_active_window","window")}


def _dimension_route(dimension: str):
    async def endpoint(principal: str, from_time: Optional[str] = Query(None, alias="from"),
                       to_time: Optional[str] = Query(None, alias="to"), start: Optional[str] = None,
                       end: Optional[str] = None):
        start_ms,end_ms = _window(from_time,to_time,start,end)
        return {"items":UserRepository().relationships(principal,dimension,start_ms,end_ms)}
    return endpoint


router.add_api_route("/users/{principal}/callers",_dimension_route("callers"),methods=["GET"])
router.add_api_route("/users/{principal}/sources",_dimension_route("sources"),methods=["GET"])
router.add_api_route("/users/{principal}/targets",_dimension_route("targets"),methods=["GET"])
router.add_api_route("/users/{principal}/operations",_dimension_route("operations"),methods=["GET"])


@router.get("/users/{principal}/timeline")
async def user_timeline(principal: str, from_time: Optional[str] = Query(None, alias="from"),
                        to_time: Optional[str] = Query(None, alias="to"), start: Optional[str] = None,
                        end: Optional[str] = None, kind: Optional[str] = None, limit: int = Query(100,ge=1,le=500)):
    start_ms,end_ms = _window(from_time,to_time,start,end)
    return {"items":UserRepository().timeline(principal,start_ms,end_ms,kind,limit)}


@router.get("/users/{principal}/changes")
async def user_changes(principal: str, from_time: Optional[str] = Query(None, alias="from"),
                       to_time: Optional[str] = Query(None, alias="to"), start: Optional[str] = None,
                       end: Optional[str] = None, limit: int = Query(100,ge=1,le=500)):
    start_ms,end_ms = _window(from_time,to_time,start,end)
    return UserRepository().list_changes(principal=principal,start_ms=start_ms,end_ms=end_ms,limit=limit)


@router.get("/user-changes")
async def changes(principal: Optional[str] = None, change_type: Optional[str] = None,
                  severity: Optional[str] = None, caller: Optional[str] = None, target: Optional[str] = None,
                  operation: Optional[str] = None, source_ip: Optional[str] = None, status: Optional[str] = None,
                  from_time: Optional[str] = Query(None,alias="from"), to_time: Optional[str] = Query(None,alias="to"),
                  start: Optional[str] = None, end: Optional[str] = None,
                  limit: int = Query(100,ge=1,le=500), offset: int = Query(0,ge=0)):
    start_ms,end_ms = _window(from_time,to_time,start,end)
    return UserRepository().list_changes(principal=principal,change_type=change_type,severity=severity,
        caller=caller,target=target,operation=operation,source_ip=source_ip,status=status,
        start_ms=start_ms,end_ms=end_ms,limit=limit,offset=offset)


@router.get("/user-changes/{change_id}")
async def change_detail(change_id: int):
    result = UserRepository().get_change(change_id)
    if not result:
        raise HTTPException(404, "User change not found")
    return result


@router.patch("/user-changes/{change_id}", dependencies=[Depends(require_api_key)])
async def update_change(change_id: int, body: ChangeUpdate):
    result = UserRepository().update_change(change_id,body.status)
    if not result: raise HTTPException(404,"User change not found")
    return result


@router.post("/user-changes/{change_id}/review")
async def review_change(change_id: int, body: ChangeReview):
    result = UserRepository().review_change(
        change_id, action=body.action, scope=body.scope,
        reason=body.reason, operator=body.operator or "operator",
        expires_at=body.expires_at
    )
    if not result: raise HTTPException(404, "User change not found")
    return result


@router.get("/incidents")
async def list_incidents(
    principal_id: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    start_ms, end_ms = _window(from_time, to_time, start, end)
    return UserRepository().list_incidents(
        principal_id=principal_id, status=status, priority=priority,
        category=category, start_ms=start_ms, end_ms=end_ms,
        limit=limit, offset=offset
    )


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    inc = UserRepository().get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "Incident not found")
    return inc


@router.get("/user-graph")
async def user_graph(principal: Optional[str] = None, service: Optional[str] = None,
                     from_time: Optional[str] = Query(None,alias="from"), to_time: Optional[str] = Query(None,alias="to"),
                     start: Optional[str] = None, end: Optional[str] = None, limit: int = Query(300,ge=1,le=1000)):
    start_ms,end_ms = _window(from_time,to_time,start,end)
    return UserRepository().graph(principal,service,start_ms,end_ms,limit)


@router.get("/user-graph/{principal}")
async def principal_graph(principal: str, from_time: Optional[str] = Query(None,alias="from"),
                          to_time: Optional[str] = Query(None,alias="to"), start: Optional[str] = None,
                          end: Optional[str] = None):
    start_ms,end_ms = _window(from_time,to_time,start,end)
    return UserRepository().graph(principal,None,start_ms,end_ms)


@router.get("/user-analytics")
async def user_analytics(): return UserRepository().analytics()


@router.get("/services/{service}/users")
async def service_users(service: str, from_time: Optional[str] = Query(None,alias="from"),
                        to_time: Optional[str] = Query(None,alias="to"), start: Optional[str] = None,
                        end: Optional[str] = None):
    start_ms,end_ms = _window(from_time,to_time,start,end)
    return {"items":UserRepository().service_users(service,start_ms,end_ms)}


@router.get("/anomalies/{anomaly_id}/users")
def anomaly_users(anomaly_id: int):
    result=UserRepository().anomaly_users(anomaly_id)
    if not result: raise HTTPException(404,"Anomaly not found")
    return result


@router.get("/users/{principal}/performance")
def user_performance(
    principal: str,
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    bucket: int = Query(300, ge=60, le=3600),
    source_ip: Optional[str] = Query(None),
):
    start_ms, end_ms = _window(from_time, to_time, start, end)
    return UserRepository().performance(principal, start_ms=start_ms, end_ms=end_ms, bucket_size=bucket, source_ip=source_ip)


@router.get("/users/{principal}/investigations")
def user_investigations(
    principal: str,
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    start_ms, end_ms = _window(from_time, to_time, start, end)
    return {"principal_name": principal, "items": UserRepository().investigations(principal, start_ms=start_ms, end_ms=end_ms)}


@router.get("/users/{principal}/topology")
def user_topology_endpoint(
    principal: str,
    from_time: Optional[str] = Query(None, alias="from"),
    to_time: Optional[str] = Query(None, alias="to"),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    start_ms, end_ms = _window(from_time, to_time, start, end)
    return UserRepository().user_topology(principal, start_ms=start_ms, end_ms=end_ms)
