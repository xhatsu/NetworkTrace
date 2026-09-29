"""Rule matching, durable outbox creation, and signed webhook delivery."""
from __future__ import annotations
import hashlib, hmac, json, logging, os, time, uuid
from datetime import datetime, timezone
from typing import Any
import httpx
from backend.app.repositories.db_context import db_transaction

log = logging.getLogger("tracescope-alerts")

def _clip(value: Any, limit: int = 400) -> str:
    """Bound plain text in UTF-16 units, including non-BMP characters."""
    text = "—" if value is None else str(value)
    encoded = text.encode("utf-16-le", errors="replace")
    if len(encoded) <= limit * 2:
        return text
    return encoded[: (limit - 1) * 2].decode("utf-16-le", errors="ignore") + "…"


def _alert_time(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return datetime.fromtimestamp(float(value) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OverflowError, OSError):
        return _clip(value, 60)


def format_alert_message(payload: dict[str, Any]) -> str:
    """Render both new and legacy outbox payloads without Telegram markup."""
    rule = payload.get("rule") or {}
    change = payload.get("change") or {}
    scope = payload.get("scope") or {}
    lines = [f"TraceScope alert | {_clip(rule.get('severity'), 40)}",
             f"Rule: {_clip(rule.get('name'), 120)}",
             f"Evaluation: {_clip(change.get('state'), 40)} | Workflow: {_clip(change.get('status'), 40)}",
             _clip(change.get("summary") or "Change detected", 500)]
    for key, label in (("subject", "Subject"), ("service", "Service"),
                       ("caller", "Caller service"), ("operation", "API / Operation"),
                       ("principal", "Observed credential"), ("source_ip", "Source IP")):
        if scope.get(key) is not None:
            lines.append(f"{label}: {_clip(scope[key], 180)}")
    lines.extend([f"Started: {_alert_time(change.get('started_at'))}",
                  f"Last seen: {_alert_time(change.get('last_seen_at'))}"])
    if change.get("signal_count") is not None:
        lines.append(f"Signals: {change['signal_count']}")
    for metric in change.get("highlights") or []:
        unit = metric.get("unit") or ""
        delta = f"; change {_clip(metric['delta'], 30)}%" if metric.get("delta") is not None else ""
        lines.append(f"{_clip(metric.get('label'), 60)}: reference {_clip(metric.get('before'), 100)} → observed {_clip(metric.get('after'), 100)} {_clip(unit, 20)}{delta}")
    for item in change.get("evidence") or []:
        lines.append(f"Evidence [{_clip(item.get('detector'), 80)}]: {_clip(item.get('detail'), 300)}")
    for reason in (change.get("abnormality") or {}).get("reasons") or []:
        lines.append(f"Assessment: {_clip(reason, 300)}")
    # Reserve room for the investigation link even when evidence is long.
    footer = f"\nChange ID: {_clip(change.get('id'), 100)}"
    link = (payload.get("links") or {}).get("change")
    if link:
        footer += f"\nDetails: {_clip(link, 700)}"
    remaining = 4000 - len(footer.encode("utf-16-le")) // 2
    return _clip("\n".join(lines), remaining) + footer

def _match(rule: dict[str, Any], episode: dict[str, Any]) -> bool:
    c = rule.get("condition") or {}; subject = episode.get("subject") or {}
    if c.get("subject") not in (None, "", "any") and c["subject"] != subject.get("type"): return False
    if c.get("state") not in (None, "", "any") and c["state"] != episode.get("state"): return False
    if c.get("service") and c["service"] not in json.dumps(episode, separators=(",", ":")): return False
    if c.get("principal") and c["principal"] not in json.dumps(episode, separators=(",", ":")): return False
    if c.get("operation") and c["operation"] not in json.dumps(episode, separators=(",", ":")): return False
    wanted = set(c.get("change_types") or [])
    actual = {str(s.get("type", "")) for s in episode.get("signals", [])} | {str(e.get("detector", "")) for e in episode.get("evidence", [])}
    return not wanted or bool(wanted & actual)

def _fingerprint(rule_id: str, episode: dict[str, Any]) -> str:
    subject = episode.get("subject") or {}
    raw = "|".join([rule_id, str(episode.get("id", "")), str(subject.get("type", "")), str(subject.get("name", ""))])
    return hashlib.sha256(raw.encode()).hexdigest()

def load_rules(db_path=None) -> list[dict[str, Any]]:
    with db_transaction(db_path) as db:
        rows = db.execute("SELECT * FROM alert_rules FINAL WHERE enabled=1").fetchall()
    return [{"id": r["id"], "name": r["name"], "severity": r["severity"], "condition": json.loads(r["condition_json"] or "{}"), "destinations": json.loads(r["destinations_json"] or "[]"), "cooldown_minutes": r["cooldown_minutes"]} for r in rows]

def enqueue_matching(episodes: list[dict[str, Any]], db_path=None, base_url: str = "") -> int:
    if not episodes: return 0
    rules = load_rules(db_path); now = int(time.time() * 1000); created = 0
    with db_transaction(db_path) as db:
        for rule in rules:
            for episode in episodes:
                if not _match(rule, episode): continue
                # A Change episode is a single incident. Cooldown is not an
                # incident identity: using it alone re-fired every active
                # episode after N minutes. Keep one fired event per
                # rule+episode; delivery retries reuse that event ID.
                fp = _fingerprint(rule["id"], episode)
                existing = db.execute("SELECT event_id FROM alert_events FINAL WHERE rule_id=? AND fingerprint=? LIMIT 1", (rule["id"], fp)).fetchone()
                if existing: continue
                event_id = f"evt-{uuid.uuid4().hex[:16]}"
                subject = episode.get("subject") or {}; payload = {"event": "tracescope.alert.fired", "event_id": event_id, "occurred_at": now, "rule": {"id": rule["id"], "name": rule["name"], "severity": rule["severity"]}, "change": {"id": episode.get("id"), "state": episode.get("state"), "status": episode.get("status"), "summary": episode.get("summary"), "started_at": episode.get("started_at"), "last_seen_at": episode.get("last_seen_at")}, "scope": {"subject_type": subject.get("type"), "subject": subject.get("name"), "service": episode.get("service"), "operation": episode.get("operation"), "principal": episode.get("principal")}, "links": {"change": f"{base_url}/changes/{episode.get('id')}" if base_url else None}}
                context = episode.get("context") or {}
                payload["scope"].update({
                    "service": episode.get("service") or context.get("target"),
                    "operation": episode.get("operation") or context.get("operation"),
                    "principal": episode.get("principal") or (subject.get("name") if subject.get("type") == "user" else None),
                    "caller": context.get("caller"), "source_ip": context.get("source_ip"),
                })
                # Keep the public episode evidence, never raw trace/auth records.
                for key in ("highlights", "evidence", "signals", "signal_count", "abnormality"):
                    payload["change"][key] = episode.get(key)
                encoded = json.dumps(payload, separators=(",", ":")); db.execute("INSERT INTO alert_events (event_id,rule_id,fingerprint,event_type,payload_json,created_at_ms) VALUES (?,?,?,?,?,?)", (event_id, rule["id"], fp, "fired", encoded, now))
                for destination in rule["destinations"]:
                    target = destination.get("url") or destination.get("target") or destination.get("chat_id", "")
                    db.execute("INSERT INTO alert_deliveries (delivery_id,event_id,rule_id,destination_type,destination_target,status,attempts,next_attempt_at_ms,updated_at_ms) VALUES (?,?,?,?,?,?,?,?,?)", (f"del-{uuid.uuid4().hex[:16]}", event_id, rule["id"], destination.get("type", "webhook"), target, "pending", 0, now, now))
                created += 1
    return created

def deliver_pending(db_path=None, limit: int = 25) -> int:
    now = int(time.time() * 1000); delivered = 0
    with db_transaction(db_path) as db:
        rows = db.execute("SELECT * FROM alert_deliveries FINAL WHERE status IN ('pending','retrying') AND next_attempt_at_ms<=? ORDER BY updated_at_ms LIMIT ?", (now, limit)).fetchall()
        payloads = {}
        for row in rows:
            event = db.execute("SELECT payload_json FROM alert_events FINAL WHERE event_id=? LIMIT 1", (row["event_id"],)).fetchone()
            if event:
                payloads[row["delivery_id"]] = event["payload_json"]
    for row in rows:
        payload = payloads.get(row["delivery_id"])
        if not payload:
            continue
        destination = row["destination_target"]; kind = row["destination_type"]; secret = os.getenv("OTEL_ALERT_WEBHOOK_SECRET", "")
        body = payload; headers = {"Content-Type": "application/json", "User-Agent": "TraceScope-Alerts/1.0", "X-TraceScope-Event-ID": row["event_id"], "X-TraceScope-Timestamp": str(now // 1000)}
        if secret: headers["X-TraceScope-Signature"] = "sha256=" + hmac.new(secret.encode(), f"{now // 1000}.{body}".encode(), hashlib.sha256).hexdigest()
        if kind == "telegram":
            token = os.getenv("OTEL_ALERT_TELEGRAM_TOKEN", ""); chat_id = destination
            destination = f"https://api.telegram.org/bot{token}/sendMessage"; body = json.dumps({"chat_id": chat_id, "text": format_alert_message(json.loads(payload)), "disable_web_page_preview": True})
        try:
            response = httpx.post(destination, content=body, headers=headers, timeout=10)
            ok = 200 <= response.status_code < 300; attempts = int(row["attempts"]) + 1
            with db_transaction(db_path) as db:
                db.execute("INSERT INTO alert_deliveries (delivery_id,event_id,rule_id,destination_type,destination_target,status,attempts,response_code,error,next_attempt_at_ms,updated_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (row["delivery_id"], row["event_id"], row["rule_id"], kind, row["destination_target"], "delivered" if ok else ("failed" if attempts >= 6 else "retrying"), attempts, response.status_code, "" if ok else response.text[:300], 0 if ok else now + min(7200000, 30000 * (2 ** min(attempts, 7))), now))
            delivered += int(ok)
        except Exception as exc:
            log.warning("alert delivery failed: %s", str(exc)[:200]); attempts = int(row["attempts"]) + 1
            with db_transaction(db_path) as db: db.execute("INSERT INTO alert_deliveries (delivery_id,event_id,rule_id,destination_type,destination_target,status,attempts,error,next_attempt_at_ms,updated_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?)", (row["delivery_id"], row["event_id"], row["rule_id"], kind, row["destination_target"], "failed" if attempts >= 6 else "retrying", attempts, str(exc)[:300], now + 30000, now))
    return delivered
