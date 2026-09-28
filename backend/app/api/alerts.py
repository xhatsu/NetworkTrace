"""Operator-managed alert rules for deeply scoped Change notifications."""
from __future__ import annotations
import json
import time
import uuid
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from backend.app.repositories.db_context import db_transaction
from backend.app.services.alerting import deliver_pending

router = APIRouter(prefix="/api/v1", tags=["alerts"])

class AlertRule(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    severity: str = Field(default="warning", pattern="^(info|warning|critical)$")
    condition: dict[str, Any] = Field(default_factory=dict)
    destinations: list[dict[str, str]] = Field(default_factory=list)
    cooldown_minutes: int = Field(default=30, ge=1, le=10080)


def _decode(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "enabled": bool(row["enabled"]),
            "severity": row["severity"], "condition": json.loads(row["condition_json"] or "{}"),
            "destinations": json.loads(row["destinations_json"] or "[]"),
            "cooldown_minutes": row["cooldown_minutes"], "created_at_ms": row["created_at_ms"],
            "updated_at_ms": row["updated_at_ms"]}

@router.get("/alerts")
def list_alerts() -> dict[str, Any]:
    with db_transaction() as db:
        rows = db.execute("SELECT * FROM alert_rules FINAL ORDER BY updated_at_ms DESC").fetchall()
    return {"items": [_decode(row) for row in rows]}

@router.post("/alerts")
def create_alert(body: AlertRule) -> dict[str, Any]:
    now = int(time.time() * 1000); rule_id = f"alert-{uuid.uuid4().hex[:12]}"
    with db_transaction() as db:
        db.execute("INSERT INTO alert_rules (id,name,enabled,severity,condition_json,destinations_json,cooldown_minutes,created_at_ms,updated_at_ms) VALUES (?,?,?,?,?,?,?,?,?)",
                   (rule_id, body.name, int(body.enabled), body.severity, json.dumps(body.condition), json.dumps(body.destinations), body.cooldown_minutes, now, now))
    return {"id": rule_id, **body.model_dump(), "created_at_ms": now, "updated_at_ms": now}

@router.put("/alerts/{rule_id}")
def update_alert(rule_id: str, body: AlertRule) -> dict[str, Any]:
    now = int(time.time() * 1000)
    with db_transaction() as db:
        existing = db.execute("SELECT id,created_at_ms FROM alert_rules FINAL WHERE id=?", (rule_id,)).fetchone()
        if not existing: raise HTTPException(404, "Alert rule not found")
        db.execute("INSERT INTO alert_rules (id,name,enabled,severity,condition_json,destinations_json,cooldown_minutes,created_at_ms,updated_at_ms) VALUES (?,?,?,?,?,?,?,?,?)",
                   (rule_id, body.name, int(body.enabled), body.severity, json.dumps(body.condition), json.dumps(body.destinations), body.cooldown_minutes, existing["created_at_ms"], now))
    return {"id": rule_id, **body.model_dump(), "created_at_ms": existing["created_at_ms"], "updated_at_ms": now}

@router.get("/alerts/deliveries")
def list_deliveries(limit: int = 100) -> dict[str, Any]:
    with db_transaction() as db:
        rows = db.execute("SELECT * FROM alert_deliveries FINAL ORDER BY updated_at_ms DESC LIMIT ?", (min(limit, 500),)).fetchall()
        items = []
        for row in rows:
            event = db.execute("SELECT payload_json FROM alert_events FINAL WHERE event_id=? LIMIT 1", (row["event_id"],)).fetchone()
            item = dict(row.items())
            if event:
                payload = json.loads(event["payload_json"] or "{}")
                change = payload.get("change") or {}
                item["change_id"] = change.get("id")
                item["change_summary"] = change.get("summary")
            items.append(item)
    return {"items": items}

@router.post("/alerts/deliveries/retry")
def retry_deliveries() -> dict[str, int]:
    return {"delivered": deliver_pending(limit=100)}

@router.delete("/alerts/{rule_id}")
def delete_alert(rule_id: str) -> dict[str, bool]:
    with db_transaction() as db:
        existing = db.execute("SELECT id FROM alert_rules FINAL WHERE id=?", (rule_id,)).fetchone()
        if not existing: raise HTTPException(404, "Alert rule not found")
        db.execute("ALTER TABLE alert_rules DELETE WHERE id=? SETTINGS mutations_sync=1", (rule_id,))
    return {"ok": True}
