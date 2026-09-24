"""Operator-facing Changes episodes built from existing detector signals.

The detector tables remain the source of truth.  This adapter deliberately
keeps detector names, scores, and baseline mechanics out of the primary
operator contract while preserving them in ``evidence`` for drill-downs.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, Iterable, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.app.repositories.anomaly_repository import AnomalyRepository
from backend.app.repositories.user_repository import UserRepository
from backend.app.services.normalization import classify_source_ip_role


router = APIRouter(prefix="/api/v1", tags=["changes"])


def _timestamp(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 10_000_000_000 else number * 1000
    try:
        number = float(str(value))
        return int(number) if number > 10_000_000_000 else int(number * 1000)
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _window(from_time: Any, to_time: Any, start: Any, end: Any) -> tuple[int | None, int | None]:
    return _timestamp(from_time or start), _timestamp(to_time or end)


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _severity_state(severity: Any) -> str:
    normalized = str(severity or "medium").lower()
    if normalized == "critical":
        return "critical"
    if normalized == "high":
        return "needs_attention"
    return "changed"


# Only an explicit operator acceptance means expected behavior. Suppression and
# data-quality dismissal remain workflow outcomes, not behavioral truth.
_EXPECTED_STATUSES = {"expected"}
_IP_CHANGE_TYPES = {"NEW_SOURCE_IP", "NEW_IP_CALLER_PAIR", "SOURCE_IP_DISTRIBUTION_SHIFT", "IP_NEW_USER", "USER_NEW_SOURCE_IP"}


def _signal_type(signal: dict[str, Any]) -> str:
    raw = signal.get("signal") or {}
    return str(raw.get("change_type") or raw.get("anomaly_type") or "change").upper()


def _signal_domain(signal_type: str) -> str:
    normalized = signal_type.upper()
    if "AUTH" in normalized or "FAILURE_THEN_SUCCESS" in normalized:
        return "authentication"
    if "ERROR" in normalized or "5XX" in normalized or "FAILURE" in normalized:
        return "errors"
    if "LATENCY" in normalized or "DURATION" in normalized or "EXECUTION_TIME" in normalized:
        return "performance"
    if "TRAFFIC" in normalized or "RATE" in normalized or "TPS" in normalized or "SURGE" in normalized or "DROP" in normalized:
        return "traffic"
    if "SOURCE_IP" in normalized or normalized in {"IP_NEW_USER", "USER_NEW_SOURCE_IP"}:
        return "network"
    return "access"


def _reason_mapping(signal: dict[str, Any]) -> dict[str, Any]:
    raw = signal.get("signal") or {}
    reason = raw.get("reason") or _json_value(raw.get("reason_json"), {})
    return reason if isinstance(reason, dict) else {}


def _is_infrastructure_ip_signal(signal: dict[str, Any]) -> bool:
    if _signal_type(signal) not in _IP_CHANGE_TYPES:
        return False
    reason = _reason_mapping(signal)
    role = str(reason.get("source_ip_role") or "").lower()
    confidence = str(reason.get("attribution_confidence") or "").lower()
    source_ip = _text((signal.get("context") or {}).get("source_ip"))
    if not role and source_ip:
        role, _, confidence = classify_source_ip_role(source_ip)
    return role in {"load_balancer", "reverse_proxy", "nat_gateway", "service_ingress"} or confidence == "low"


def _evaluate_episode(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Promote correlated changes to abnormal states without conflating both concepts."""
    types = [_signal_type(signal) for signal in signals]
    domains = {_signal_domain(signal_type) for signal_type in types}
    raw_statuses = {str(signal.get("raw_status") or "open").lower() for signal in signals}
    source_severities = {str(signal.get("severity") or "medium").lower() for signal in signals}
    all_expected = bool(raw_statuses) and raw_statuses.issubset(_EXPECTED_STATUSES)
    infrastructure_only = bool(signals) and all(_is_infrastructure_ip_signal(signal) for signal in signals)
    correlated = len(signals) > 1
    dangerous_domain = bool(domains & {"authentication", "errors", "performance"})

    numeric_deltas: list[float] = []
    for signal in signals:
        for highlight in signal.get("highlights") or []:
            try:
                if highlight.get("delta") is not None:
                    numeric_deltas.append(abs(float(highlight["delta"])))
            except (TypeError, ValueError):
                continue
    material_numeric_change = any(delta >= 100 for delta in numeric_deltas)
    critical_source = "critical" in source_severities
    high_source = bool(source_severities & {"critical", "high"})
    access_correlation = len([item for item in types if _signal_domain(item) == "access"]) >= 2
    detector_confirmed_metric = any(signal.get("source") == "anomaly" for signal in signals) and dangerous_domain

    reasons: list[str] = []
    if all_expected:
        state = "expected"
        reasons.append("Operator review or suppression marks this behavior as expected.")
    elif infrastructure_only:
        state = "changed"
        reasons.append("The source change is attributed only to known or low-confidence infrastructure hops.")
    elif critical_source and (dangerous_domain or correlated):
        state = "critical"
        reasons.append("Critical detector evidence includes operational or correlated behavioral impact.")
    elif len(domains) >= 3 and bool(domains & {"authentication", "errors"}):
        state = "critical"
        reasons.append("Multiple independent evidence domains include authentication or error impact.")
    elif high_source or detector_confirmed_metric or material_numeric_change or access_correlation or (correlated and len(domains) >= 2):
        state = "needs_attention"
        if high_source:
            reasons.append("A source detector classified the observed deviation as high impact.")
        if correlated:
            reasons.append(f"{len(signals)} related changes were observed in the same subject and time window.")
        if material_numeric_change:
            reasons.append("A measured metric changed by at least 100% from baseline.")
        if dangerous_domain:
            reasons.append("Performance, error, or authentication evidence is present.")
        if access_correlation:
            reasons.append("Multiple access relationships changed together.")
    else:
        state = "changed"
        reasons.append("A meaningful difference was observed, but current evidence does not make it abnormal.")

    return {
        "state": state,
        "is_abnormal": state in {"needs_attention", "critical"},
        "correlated": correlated,
        "infrastructure_only": infrastructure_only,
        "domains": sorted(domains),
        "reasons": reasons,
        "evaluation_version": "episode-v1",
    }


def _change_status(status: Any) -> str:
    normalized = str(status or "new").lower()
    if normalized in {"expected", "ignored", "resolved", "suppressed"}:
        return "resolved"
    if normalized in {"reviewed", "acknowledged", "investigating"}:
        return "acknowledged"
    return "open"


def _readable_change(change_type: str) -> str:
    return change_type.replace("_", " ").strip().title() or "Behavior change"


def _change_summary(row: dict[str, Any]) -> str:
    principal = _text(row.get("principal_name")) or "This identity"
    target = _text(row.get("target_service"))
    operation = _text(row.get("operation"))
    caller = _text(row.get("caller_service"))
    change_type = str(row.get("change_type") or "").upper()

    if change_type in {"NEW_TARGET", "NEW_RELATIONSHIP"} and target:
        return f"{principal} started accessing {target} for the first time."
    if change_type == "NEW_OPERATION" and operation:
        return f"{principal} started using {operation} for the first time."
    if change_type == "NEW_CALLER" and caller:
        return f"{principal} received traffic from a new caller: {caller}."
    if change_type in {"NEW_SOURCE_IP", "NEW_IP_CALLER_PAIR", "SOURCE_IP_DISTRIBUTION_SHIFT"}:
        source_ip = _text(row.get("source_ip")) or "a new source IP"
        return f"{principal} appeared from {source_ip}."
    if change_type == "DORMANT_REACTIVATED":
        return f"{principal} became active again after a quiet period."
    if change_type in {"PRINCIPAL_RATE_SURGE", "TARGET_FANOUT_SURGE", "SOURCE_FANOUT_SURGE"}:
        return f"{principal} changed its traffic pattern significantly."
    if change_type == "CALLER_PRINCIPAL_SWITCH":
        return f"{principal} was mapped to a different caller relationship."
    if change_type == "UNUSUAL_TIME":
        return f"{principal} was active outside its normal time pattern."
    return f"{principal} has a new behavioral change: {_readable_change(change_type).lower()}."


def _anomaly_summary(row: dict[str, Any]) -> str:
    subject = _text(row.get("principal_name")) or _text(row.get("target_service")) or _text(row.get("caller_service")) or "This service"
    anomaly_type = str(row.get("anomaly_type") or "").lower()
    if "latency" in anomaly_type:
        return f"{subject} latency is significantly above normal."
    if "error" in anomaly_type:
        return f"{subject} error rate increased above normal."
    if "drop" in anomaly_type:
        return f"{subject} traffic dropped below its normal level."
    if "spike" in anomaly_type or "surge" in anomaly_type:
        return f"{subject} traffic increased above its normal level."
    if "new_service" in anomaly_type or "principal_edge" in anomaly_type:
        target = _text(row.get("target_service")) or "a new service relationship"
        return f"{subject} started using {target}."
    return f"{subject} differs from its normal operating pattern."


def _highlight(label: str, before: Any, after: Any, unit: str | None = None, delta: Any = None) -> dict[str, Any]:
    return {
        "label": label,
        "before": before,
        "after": after,
        "unit": unit,
        "delta": delta,
    }


def _change_signal(row: dict[str, Any]) -> dict[str, Any]:
    detected = _timestamp(row.get("detected_at")) or 0
    first = _timestamp(row.get("first_observed")) or detected
    principal = _text(row.get("principal_name"))
    target = _text(row.get("target_service"))
    operation = _text(row.get("operation"))
    caller = _text(row.get("caller_service"))
    source_ip = _text(row.get("source_ip"))
    change_type = str(row.get("change_type") or "behavior_change")
    reason = _json_value(row.get("reason"), {})
    reason_text = (reason.get("text") or reason.get("summary") or reason.get("what_changed")) if isinstance(reason, dict) else None

    highlights: list[dict[str, Any]] = []
    if target:
        highlights.append(_highlight("Target", None if change_type in {"NEW_TARGET", "NEW_RELATIONSHIP"} else row.get("old_value"), target))
    if operation:
        highlights.append(_highlight("API", None if change_type == "NEW_OPERATION" else None, operation))
    if caller:
        highlights.append(_highlight("Caller", None, caller))
    if source_ip:
        highlights.append(_highlight("Source IP", None, source_ip))

    source_role = reason.get("source_ip_role") if isinstance(reason, dict) else None
    role_label = reason.get("role_label") if isinstance(reason, dict) else None
    if source_ip and not source_role:
        source_role, role_label, _ = classify_source_ip_role(source_ip)
    evidence_detail = reason_text or "Behavior changed compared with the learned baseline."
    if change_type.upper() in _IP_CHANGE_TYPES and source_role in {"load_balancer", "reverse_proxy", "nat_gateway", "service_ingress"}:
        evidence_detail = f"{evidence_detail} Source role: {role_label or source_role}; supporting infrastructure evidence only."

    return {
        "id": f"chg-{row.get('id')}",
        "source": "principal_change",
        "source_id": str(row.get("id")),
        "subject": {"type": "user", "name": principal or "unknown"},
        "summary": _change_summary(row),
        "explanation": reason_text or _readable_change(change_type),
        "started_at": first,
        "last_seen_at": detected,
        "context": {"caller": caller, "target": target, "operation": operation, "source_ip": source_ip},
        "highlights": highlights,
        "evidence": [{
            "label": _readable_change(change_type),
            "detector": change_type,
            "detail": evidence_detail,
        }],
        "signal_count": 1,
        "state": _severity_state(row.get("severity")),
        "severity": str(row.get("severity") or "medium").lower(),
        "status": _change_status(row.get("status")),
        "raw_status": row.get("status") or "new",
        "score": row.get("score"),
        "signal": row,
    }


def _anomaly_signal(row: dict[str, Any]) -> dict[str, Any]:
    detected = _timestamp(row.get("detected_at")) or _timestamp(row.get("last_seen")) or 0
    first = _timestamp(row.get("first_seen")) or detected
    last = _timestamp(row.get("last_seen")) or detected
    principal = _text(row.get("principal_name"))
    target = _text(row.get("target_service"))
    caller = _text(row.get("caller_service"))
    operation = _text(row.get("operation"))
    source_ip = _text(row.get("source_ip"))
    anomaly_type = str(row.get("anomaly_type") or "anomaly")
    baseline = row.get("baseline_value")
    current = row.get("current_value")
    unit = "ms" if "latency" in anomaly_type.lower() else "%" if "error" in anomaly_type.lower() else "tps"
    reasons = row.get("reasons") or _json_value(row.get("reason_json"), [])
    if isinstance(reasons, dict):
        reasons = [reasons]
    reason_text = next((item.get("text") for item in reasons if isinstance(item, dict) and item.get("text")), None)
    percent = row.get("delta_percentage")
    if percent is None and baseline not in (None, 0):
        percent = round((float(current or 0) - float(baseline)) / float(baseline) * 100, 1)

    return {
        "id": f"anm-{row.get('id')}",
        "source": "anomaly",
        "source_id": str(row.get("id")),
        "subject": {"type": "user" if principal and principal not in {"unknown", "-anonymous-"} else "service", "name": principal or target or caller or "unknown"},
        "summary": _anomaly_summary(row),
        "explanation": reason_text or f"{_readable_change(anomaly_type)} compared with the normal operating pattern.",
        "started_at": first,
        "last_seen_at": last,
        "context": {"caller": caller, "target": target, "operation": operation, "source_ip": source_ip},
        "highlights": [_highlight("Latency" if unit == "ms" else "Error" if unit == "%" else "TPS", baseline, current, unit, percent)],
        "evidence": [{
            "label": _readable_change(anomaly_type),
            "detector": anomaly_type,
            "detail": reason_text or "Measured deviation from the learned baseline.",
        }],
        "signal_count": 1,
        "state": _severity_state(row.get("severity")),
        "severity": str(row.get("severity") or "medium").lower(),
        "status": _change_status(row.get("status")),
        "raw_status": row.get("status") or "open",
        "score": row.get("score"),
        "signal": row,
    }


def _episode_key(signal: dict[str, Any]) -> str:
    subject = signal["subject"]["name"]
    raw = signal["signal"]
    incident_id = _text(raw.get("incident_id"))
    if incident_id:
        return f"{signal['subject']['type']}:{incident_id}"
    # A 15-minute correlation window makes adjacent facts one operator episode.
    window = int(signal["started_at"] or 0) // 900_000
    context = signal.get("context") or {}
    scope = context.get("target") or context.get("caller") or "estate"
    return f"{signal['subject']['type']}:{subject}:{scope}:{window}"


def _merge_signals(signals: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    episodes: OrderedDict[str, dict[str, Any]] = OrderedDict()
    status_rank = {"open": 3, "acknowledged": 2, "resolved": 1}
    for signal in sorted(signals, key=lambda item: (item["last_seen_at"], item["id"]), reverse=True):
        key = _episode_key(signal)
        current = episodes.get(key)
        if current is None:
            current = {**signal, "signal_ids": [], "signals": [], "evidence": [], "highlights": [], "_evaluation_signals": []}
            episodes[key] = current
        current["signal_ids"].append(signal["id"])
        current["_evaluation_signals"].append(signal)
        current["signals"].append({
            "id": signal["id"],
            "source": signal["source"],
            "type": signal["signal"].get("change_type") or signal["signal"].get("anomaly_type"),
            "detected_at": signal["last_seen_at"],
        })
        current["evidence"].extend(signal["evidence"])
        current["highlights"].extend(signal["highlights"])
        current["started_at"] = min(current["started_at"], signal["started_at"])
        current["last_seen_at"] = max(current["last_seen_at"], signal["last_seen_at"])
        if status_rank.get(signal["status"], 0) > status_rank.get(current["status"], 0):
            current["status"] = signal["status"]
        current["signal_count"] = len(current["signal_ids"])

    for episode in episodes.values():
        seen_evidence: set[str] = set()
        episode["evidence"] = [item for item in episode["evidence"] if not (item["detector"] in seen_evidence or seen_evidence.add(item["detector"]))]
        seen_highlights: set[tuple[str, str]] = set()
        compact: list[dict[str, Any]] = []
        for item in episode["highlights"]:
            marker = (str(item.get("label")), str(item.get("after")))
            if marker not in seen_highlights:
                seen_highlights.add(marker)
                compact.append(item)
        episode["highlights"] = compact[:8]
        evaluation = _evaluate_episode(episode["_evaluation_signals"])
        episode["state"] = evaluation["state"]
        episode["severity"] = {"expected": "info", "changed": "info", "needs_attention": "high", "critical": "critical"}[evaluation["state"]]
        episode["abnormality"] = evaluation
        if episode["signal_count"] > 1:
            domains = set(evaluation["domains"])
            if "access" in domains and domains & {"traffic", "errors", "performance", "authentication"}:
                episode["summary"] = f"{episode['subject']['name']} changed its access behavior while operational metrics deviated from normal."
            else:
                episode["summary"] = f"{episode['summary']} ({episode['signal_count']} related changes)."
        episode.pop("_evaluation_signals", None)
        episode.pop("signal", None)
    return list(episodes.values())


def _load_signals(start_ms: int | None, end_ms: int | None, limit: int) -> list[dict[str, Any]]:
    anomaly_rows = AnomalyRepository().list_anomalies(start_ms=start_ms, end_ms=end_ms, limit=limit)
    change_result = UserRepository().list_changes(start_ms=start_ms, end_ms=end_ms, limit=limit)
    change_rows = change_result.get("items", [])
    # list_changes intentionally has a non-empty fallback for the user UI; the
    # Changes feed must still honor an explicit time window.
    if start_ms is not None or end_ms is not None:
        change_rows = [
            row for row in change_rows
            if (start_ms is None or int(row.get("detected_at") or 0) >= start_ms)
            and (end_ms is None or int(row.get("detected_at") or 0) < end_ms)
        ]
    return [_anomaly_signal(row) for row in anomaly_rows] + [_change_signal(row) for row in change_rows]


def _filter_episodes(episodes: list[dict[str, Any]], *, subject_type: str | None, state: str | None,
                     status: str | None, service: str | None, principal: str | None, search: str | None) -> list[dict[str, Any]]:
    query = (search or "").strip().lower()
    result = []
    for episode in episodes:
        if subject_type and episode["subject"]["type"] != subject_type:
            continue
        if state and episode["state"] != state:
            continue
        if status and episode["status"] != status:
            continue
        context = episode.get("context") or {}
        if service and service not in {context.get("caller"), context.get("target")}:
            continue
        if principal and episode["subject"]["name"] != principal:
            continue
        if query:
            haystack = " ".join(str(value or "") for value in [
                episode["subject"]["name"], episode["summary"], episode["explanation"],
                *context.values(), *(item.get("detector") for item in episode.get("evidence", [])),
            ]).lower()
            if query not in haystack:
                continue
        result.append(episode)
    return sorted(result, key=lambda item: (item["status"] == "resolved", -item["last_seen_at"]))


@router.get("/changes")
async def list_changes(
    from_time: Optional[Any] = Query(None, alias="from"),
    to_time: Optional[Any] = Query(None, alias="to"),
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    subject_type: Optional[str] = Query(None, alias="subject"),
    state: Optional[str] = None,
    status: Optional[str] = None,
    service: Optional[str] = None,
    principal: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    start_ms, end_ms = _window(from_time, to_time, start, end)
    signals = _load_signals(start_ms, end_ms, min(500, max(limit * 3, 100)))
    episodes = _filter_episodes(_merge_signals(signals), subject_type=subject_type, state=state,
                                status=status, service=service, principal=principal, search=q)
    items = episodes[:limit]
    return {
        "items": items,
        "count": len(items),
        "total": len(episodes),
        "summary": {
            "expected": sum(item["state"] == "expected" for item in episodes),
            "changed": sum(item["state"] == "changed" and item["status"] != "resolved" for item in episodes),
            "needs_attention": sum(item["state"] in {"needs_attention", "critical"} and item["status"] != "resolved" for item in episodes),
            "critical": sum(item["state"] == "critical" and item["status"] != "resolved" for item in episodes),
            "reviewed": sum(item["state"] == "expected" or item["status"] == "resolved" for item in episodes),
            "changed_users": sum(item["subject"]["type"] == "user" and item["status"] != "resolved" for item in episodes),
            "changed_services": sum(item["subject"]["type"] == "service" and item["status"] != "resolved" for item in episodes),
        },
    }


@router.get("/changes/{episode_id}")
async def get_change_episode(episode_id: str, from_time: Optional[Any] = Query(None, alias="from"),
                             to_time: Optional[Any] = Query(None, alias="to"), start: Optional[Any] = None,
                             end: Optional[Any] = None) -> dict[str, Any]:
    start_ms, end_ms = _window(from_time, to_time, start, end)
    prefix, _, raw_id = episode_id.partition("-")
    source_signals: list[dict[str, Any]] = []
    if prefix == "chg":
        row = UserRepository().get_change(int(raw_id)) if raw_id.isdigit() else None
        source_signals = [_change_signal(row)] if row else []
    elif prefix == "anm":
        row = AnomalyRepository().get_anomaly(int(raw_id)) if raw_id.isdigit() else None
        source_signals = [_anomaly_signal(row)] if row else []
    elif episode_id.isdigit():
        anomaly_row = AnomalyRepository().get_anomaly(int(episode_id))
        change_row = UserRepository().get_change(int(episode_id))
        if anomaly_row:
            source_signals.append(_anomaly_signal(anomaly_row))
        if change_row:
            source_signals.append(_change_signal(change_row))
    else:
        signals = _load_signals(start_ms, end_ms, 500)

    if source_signals:
        related_start = min(signal["started_at"] for signal in source_signals) - 900_000
        related_end = max(signal["last_seen_at"] for signal in source_signals) + 900_001
        signals = _load_signals(related_start, related_end, 500)
        known_ids = {signal["id"] for signal in signals}
        signals.extend(signal for signal in source_signals if signal["id"] not in known_ids)
    elif "signals" not in locals():
        signals = []
    episodes = _merge_signals(signals)
    requested_ids = {episode_id, *(signal["id"] for signal in source_signals)}
    item = next((episode for episode in episodes if requested_ids.intersection(episode.get("signal_ids", [])) or episode.get("id") in requested_ids), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Change episode not found")
    item["timeline"] = [
        {"at": signal["detected_at"], "type": signal["type"], "source": signal["source"]}
        for signal in sorted(item.get("signals", []), key=lambda value: value["detected_at"])
    ]
    item["debug"] = {
        "signals": item.get("signals", []),
        "scores_are_secondary": True,
        "note": "Detector scores and baseline mechanics remain available in the source evidence.",
    }
    return item
