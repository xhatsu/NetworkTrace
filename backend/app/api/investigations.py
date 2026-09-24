"""Authenticated, explicit-request investigation API."""
from __future__ import annotations

import hmac
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.config import settings
from backend.app.models.investigation import (
    AnomalyEventRef, IncidentRef, InvestigationCreate, PrincipalChangeEventRef,
    FindingRef, finding_key,
)
from backend.app.services.investigation import InvestigationRunner, InvestigationServiceError
from backend.app.services.investigation_evidence import SourceError


router = APIRouter(prefix="/api/v1/investigations", tags=["investigations"])
_TERMINAL = {"succeeded", "failed", "timed_out", "canceled", "source_changed", "source_closed", "source_superseded", "source_stale"}


def _runner(request: Request) -> InvestigationRunner:
    runner = getattr(request.app.state, "investigation_runner", None)
    if runner is None:
        runner = InvestigationRunner()
    return runner


async def investigation_auth(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    if not settings.llm_investigation_enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    # If an operator API key is configured, enforce X-API-Key validation;
    # otherwise allow open access consistent with the rest of the dashboard API.
    if settings.api_key:
        if x_api_key is None or not hmac.compare_digest(x_api_key, settings.api_key):
            raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Valid X-API-Key required"})



router.dependencies.append(Depends(investigation_auth))


def _error(exc: InvestigationServiceError) -> JSONResponse:
    mapping = {"source_not_found": 404, "run_not_found": 404, "capacity": 429, "rate_limited": 429,
               "store_unavailable": 503, "owner_unavailable": 503, "store_schema_unavailable": 503,
               "provider_unconfigured": 503, "source_changed": 409, "source_closed": 409,
               "source_superseded": 409, "source_stale": 409, "insufficient_scope": 409,
               "retry_not_allowed": 409, "invalid_source": 422, "source_too_large": 422,
               "owner_not_acknowledged": 503, "owner_proxy_forbidden": 503,
               "invalid_response_mode": 503, "invalid_provider_context": 503}
    detail = {"code": exc.code, "message": str(exc)}
    if exc.expected_version is not None:
        detail["expected_version"] = exc.expected_version
    if exc.current_version is not None:
        detail["current_version"] = exc.current_version
    if exc.run_id:
        detail["existing_investigation_id"] = exc.run_id
    headers = {"Retry-After": "1"} if exc.code in {"capacity", "rate_limited"} else None
    return JSONResponse(status_code=mapping.get(exc.code, 422), content={"detail": detail}, headers=headers)


def _ref(kind: str, identifier: str) -> FindingRef:
    if kind == "anomaly_event": return AnomalyEventRef(kind=kind, anomaly_event_id=identifier)
    if kind == "principal_change_event": return PrincipalChangeEventRef(kind=kind, principal_change_event_id=identifier)
    if kind == "incident": return IncidentRef(kind=kind, incident_id=identifier)
    raise ValueError("unsupported finding kind")


def _operator_view(row: dict[str, Any]) -> dict[str, Any]:
    """Build trusted operator navigation from the immutable server snapshot."""
    snapshot = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
    dimensions = snapshot.get("dimensions") if isinstance(snapshot.get("dimensions"), dict) else {}
    facts = snapshot.get("source_facts") if isinstance(snapshot.get("source_facts"), dict) else {}
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    hypotheses = result.get("hypotheses") if isinstance(result.get("hypotheses"), list) else []
    hypothesis = hypotheses[0] if hypotheses and isinstance(hypotheses[0], dict) else {}

    def service_ref(name: Any) -> dict[str, str] | None:
        return {"kind": "service", "name": name} if isinstance(name, str) and name.strip() else None

    caller = service_ref(dimensions.get("caller_service"))
    target = service_ref(dimensions.get("target_service"))
    principal = dimensions.get("principal_name")
    user = ({"kind": "user", "principal": principal}
            if isinstance(principal, str) and principal.strip() and principal not in {"unknown", "-anonymous-"} else None)
    operation = dimensions.get("operation")
    api = ({"kind": "api", "service": target["name"], "operation": operation}
           if target and isinstance(operation, str) and operation.strip() else None)

    relationship = []
    for value, entity in ((dimensions.get("caller_service"), caller), (dimensions.get("target_service"), target), (operation, api)):
        if entity and isinstance(value, str) and value.strip():
            relationship.append({"text": value, "entity": entity})
    evidence = []
    entities = [entity for entity in (caller, target, api, user) if entity]
    if relationship or user:
        evidence.append({
            "label": "Observed relationship and identity" if user else "Observed relationship",
            "relationship": relationship,
            "entities": entities,
        })

    baseline, current = facts.get("baseline"), facts.get("current")
    if isinstance(baseline, (int, float)) and not isinstance(baseline, bool) and isinstance(current, (int, float)) and not isinstance(current, bool):
        source_type = str(facts.get("type") or "").lower()
        if "latency" in source_type:
            label, unit = "P95 latency", " ms"
        elif "error" in source_type:
            label, unit = "Error rate", "%"
        elif any(token in source_type for token in ("traffic", "spike", "drop")):
            label, unit = "TPS", ""
        else:
            label, unit = "Observed metric", ""
        if unit == "%":
            value = f"{float(baseline) * 100:.1f}% → {float(current) * 100:.1f}%"
        else:
            value = f"{float(baseline):,.2f}{unit} → {float(current):,.2f}{unit}"
        evidence.append({"label": label, "value": value})

    observed_at = next((facts.get(key) for key in ("detected_at", "first_seen", "first_observed", "started_at")
                        if isinstance(facts.get(key), int) and facts.get(key) > 0), None)
    if observed_at is not None:
        evidence.append({"label": "First observed", "timestamp_ms": observed_at})

    next_actions = []
    if api:
        next_actions.append({"label": "View API", "entity": api})
    if target or caller:
        next_actions.append({"label": "View Service", "entity": target or caller})
    if user:
        next_actions.append({"label": "View User", "entity": user})
    trace_filters = {key: dimensions[key] for key in ("principal_name", "target_service", "operation")
                     if isinstance(dimensions.get(key), str) and dimensions[key].strip()}
    if trace_filters:
        params = {"principal_name": "principal", "target_service": "service", "operation": "operation"}
        next_actions.append({"label": "View related traces", "href": "/traces?" + urlencode({params[key]: value for key, value in trace_filters.items()})})

    state = str(row.get("state") or "")
    status = "done" if state == "succeeded" else "failed" if state in _TERMINAL else "running"
    assessment = result.get("assessment")
    summary = hypothesis.get("statement")
    if not summary:
        summary = "There is not enough evidence to produce a reliable explanation." if assessment == "insufficient_evidence" else "Investigation completed using the attached telemetry evidence."
    limitations = list(snapshot.get("limitations") or [])
    for missing in result.get("missing_evidence") or []:
        if isinstance(missing, dict) and isinstance(missing.get("explanation"), str) and missing["explanation"] not in limitations:
            limitations.append(missing["explanation"])
    return {
        "status": status,
        "summary": summary,
        "confidence": hypothesis.get("confidence"),
        "evidence": evidence,
        "next_actions": next_actions,
        "limitations": limitations,
    }


def _public(row: dict[str, Any]) -> dict[str, Any]:
    result = {key: row.get(key) for key in ("id", "retry_index", "retry_of", "finding_kind", "finding_id", "source_version", "snapshot_schema_version", "prompt_version", "result_schema_version", "policy_version", "provider", "configured_model", "reported_model", "state", "state_version", "cancel_requested", "created_at_ms", "updated_at_ms", "started_at_ms", "finished_at_ms", "deadline_ms", "failure_code")}
    result["snapshot"] = row.get("snapshot", {})
    result["evidence_manifest"] = {"digest": row.get("evidence_digest"), **({"bundle": row.get("evidence", {})} if row.get("evidence") else {})}
    result["deterministic_summary"] = row.get("deterministic_summary", {})
    result["result"] = row.get("result")
    result["operator_view"] = _operator_view(row)
    metadata = row.get("metadata", {})
    result["metadata"] = metadata if isinstance(metadata, dict) else {}
    result["source_check"] = row.get("source_check")
    if row.get("effective_status") is not None:
        result["effective_status"] = row["effective_status"]
    return result


@router.get("/source")
async def source_snapshot(request: Request, kind: str = Query(...), id: str = Query(...)) -> dict[str, Any]:
    try:
        ref = _ref(kind, id)
        runner = _runner(request)
        snapshot, eligibility, reason = await runner.resolve_source(ref)
        latest = await runner.history(ref, 1)
        latest_id = latest[0].get("id") if latest else None
        return {"snapshot": snapshot.model_dump(), "eligibility": {"status": eligibility, "reason": reason}, "latest_investigation_id": latest_id}
    except SourceError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
    except (ValueError, InvestigationServiceError) as exc:
        if isinstance(exc, InvestigationServiceError):
            return _error(exc)
        raise HTTPException(status_code=422, detail={"code": "invalid_source", "message": "invalid finding reference"}) from exc


@router.post("", status_code=202)
async def create_investigation(request: Request, raw_payload: Any = Body(...)) -> JSONResponse:
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > 16 * 1024):
        return JSONResponse(status_code=422, content={"detail": {"code": "request_too_large", "message": "investigation request exceeds 16 KiB"}})
    try:
        if len(await request.body()) > 16 * 1024:
            return JSONResponse(status_code=422, content={"detail": {"code": "request_too_large", "message": "investigation request exceeds 16 KiB"}})
        payload = InvestigationCreate.model_validate(raw_payload)
        row, reused, code = await _runner(request).submit(payload.finding, payload.source_version, payload.retry_of)
        run_id = str(row["id"])
        return JSONResponse(status_code=200 if reused else code, content={"id": run_id, "status": row.get("state"), "reused": reused, "source_version": row["source_version"], "status_url": "/api/v1/investigations/" + run_id})
    except ValidationError:
        return JSONResponse(status_code=422, content={"detail": {"code": "invalid_request", "message": "invalid investigation request"}})
    except SourceError as exc:
        return JSONResponse(status_code=422, content={"detail": {"code": exc.code, "message": str(exc)}})
    except InvestigationServiceError as exc:
        return _error(exc)


@router.get("", response_model=None)
async def investigation_history(request: Request, kind: str = Query(...), id: str = Query(...), limit: int = Query(5, ge=1, le=10)) -> dict[str, Any] | JSONResponse:
    try:
        ref = _ref(kind, id)
        runner = _runner(request)
        await runner.resolve_source(ref)
        return {"items": [_public(row) for row in await runner.history(ref, limit)], "limit": limit, "finding": {"kind": kind, "id": id}}
    except (ValueError, InvestigationServiceError) as exc:
        if isinstance(exc, InvestigationServiceError): return _error(exc)
        return JSONResponse(status_code=422, content={"detail": {"code": "invalid_source", "message": "invalid finding reference"}})


@router.post("/{run_id}/cancel")
async def cancel_investigation(request: Request, run_id: UUID) -> JSONResponse:
    try:
        row = await _runner(request).cancel(run_id)
        return JSONResponse(status_code=202 if row.get("state") not in _TERMINAL else 200, content={"id": str(row["id"]), "status": row.get("state"), "cancel_requested": bool(row.get("cancel_requested"))})
    except InvestigationServiceError as exc:
        return _error(exc)


@router.get("/{run_id}")
async def get_investigation(request: Request, run_id: UUID) -> JSONResponse:
    try:
        row = await _runner(request).get(run_id)
        if row is None:
            return JSONResponse(status_code=404, content={"detail": {"code": "run_not_found", "message": "investigation was not found"}})
        return JSONResponse(content=_public(row))
    except InvestigationServiceError as exc:
        return _error(exc)
