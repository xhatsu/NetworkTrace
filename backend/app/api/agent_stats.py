"""POST /api/agent/stats — Oldkernel Agent Statistics Protocol v1 receiver.

Spec: ~/Viettel/NetworkTracing/oldkernel/AGENT-STATS-PROTOCOL.md

Validation rules (from spec):
  - Content-Type: application/json
  - Body must be valid JSON
  - Max encoded body: 16 KiB
  - schema_version must be 1
  - type must be "agent_stats"
  - Required top-level fields: node, instance_id, sequence, observed_at,
    window_seconds, status
  - status must be "ok" or "degraded"
  - reasons must be a list of bounded enum values only
  - Duplicate (node, instance_id, sequence) -> HTTP 200, accepted: false
  - Invalid document -> HTTP 400

The receiver validates before persistence so independently scaled fleet agents
cannot turn malformed health data into durable ClickHouse cardinality pressure.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.app.repositories.agent_stats_repository import AgentStatsRepository
from backend.app.services.storage_owner_client import StorageOwnerError, storage_owner_client

router = APIRouter(tags=["agent"])

# Bound untrusted agent payloads before JSON parsing to protect a high-fan-in receiver.
_MAX_BODY_BYTES = 16 * 1024  # 16 KiB per spec

_VALID_STATUSES = {"ok", "degraded"}
_VALID_REASONS = {
    "kernel_drop",
    "ship_drop",
    "hub_unreachable",
    "queue_pressure",
    "resource_pressure",
    "invalid_ring_frame",
}

_REQUIRED_FIELDS = ("node", "instance_id", "sequence", "observed_at", "window_seconds", "status")


def _remote_error_response(exc: StorageOwnerError) -> JSONResponse:
    headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)


def _validate(body: Any) -> str | None:
    """Return an error string if invalid, else None."""
    if not isinstance(body, dict):
        return "Body must be a JSON object"

    if body.get("schema_version") != 1:
        return "schema_version must be 1"
    if body.get("type") != "agent_stats":
        return "type must be 'agent_stats'"

    for field in _REQUIRED_FIELDS:
        if field not in body:
            return "Missing required field: {}".format(field)

    if not isinstance(body["node"], str) or not body["node"]:
        return "node must be a non-empty string"
    if not isinstance(body["instance_id"], str) or not body["instance_id"]:
        return "instance_id must be a non-empty string"
    if not isinstance(body["sequence"], int) or body["sequence"] < 0:
        return "sequence must be a non-negative integer"
    if not isinstance(body["observed_at"], (int, float)):
        return "observed_at must be a number (Unix seconds)"
    if not isinstance(body["window_seconds"], (int, float)) or body["window_seconds"] <= 0:
        return "window_seconds must be a positive number"

    status = body.get("status")
    if status not in _VALID_STATUSES:
        return "status must be 'ok' or 'degraded'"

    reasons = body.get("reasons")
    if reasons is not None:
        if not isinstance(reasons, list):
            return "reasons must be an array"
        for r in reasons:
            if r not in _VALID_REASONS:
                return "reasons contains invalid value: {}".format(r)

    return None


@router.post("/api/agent/stats")
async def agent_stats(request: Request) -> Dict[str, Any]:
    """Accept an agent health sample per AGENT-STATS-PROTOCOL v1."""
    # --- size guard ---
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_BODY_BYTES:
                return JSONResponse(
                    {"ok": False, "error": "Payload exceeds 16 KiB limit"},
                    status_code=400,
                )
        except ValueError:
            pass  # malformed header; continue and check actual body length

    raw_body = await request.body()
    if len(raw_body) > _MAX_BODY_BYTES:
        return JSONResponse(
            {"ok": False, "error": "Payload exceeds 16 KiB limit"},
            status_code=400,
        )
    if not raw_body:
        return JSONResponse({"ok": False, "error": "Empty body"}, status_code=400)

    # --- parse ---
    try:
        import json
        body = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"ok": False, "error": "Body must be valid JSON"}, status_code=400)

    # --- validate ---
    err = _validate(body)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)

    try:
        # The optional internal boundary retains role isolation without changing this public protocol.
        if storage_owner_client.enabled:
            accepted = bool((await storage_owner_client.store_agent_sample(body))["accepted"])
        else:
            accepted = await run_in_threadpool(AgentStatsRepository().upsert, body)
    except StorageOwnerError as exc:
        return _remote_error_response(exc)

    return {
        "ok": True,
        "accepted": accepted,
        "schema_version": 1,
        "server_time": int(time.time()),
    }


@router.get("/api/agent/stats")
async def agent_stats_latest(node: str | None = None) -> Dict[str, Any]:
    """Return the latest agent health sample for each known node (or a specific node)."""
    try:
        items = (
            await storage_owner_client.agent_latest(node)
            if storage_owner_client.enabled
            else await run_in_threadpool(AgentStatsRepository().get_latest, node)
        )
    except StorageOwnerError as exc:
        return _remote_error_response(exc)
    return {"items": items, "count": len(items)}


@router.get("/api/agent/stats/{node}/history")
async def agent_stats_history(node: str, limit: int = 120, instance_id: str | None = None) -> Dict[str, Any]:
    """Return up to `limit` recent history samples for a specific node (and optional instance_id)."""
    if limit < 1:
        limit = 1
    if limit > 2880:
        limit = 2880
    try:
        items = (
            await storage_owner_client.agent_history(node, limit, instance_id)
            if storage_owner_client.enabled
            else await run_in_threadpool(AgentStatsRepository().get_history, node, limit, instance_id)
        )
    except StorageOwnerError as exc:
        return _remote_error_response(exc)
    return {"node": node, "instance_id": instance_id, "items": items, "count": len(items)}


@router.get("/api/agent/stats/{node}")
async def agent_stats_node_detail(node: str, instance_id: str | None = None) -> Dict[str, Any]:
    """Return the latest agent health sample and status for a specific node/instance."""
    try:
        all_node_items = (
            await storage_owner_client.agent_latest(node)
            if storage_owner_client.enabled
            else await run_in_threadpool(AgentStatsRepository().get_latest, node)
        )
    except StorageOwnerError as exc:
        return _remote_error_response(exc)
    if not all_node_items:
        return {"node": node, "instance_id": instance_id, "latest": None, "instances": [], "found": False}
    
    # If instance_id requested, filter to that instance
    selected = next((it for it in all_node_items if it.get("instance_id") == instance_id), None) if instance_id else all_node_items[0]
    instances = [it.get("instance_id") for it in all_node_items if it.get("instance_id")]
    
    if not selected:
        return {"node": node, "instance_id": instance_id, "latest": None, "instances": instances, "found": False}

    return {
        "node": node,
        "instance_id": selected.get("instance_id"),
        "latest": selected,
        "instances": instances,
        "found": True,
    }


@router.delete("/api/agent/stats/{node}")
async def agent_stats_delete_node(node: str, instance_id: str | None = None) -> Dict[str, Any]:
    """Delete an agent node (or a specific instance if instance_id is provided)."""
    try:
        result = (
            await storage_owner_client.delete_agent(node, instance_id)
            if storage_owner_client.enabled
            else await run_in_threadpool(AgentStatsRepository().delete_instance, node, instance_id)
        )
    except StorageOwnerError as exc:
        return _remote_error_response(exc)
    if not result["deleted"]:
        target_str = f"node '{node}' (instance '{instance_id}')" if instance_id else f"node '{node}'"
        return JSONResponse(
            {"ok": False, "node": node, "instance_id": instance_id, "error": f"Agent {target_str} not found", "found": False},
            status_code=404,
        )
    return {
        "ok": True,
        "node": node,
        "instance_id": instance_id,
        "deleted": True,
        "deleted_latest": result["deleted_latest"],
        "deleted_history": result["deleted_history"],
    }


@router.delete("/api/agent/stats/{node}/{instance_id}")
async def agent_stats_delete_specific_instance(node: str, instance_id: str) -> Dict[str, Any]:
    """Delete a specific agent instance and its historical telemetry records."""
    return await agent_stats_delete_node(node=node, instance_id=instance_id)
