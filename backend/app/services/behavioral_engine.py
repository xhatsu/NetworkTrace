"""TraceScope Behavioral Engine

Implements canonical identity and request evidence normalization, detector readiness,
multi-layer baselines, bounded incidents, capped family scoring, and behavioral detectors.

The engine persists explainable derived evidence in the shared ClickHouse store,
which lets periodic workers and read APIs agree without replaying raw telemetry.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.config import settings
from backend.app.repositories.db_context import get_connection, db_transaction
from backend.app.models.incident import Incident, OperatorOverride


# -----------------------------------------------------------------------------
# Family caps prevent many correlated observations from being presented as many independent risks.
# 1. Scoring Matrix and Family Caps
# -----------------------------------------------------------------------------

EVENT_FAMILY = {
    # Origin family (cap: 35)
    "NEW_CALLER": "origin",
    "NEW_SOURCE_IP": "origin",
    "SOURCE_IP_DISTRIBUTION_SHIFT": "origin",
    "NEW_IP_CALLER_PAIR": "origin",
    "NEW_PRINCIPAL_ON_SOURCE": "origin",
    "SOURCE_FANOUT_SURGE": "origin",
    # Access family (cap: 40)
    "NEW_TARGET": "access",
    "NEW_OPERATION": "access",
    "NEW_RELATIONSHIP": "access",
    "TARGET_FANOUT_SURGE": "access",
    "OPERATION_MIX_SHIFT": "access",
    "UNUSUAL_ACCESS": "access",
    # Activity family (cap: 35)
    "DORMANT_REACTIVATED": "activity",
    "PRINCIPAL_RATE_SURGE": "activity",
    "UNUSUAL_TIME": "activity",
    # Identity mapping family (cap: 30)
    "CALLER_PRINCIPAL_SWITCH": "identity_mapping",
    # Authentication family (cap: 45)
    "AUTH_FAILURE_BURST": "authentication",
    "FAILURE_THEN_SUCCESS": "authentication",
    "SOURCE_IDENTITY_FANOUT": "authentication",
    # Audit / Operational / Data Quality (0 security points)
    "USERNAME_FIRST_SEEN": "audit",
    "RELATIONSHIP_DISAPPEARED": "operational",
    "RELATIONSHIP_REAPPEARED": "operational",
    "IDENTITY_FAILURE_RATE_SHIFT": "operational",
    "DATA_QUALITY_GAP": "data_quality",
    "DATA_QUALITY_EXTRACTION_DROP": "data_quality",
}

BASE_IMPORTANCE = {
    "NEW_CALLER": "high",
    "NEW_SOURCE_IP": "low",
    "SOURCE_IP_DISTRIBUTION_SHIFT": "low",
    "NEW_IP_CALLER_PAIR": "low",
    "NEW_PRINCIPAL_ON_SOURCE": "medium",
    "SOURCE_FANOUT_SURGE": "medium",
    "NEW_TARGET": "medium",
    "NEW_OPERATION": "low",
    "NEW_RELATIONSHIP": "low",
    "TARGET_FANOUT_SURGE": "medium",
    "OPERATION_MIX_SHIFT": "medium",
    "UNUSUAL_ACCESS": "high",
    "DORMANT_REACTIVATED": "high",
    "PRINCIPAL_RATE_SURGE": "medium",
    "UNUSUAL_TIME": "low",
    "CALLER_PRINCIPAL_SWITCH": "high",
    "AUTH_FAILURE_BURST": "high",
    "FAILURE_THEN_SUCCESS": "high",
    "SOURCE_IDENTITY_FANOUT": "medium",
    "USERNAME_FIRST_SEEN": "low",
    "RELATIONSHIP_DISAPPEARED": "low",
    "RELATIONSHIP_REAPPEARED": "low",
    "IDENTITY_FAILURE_RATE_SHIFT": "medium",
    "DATA_QUALITY_GAP": "low",
    "DATA_QUALITY_EXTRACTION_DROP": "low",
}

EVENT_SCORES = {
    # Origin
    "NEW_CALLER": 30,
    "NEW_SOURCE_IP": 10,
    "SOURCE_IP_DISTRIBUTION_SHIFT": 10,
    "NEW_IP_CALLER_PAIR": 10,
    "NEW_PRINCIPAL_ON_SOURCE": 15,
    "SOURCE_FANOUT_SURGE": 25,
    # Access
    "NEW_TARGET": 25,
    "NEW_OPERATION": 15,
    "NEW_RELATIONSHIP": 15,
    "TARGET_FANOUT_SURGE": 25,
    "OPERATION_MIX_SHIFT": 25,
    "UNUSUAL_ACCESS": 30,
    # Activity
    "DORMANT_REACTIVATED": 30,
    "PRINCIPAL_RATE_SURGE": 20,
    "UNUSUAL_TIME": 10,
    # Identity mapping
    "CALLER_PRINCIPAL_SWITCH": 30,
    # Authentication
    "AUTH_FAILURE_BURST": 30,
    "FAILURE_THEN_SUCCESS": 35,
    "SOURCE_IDENTITY_FANOUT": 20,
    # Audit / Operational (0 points)
    "USERNAME_FIRST_SEEN": 0,
    "RELATIONSHIP_DISAPPEARED": 0,
    "RELATIONSHIP_REAPPEARED": 0,
    "IDENTITY_FAILURE_RATE_SHIFT": 0,
    "DATA_QUALITY_GAP": 0,
    "DATA_QUALITY_EXTRACTION_DROP": 0,
}

# Compatibility alias for legacy modules
CHANGE_SCORES = EVENT_SCORES

FAMILY_CAPS = {
    "origin": 35,
    "access": 40,
    "activity": 35,
    "identity_mapping": 30,
    "authentication": 45,
    "audit": 0,
    "operational": 0,
    "data_quality": 0,
}


def investigation_priority(score: int) -> str:
    if score >= 50:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


# -----------------------------------------------------------------------------
# 2. Detector Readiness Assessment
# -----------------------------------------------------------------------------

def evaluate_readiness(
    db, principal_id: str, detector: str, current_time_ms: int
) -> tuple[bool, str]:
    """
    Evaluates detector readiness per principal:
    - Caller/target/operation novelty: >=7 elapsed days, >=3 active days, >=100 eligible observations
    - Rate and operation mix: >=14 elapsed days and enough comparable historical windows
    - Time-of-week behavior: >=4 weeks with repeated activity in comparable weekly periods
    - Dormancy: recorded previous activity plus reliable observation coverage across interval
    - Relationship disappearance: repeated expected occurrences across several cycles
    - Authentication / policy rules: always ready (no personal-history requirement)
    """
    p_name = principal_id.split(":")[-1] if ":" in principal_id else principal_id
    if not p_name or p_name in ("-anonymous-", "unknown", "anonymous", ""):
        return False, "anonymous_not_eligible"

    # Explicit policy or authentication detectors have no personal-history requirement
    if detector in {"AUTH_FAILURE_BURST", "FAILURE_THEN_SUCCESS", "SOURCE_IDENTITY_FANOUT", "DATA_QUALITY_GAP", "NEW_PRINCIPAL_ON_SOURCE"}:
        return True, "ready"

    row = db.execute(
        "SELECT MIN(timestamp_ms), MAX(timestamp_ms), COUNT(DISTINCT timestamp_ms / 86400000), COUNT(*) "
        "FROM traces WHERE principal_id = ? OR (principal_id IS NULL AND principal_name = ?)",
        (principal_id, p_name)
    ).fetchone()

    return evaluate_readiness_from_stats(row, detector, current_time_ms)


def evaluate_readiness_from_stats(
    row, detector: str, current_time_ms: int
) -> tuple[bool, str]:
    """Apply the readiness rules to a precomputed principal aggregate."""
    if detector in {"AUTH_FAILURE_BURST", "FAILURE_THEN_SUCCESS", "SOURCE_IDENTITY_FANOUT", "DATA_QUALITY_GAP", "NEW_PRINCIPAL_ON_SOURCE"}:
        return True, "ready"
    if not row or row[0] is None or int(row[3]) == 0:
        return False, "insufficient_history"

    first_seen_ms, last_seen_ms, active_days, total_obs = row
    elapsed_days = (current_time_ms - first_seen_ms) / 86_400_000.0

    if detector in {"NEW_CALLER", "NEW_TARGET", "NEW_OPERATION", "NEW_RELATIONSHIP", "NEW_SOURCE_IP", "SOURCE_IP_DISTRIBUTION_SHIFT", "NEW_IP_CALLER_PAIR"}:
        if elapsed_days >= 7.0 and active_days >= 3 and total_obs >= 100:
            return True, "ready"
        if total_obs >= 10 or (elapsed_days >= 1.0 and total_obs >= 5):
            return True, "low_confidence"
        return False, "insufficient_history"

    if detector in {"OPERATION_MIX_SHIFT", "PRINCIPAL_RATE_SURGE", "CALLER_PRINCIPAL_SWITCH", "TARGET_FANOUT_SURGE", "SOURCE_FANOUT_SURGE"}:
        if elapsed_days >= 14.0 and active_days >= 5 and total_obs >= 200:
            return True, "ready"
        return False, "insufficient_history"

    if detector == "UNUSUAL_TIME":
        if elapsed_days >= 28.0 and active_days >= 10:
            return True, "ready"
        return False, "insufficient_history"

    if detector == "DORMANT_REACTIVATED":
        # Needs at least one prior active observation
        if total_obs >= 5:
            return True, "ready"
        return False, "insufficient_history"

    if detector == "RELATIONSHIP_DISAPPEARED":
        if elapsed_days >= 7.0 and total_obs >= 50:
            return True, "ready"
        return False, "insufficient_history"

    return True, "ready"


INCIDENT_COLUMNS = (
    "incident_id", "principal_id", "environment", "category", "scope",
    "started_at", "last_seen_at", "closed_at", "status", "score", "priority",
    "confidence", "family_scores_json", "contributing_event_ids_json",
    "suppressed_contributions_json", "successor_id", "review_notes", "reviewed_by",
    "reviewed_at", "created_at", "updated_at",
)


def insert_incident_version(db, incident: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """Persist a complete replacement row; never issue a ClickHouse mutation."""
    replacement = dict(incident)
    replacement.update(changes)
    columns = ",".join(INCIDENT_COLUMNS)
    placeholders = ",".join("?" for _ in INCIDENT_COLUMNS)
    db.execute(
        f"INSERT INTO incidents ({columns}) VALUES ({placeholders})",
        tuple(replacement.get(column) for column in INCIDENT_COLUMNS),
    )
    return replacement


# -----------------------------------------------------------------------------
# 3. Multi-layer Baselines & Candidate Promotion
# -----------------------------------------------------------------------------

def is_operator_accepted(db, scope_type: str, scope_value: str, current_time_ms: int) -> bool:
    row = db.execute(
        "SELECT 1 FROM operator_overrides WHERE scope_type = ? AND scope_value = ? "
        "AND (expires_at IS NULL OR expires_at > ?)",
        (scope_type, scope_value, current_time_ms)
    ).fetchone()
    return row is not None


def is_dimension_established(db, principal_id: str, dim_type: str, dim_value: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM established_baselines WHERE principal_id = ? AND dimension_type = ? AND dimension_value = ?",
        (principal_id, dim_type, dim_value)
    ).fetchone()
    return row is not None


def record_historical_observation(
    db, principal_id: str, dim_type: str, dim_value: str, timestamp_ms: int
):
    key = f"{dim_type}:{principal_id}:{dim_value}"
    now = int(time.time() * 1000)
    existing = db.execute("SELECT first_seen,last_seen,observation_count,created_at FROM historical_registry FINAL "
                          "WHERE registry_key=?", (key,)).fetchone()
    if existing:
        db.execute("INSERT INTO historical_registry (registry_key,principal_id,dimension_type,dimension_value,"
                   "first_seen,last_seen,observation_count,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (key, principal_id, dim_type, dim_value, min(int(existing[0]), timestamp_ms),
                    max(int(existing[1]), timestamp_ms), int(existing[2]) + 1, int(existing[3]), now))
    else:
        db.execute("INSERT INTO historical_registry (registry_key,principal_id,dimension_type,dimension_value,"
                   "first_seen,last_seen,observation_count,created_at,updated_at) VALUES(?,?,?,?,?,?,1,?,?)",
                   (key, principal_id, dim_type, dim_value, timestamp_ms, timestamp_ms, now, now))


def record_candidate_behavior(
    db, principal_id: str, dim_type: str, dim_value: str, timestamp_ms: int, window_id: int
):
    key = f"{dim_type}:{principal_id}:{dim_value}"
    now = int(time.time() * 1000)
    existing = db.execute("SELECT first_seen,last_seen,distinct_days_count,distinct_windows_count,observation_count,status,created_at "
                          "FROM candidate_behaviors FINAL WHERE candidate_key = ?", (key,)).fetchone()
    if not existing:
        db.execute("""
            INSERT INTO candidate_behaviors (candidate_key, principal_id, dimension_type, dimension_value, first_seen, last_seen, distinct_days_count, distinct_windows_count, observation_count, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1, 1, 'pending', ?, ?)
        """, (key, principal_id, dim_type, dim_value, timestamp_ms, timestamp_ms, now, now))
    else:
        first_s, last_s, days_cnt, win_cnt, obs_cnt = existing[:5]
        new_day = 1 if (timestamp_ms // 86400000) > (last_s // 86400000) else 0
        new_win = 1 if (timestamp_ms // 900000) > (last_s // 900000) else 0
        new_days = days_cnt + new_day
        new_wins = win_cnt + new_win
        new_obs = obs_cnt + 1

        # Promotion rule: Observed on at least 3 distinct days AND present in at least 5 separate windows
        if new_days >= 3 and new_wins >= 5:
            # Promote candidate to established baseline
            base_key = f"{dim_type}:{principal_id}:{dim_value}"
            db.execute("""
                INSERT INTO established_baselines (baseline_key, principal_id, dimension_type, dimension_value, first_seen, last_seen, observation_count, distribution_share, promoted_at, promotion_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0.05, ?, 'Promoted after 3+ days and 5+ windows support', ?, ?)
            """, (base_key, principal_id, dim_type, dim_value, first_s, timestamp_ms, new_obs, now, now, now))
            db.execute("INSERT INTO candidate_behaviors VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (key, principal_id, dim_type, dim_value, first_s, timestamp_ms, new_days, new_wins,
                        new_obs, "promoted", existing[6], now))
        else:
            db.execute("INSERT INTO candidate_behaviors VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (key, principal_id, dim_type, dim_value, first_s, timestamp_ms, new_days, new_wins,
                        new_obs, existing[5], existing[6], now))


# -----------------------------------------------------------------------------
# 4. Incident Lifetime & Capped Scoring Engine
# -----------------------------------------------------------------------------

def get_or_create_incident(
    db, principal_id: str, environment: str, category: str, scope: str, current_time_ms: int,
    incident_cache: Optional[Dict[Tuple[str, str, str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Finds an open incident for this principal + context within 30 minutes of last activity,
    under the 24-hour lifetime cap. If older than 24 hours, marks resolved and starts a successor.
    """
    parts = principal_id.split(":")
    p_name = parts[1] if len(parts) >= 2 else principal_id
    if not p_name or p_name in ("-anonymous-", "unknown", "anonymous", ""):
        return {}

    cache_key = (principal_id, environment, category)
    cached = incident_cache.get(cache_key) if incident_cache is not None else None
    row = cached or db.execute("""
        SELECT * FROM incidents FINAL
        WHERE principal_id = ? AND environment = ? AND category = ? AND status IN ('open', 'investigating')
        ORDER BY started_at DESC LIMIT 1
    """, (principal_id, environment, category)).fetchone()

    now = int(time.time() * 1000)

    if row:
        inc = dict(row)
        # Check if inactive > 30 minutes
        if current_time_ms - inc["last_seen_at"] > 30 * 60 * 1000:
            # Close stale incident
            resolved = dict(inc, status="resolved", closed_at=current_time_ms, updated_at=now)
            if incident_cache is None:
                insert_incident_version(db, resolved)
        # Check if lifetime exceeds 24 hours
        elif current_time_ms - inc["started_at"] >= 24 * 3600 * 1000:
            succ_id = f"inc_{uuid.uuid4().hex[:16]}"
            resolved = dict(inc, status="resolved", closed_at=current_time_ms,
                            successor_id=succ_id, updated_at=now)
            if incident_cache is None:
                insert_incident_version(db, resolved)
            # Create successor
            if incident_cache is None:
                db.execute("""
                INSERT INTO incidents (incident_id, principal_id, environment, category, scope, started_at, last_seen_at, status, score, priority, confidence, family_scores_json, contributing_event_ids_json, suppressed_contributions_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', 0, 'low', 1.0, '{}', '[]', '[]', ?, ?)
                """, (succ_id, principal_id, environment, category, scope, current_time_ms, current_time_ms, now, now))
                return dict(db.execute("SELECT * FROM incidents FINAL WHERE incident_id = ?", (succ_id,)).fetchone())
            successor = {column: None for column in INCIDENT_COLUMNS}
            successor.update({"incident_id": succ_id, "principal_id": principal_id, "environment": environment,
                              "category": category, "scope": scope, "started_at": current_time_ms,
                              "last_seen_at": current_time_ms, "status": "open", "score": 0, "priority": "low",
                              "confidence": 1.0, "family_scores_json": "{}", "contributing_event_ids_json": "[]",
                              "suppressed_contributions_json": "[]", "created_at": now, "updated_at": now})
            incident_cache[cache_key] = successor
            return successor
        else:
            if incident_cache is not None:
                incident_cache[cache_key] = inc
            return inc

    # Create new incident
    new_inc_id = f"inc_{uuid.uuid4().hex[:16]}"
    if incident_cache is None:
        db.execute("""
        INSERT INTO incidents (incident_id, principal_id, environment, category, scope, started_at, last_seen_at, status, score, priority, confidence, family_scores_json, contributing_event_ids_json, suppressed_contributions_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'open', 0, 'low', 1.0, '{}', '[]', '[]', ?, ?)
        """, (new_inc_id, principal_id, environment, category, scope, current_time_ms, current_time_ms, now, now))
        return dict(db.execute("SELECT * FROM incidents FINAL WHERE incident_id = ?", (new_inc_id,)).fetchone())
    created = {column: None for column in INCIDENT_COLUMNS}
    created.update({"incident_id": new_inc_id, "principal_id": principal_id, "environment": environment,
                    "category": category, "scope": scope, "started_at": current_time_ms,
                    "last_seen_at": current_time_ms, "status": "open", "score": 0, "priority": "low",
                    "confidence": 1.0, "family_scores_json": "{}", "contributing_event_ids_json": "[]",
                    "suppressed_contributions_json": "[]", "created_at": now, "updated_at": now})
    incident_cache[cache_key] = created
    return created


def recalculate_incident_score(db, incident_id: str):
    """
    Applies deduplication and capped family scoring:
    family_score = min(family_cap, sum(eligible distinct contributions))
    incident_score = min(100, sum(family_scores))
    """
    events = [dict(r) for r in db.execute(
        "SELECT * FROM principal_change_events WHERE incident_id = ? ORDER BY detected_at ASC", (incident_id,)
    ).fetchall()]

    if not events:
        return

    family_contributions: Dict[str, Dict[str, int]] = {
        "origin": {},
        "access": {},
        "activity": {},
        "identity_mapping": {},
        "authentication": {},
        "audit": {},
        "operational": {},
        "data_quality": {},
    }
    suppressed: List[Dict[str, Any]] = []

    # Track seen changes within this incident to prevent duplicate scoring
    seen_change_values: Set[Tuple[str, str]] = set()
    scored_novelties: Set[str] = set()
    has_failure_burst = False
    has_failure_then_success = False

    for ev in events:
        ctype = ev["change_type"]
        val = ev.get("new_value") or ""
        fam = EVENT_FAMILY.get(ctype, "behavioral")
        base_score = EVENT_SCORES.get(ctype, 0)

        # 1. Deduplication rule: Count same rule and changed value once within an incident
        dedup_key = (ctype, val)
        if dedup_key in seen_change_values:
            suppressed.append({"event_id": ev["id"], "change_type": ctype, "reason": f"Duplicate value '{val}' already scored in this incident"})
            continue
        seen_change_values.add(dedup_key)

        # 2. Logical relationship rule: Do not score NEW_RELATIONSHIP when a scored new caller, target, or operation already explains it
        if ctype == "NEW_RELATIONSHIP" and ("NEW_CALLER" in scored_novelties or "NEW_TARGET" in scored_novelties or "NEW_OPERATION" in scored_novelties):
            suppressed.append({"event_id": ev["id"], "change_type": ctype, "reason": "Explained by newly scored constituent dimension (caller/target/op)"})
            continue

        # 3. Authentication rule: When FAILURE_THEN_SUCCESS includes the same failure burst, retain both explanations but score the stronger contribution
        if ctype == "AUTH_FAILURE_BURST":
            has_failure_burst = True
            if has_failure_then_success:
                suppressed.append({"event_id": ev["id"], "change_type": ctype, "reason": "Subsumed by stronger FAILURE_THEN_SUCCESS contribution"})
                continue
        elif ctype == "FAILURE_THEN_SUCCESS":
            has_failure_then_success = True
            if has_failure_burst and "AUTH_FAILURE_BURST" in family_contributions["authentication"]:
                # Remove AUTH_FAILURE_BURST contribution in favor of FAILURE_THEN_SUCCESS (35 vs 30)
                del family_contributions["authentication"]["AUTH_FAILURE_BURST"]
                suppressed.append({"event_id": ev["id"], "change_type": "AUTH_FAILURE_BURST", "reason": "Replaced by stronger FAILURE_THEN_SUCCESS contribution"})

        # 4. IP Attribution Confidence rule:
        # Known or likely load balancer IP -> suppressed or low weight
        # High confidence client IP -> meaningful
        if ctype in {"NEW_SOURCE_IP", "SOURCE_IP_DISTRIBUTION_SHIFT", "NEW_IP_CALLER_PAIR"}:
            reason_raw = ev.get("reason_json") or ev.get("reason") or {}
            if isinstance(reason_raw, str):
                try:
                    reason_data = json.loads(reason_raw)
                except Exception:
                    reason_data = {}
            elif isinstance(reason_raw, dict):
                reason_data = reason_raw
            else:
                reason_data = {}

            role = reason_data.get("source_ip_role")
            conf = reason_data.get("attribution_confidence")
            if not role and ev.get("source_ip"):
                from backend.app.services.normalization import classify_source_ip_role
                role, _, conf = classify_source_ip_role(ev.get("source_ip"))

            if role == "load_balancer" or conf == "low":
                base_score = 0
                suppressed.append({"event_id": ev["id"], "change_type": ctype, "reason": "Likely load balancer / hop address; suppressed from security score"})
            elif conf == "medium":
                base_score = 5

        if base_score > 0:
            family_contributions[fam][f"{ctype}:{val}"] = base_score
            if ctype in {"NEW_CALLER", "NEW_TARGET", "NEW_OPERATION"}:
                scored_novelties.add(ctype)

    # Compute family scores with caps
    family_scores = {}
    for fam, items in family_contributions.items():
        raw_sum = sum(items.values())
        cap = FAMILY_CAPS.get(fam, 30)
        family_scores[fam] = min(cap, raw_sum)

    total_score = min(100, sum(family_scores.values()))
    priority = investigation_priority(total_score)
    now = int(time.time() * 1000)

    current = db.execute("SELECT * FROM incidents FINAL WHERE incident_id = ?", (incident_id,)).fetchone()
    if current:
        insert_incident_version(
            db, dict(current), score=total_score, priority=priority,
            family_scores_json=json.dumps(family_scores, separators=(',', ':')),
            suppressed_contributions_json=json.dumps(suppressed, separators=(',', ':')),
            contributing_event_ids_json=json.dumps([e["id"] for e in events], separators=(',', ':')),
            updated_at=now,
        )


# -----------------------------------------------------------------------------
# 5. Emission with 7-Question Explainability
# -----------------------------------------------------------------------------

def emit_behavioral_change(
    db,
    *,
    principal_id: str,
    change_type: str,
    detected_at: int,
    caller_service: str = "",
    source_ip: str = "",
    target_service: str = "",
    operation: str = "",
    old_value: str = "",
    new_value: str = "",
    baseline_window_desc: str = "available historical baseline",
    expected_range: str = "not previously observed",
    sample_count: int = 0,
    active_days: int = 0,
    attribution_method: str = "trace_linked",
    collection_quality: str = "healthy",
    representative_traces: Optional[List[str]] = None,
    custom_summary: Optional[str] = None,
    category_override: Optional[str] = None,
    _incident_cache: Optional[Dict[Tuple[str, str, str], dict[str, Any]]] = None,
    _event_rows: Optional[List[tuple]] = None,
    _override_cache: Optional[Dict[str, bool]] = None,
    _defer_incident_score: bool = False,
) -> int:
    """Emits an explainable Behavioral Change Event and links it to an active Incident."""
    fam = EVENT_FAMILY.get(change_type, "behavioral")
    category = category_override or ("authentication" if fam == "authentication" else "audit" if fam == "audit" else "operational" if fam == "operational" else "data_quality" if fam == "data_quality" else "behavioral")
    base_imp = BASE_IMPORTANCE.get(change_type, "low")
    base_pts = EVENT_SCORES.get(change_type, 0)

    parts = principal_id.split(":")
    environment = parts[0] if len(parts) >= 2 else "production"
    principal_name = parts[1] if len(parts) >= 2 else principal_id

    if not principal_name or principal_name in ("-anonymous-", "unknown", "anonymous", ""):
        return 0

    # Check operator override
    scope_key = f"{principal_id}|{change_type}|{new_value}"
    accepted = (_override_cache.get(scope_key) if _override_cache is not None and scope_key in _override_cache
                else is_operator_accepted(db, "change_rule", scope_key, detected_at))
    if _override_cache is not None:
        _override_cache[scope_key] = accepted
    if accepted:
        return 0

    # Format plain-language 7 questions
    summary_text = custom_summary or f"{change_type.replace('_', ' ').title()}: {new_value or principal_name}"
    explanation = {
        "what_changed": summary_text,
        "compared_with": f"This entity was not observed for the principal during the {baseline_window_desc} (baseline range: {expected_range}, sample count: {sample_count}, active days: {active_days}).",
        "where": {
            k: v for k, v in {
                "principal": principal_name,
                "principal_id": principal_id,
                "caller": caller_service,
                "source": source_ip,
                "target": target_service,
                "operation": operation,
            }.items() if v and v != "unknown"
        },
        "how_reliable": {
            "attribution_method": attribution_method,
            "collection_quality": collection_quality,
            "baseline_readiness": "ready",
        },
        "why_priority": {
            "base_importance": base_imp,
            "base_points": base_pts,
            "family": fam,
            "family_cap": FAMILY_CAPS.get(fam, 30),
        },
        "what_proves_it": {
            "first_observed": detected_at,
            "last_observed": detected_at,
            "representative_traces": representative_traces or [],
        },
        "what_happened_afterward": "Under active investigation; evaluating operational context.",
    }

    # Bounded Incident linking
    incident = get_or_create_incident(
        db,
        principal_id=principal_id,
        environment=environment,
        category=category,
        scope=f"{target_service or 'global'}:{caller_service or 'direct'}",
        current_time_ms=detected_at,
        incident_cache=_incident_cache,
    )
    incident_id = incident["incident_id"]

    identity = "|".join((principal_id, change_type, caller_service, source_ip, target_service, operation, str(detected_at // 900_000)))
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()
    now = int(time.time() * 1000)
    event_id = (int(hashlib.sha256(fingerprint.encode()).hexdigest()[:15], 16) % 9000000000000000) + 1

    event_values = (
        event_id, fingerprint, principal_name, change_type, base_imp, base_pts, detected_at,
        caller_service or None, source_ip or None, target_service or None, operation or None,
        old_value or None, new_value or None, detected_at,
        json.dumps(explanation, separators=(',', ':')), now,
        incident_id, principal_id, environment, base_imp, category, fam, attribution_method
    )
    if _event_rows is None:
        db.execute("""
      INSERT INTO principal_change_events (
        id, fingerprint, principal_name, change_type, severity, score, detected_at,
        caller_service, source_ip, target_service, operation, old_value, new_value,
        first_observed, reason_json, status, updated_at, incident_id, principal_id,
        environment, base_importance, category, family, reliability
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?, ?, ?, ?)
        """, event_values)
    else:
        _event_rows.append((*event_values[:15], "new", *event_values[15:]))

    # Update incident last_seen_at and recalculate score
    incident.update(last_seen_at=max(int(incident["last_seen_at"]), detected_at), updated_at=now)
    if not _defer_incident_score:
        insert_incident_version(db, incident)
        recalculate_incident_score(db, incident_id)

    if _event_rows is not None:
        return event_id
    event_id_row = db.execute("SELECT id FROM principal_change_events WHERE fingerprint = ?", (fingerprint,)).fetchone()
    return event_id_row[0] if (event_id_row and event_id_row[0]) else event_id

# -----------------------------------------------------------------------------
# 6. Advanced Behavioral Detectors & Telemetry Gates
# -----------------------------------------------------------------------------

def detect_telemetry_quality_gates(db, window_start_ms: int, window_end_ms: int) -> dict[str, Any]:
    """
    Evaluates telemetry health in the window:
    - Collection gap: 0 requests during normally active periods
    - Caller linkage rate: fraction of server spans with reliable caller attribution
    - Username extraction rate: fraction of requests with known principal
    """
    total_spans = db.execute(
        "SELECT COUNT(*) FROM traces WHERE timestamp_ms >= ? AND timestamp_ms < ?",
        (window_start_ms, window_end_ms)
    ).fetchone()[0]

    if total_spans == 0:
        return {
            "is_gap": True,
            "caller_linkage_rate": 0.0,
            "username_rate": 0.0,
            "sampling_ratio": 1.0,
        }

    linked_callers = db.execute(
        "SELECT COUNT(*) FROM traces WHERE timestamp_ms >= ? AND timestamp_ms < ? "
        "AND caller_service IS NOT NULL AND caller_service NOT IN ('', 'unknown')",
        (window_start_ms, window_end_ms)
    ).fetchone()[0]

    extracted_users = db.execute(
        "SELECT COUNT(*) FROM traces WHERE timestamp_ms >= ? AND timestamp_ms < ? "
        "AND principal_name IS NOT NULL AND principal_name NOT IN ('', 'unknown')",
        (window_start_ms, window_end_ms)
    ).fetchone()[0]

    caller_linkage_rate = linked_callers / float(total_spans)
    username_rate = extracted_users / float(total_spans)

    now = int(time.time() * 1000)
    db.execute("""
        INSERT OR REPLACE INTO telemetry_quality_windows (
            window_start_sec, window_end_sec, total_spans, counted_requests,
            caller_linked_count, caller_linkage_rate, username_extracted_count,
            username_extraction_rate, is_collection_gap, sampling_ratio, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1.0, ?)
    """, (window_start_ms // 1000, window_end_ms // 1000, total_spans, total_spans,
          linked_callers, caller_linkage_rate, extracted_users, username_rate, now))

    return {
        "is_gap": False,
        "caller_linkage_rate": caller_linkage_rate,
        "username_rate": username_rate,
        "sampling_ratio": 1.0,
    }


def detect_operation_mix_shift(
    db, principal_id: str, target_service: str, window_start_ms: int, window_end_ms: int
) -> Optional[int]:
    """
    Compares operation shares for each principal + target against comparable historical windows.
    Guard: >= 100 current observations; flag supported share increase >= 20 percentage points.
    """
    ready, _ = evaluate_readiness(db, principal_id, "OPERATION_MIX_SHIFT", window_end_ms)
    if not ready:
        return None

    # Current window operations for this principal + target
    current_rows = db.execute("""
        SELECT operation_key, COUNT(*) as cnt
        FROM traces
        WHERE principal_id = ? AND target_service = ?
          AND timestamp_ms >= ? AND timestamp_ms < ?
        GROUP BY operation_key
    """, (principal_id, target_service, window_start_ms, window_end_ms)).fetchall()

    current_total = sum(r[1] for r in current_rows)
    if current_total < 100:
        return None

    # Historical baseline shares (prior to current window)
    hist_rows = db.execute("""
        SELECT operation_key, COUNT(*) as cnt
        FROM traces
        WHERE principal_id = ? AND target_service = ? AND timestamp_ms < ?
        GROUP BY operation_key
    """, (principal_id, target_service, window_start_ms)).fetchall()

    hist_total = sum(r[1] for r in hist_rows)
    if hist_total < 200:
        return None

    hist_shares = {r[0]: (r[1] / float(hist_total)) for r in hist_rows}

    for op_key, cur_cnt in current_rows:
        cur_share = cur_cnt / float(current_total)
        base_share = hist_shares.get(op_key, 0.0)
        # Shift >= 20 percentage points (0.20)
        if cur_share >= (base_share + 0.20) and cur_cnt >= 25:
            delta_pct = round((cur_share - base_share) * 100, 1)
            traces = [r[0] for r in db.execute(
                "SELECT trace_id FROM traces WHERE principal_id = ? AND target_service = ? AND operation_key = ? AND timestamp_ms >= ? LIMIT 3",
                (principal_id, target_service, op_key, window_start_ms)
            ).fetchall()]

            return emit_behavioral_change(
                db,
                principal_id=principal_id,
                change_type="OPERATION_MIX_SHIFT",
                detected_at=window_end_ms,
                target_service=target_service,
                operation=op_key,
                old_value=f"historical share {round(base_share*100, 1)}%",
                new_value=f"current share {round(cur_share*100, 1)}% (+{delta_pct}%)",
                expected_range=f"0–{round(base_share*100, 1)}%",
                sample_count=hist_total,
                active_days=int((window_end_ms - window_start_ms) // 86400000) or 1,
                attribution_method="trace_linked",
                representative_traces=traces,
                custom_summary=f"Operation mix changed: {op_key} surged to {round(cur_share*100, 1)}% of requests on {target_service} (baseline was {round(base_share*100, 1)}%)"
            )
    return None


def detect_caller_principal_switch(
    db, caller_service: str, target_service: str, operation_key: str,
    window_start_ms: int, window_end_ms: int
) -> Optional[int]:
    """
    Learns principal distribution for caller + target + operation.
    Detects an unexpected principal gaining material share when a familiar caller changes credentials.
    """
    if not caller_service or caller_service == "unknown":
        return None

    # Current window identities for this caller + target + operation
    current_rows = db.execute("""
        SELECT principal_id, principal_name, COUNT(*) as cnt
        FROM traces
        WHERE caller_service = ? AND target_service = ? AND operation_key = ?
          AND timestamp_ms >= ? AND timestamp_ms < ?
          AND principal_name IS NOT NULL AND principal_name NOT IN ('unknown', '-anonymous-', 'anonymous', '')
        GROUP BY principal_id, principal_name
    """, (caller_service, target_service, operation_key, window_start_ms, window_end_ms)).fetchall()

    if not current_rows:
        return None

    # Historical dominant identity
    hist_rows = db.execute("""
        SELECT principal_id, COUNT(*) as cnt
        FROM traces
        WHERE caller_service = ? AND target_service = ? AND operation_key = ?
          AND timestamp_ms < ? AND principal_name IS NOT NULL AND principal_name NOT IN ('unknown', '-anonymous-', 'anonymous', '')
        GROUP BY principal_id ORDER BY cnt DESC
    """, (caller_service, target_service, operation_key, window_start_ms)).fetchall()

    hist_total = sum(r[1] for r in hist_rows)
    if hist_total < 100:
        return None

    usual_principal_id = hist_rows[0][0]
    usual_share = hist_rows[0][1] / float(hist_total)

    # If the historical pattern was strongly dominated by one principal (>= 80% share)
    if usual_share >= 0.80:
        for cur_pid, cur_pname, cur_cnt in current_rows:
            if cur_pid != usual_principal_id and cur_cnt >= 10:
                traces = [r[0] for r in db.execute(
                    "SELECT trace_id FROM traces WHERE caller_service = ? AND target_service = ? AND principal_id = ? AND timestamp_ms >= ? LIMIT 3",
                    (caller_service, target_service, cur_pid, window_start_ms)
                ).fetchall()]

                return emit_behavioral_change(
                    db,
                    principal_id=cur_pid,
                    change_type="CALLER_PRINCIPAL_SWITCH",
                    detected_at=window_end_ms,
                    caller_service=caller_service,
                    target_service=target_service,
                    operation=operation_key,
                    old_value=f"usual principal: {usual_principal_id.split(':')[-1]} ({round(usual_share*100)}%)",
                    new_value=f"switched to: {cur_pname} ({cur_cnt} requests)",
                    expected_range=f"{round(usual_share*100)}% dominant {usual_principal_id.split(':')[-1]}",
                    sample_count=hist_total,
                    attribution_method="caller_trace_parent",
                    representative_traces=traces,
                    custom_summary=f"Caller principal switch: {caller_service} calling {target_service} presenting novel identity '{cur_pname}' instead of established '{usual_principal_id.split(':')[-1]}'"
                )
    return None


def detect_target_fanout_surge(
    db, principal_id: str, window_start_ms: int, window_end_ms: int
) -> Optional[int]:
    """
    Counts distinct targets per principal per window.
    Requires >= 3 targets and count above historical upper range and multiple of usual count.
    """
    ready, _ = evaluate_readiness(db, principal_id, "TARGET_FANOUT_SURGE", window_end_ms)
    if not ready:
        return None

    cur_targets = db.execute("""
        SELECT COUNT(DISTINCT target_service)
        FROM traces
        WHERE principal_id = ? AND timestamp_ms >= ? AND timestamp_ms < ?
    """, (principal_id, window_start_ms, window_end_ms)).fetchone()[0]

    if cur_targets < 3:
        return None

    # Historical median and max targets per 15-minute window
    hist_counts = [r[0] for r in db.execute("""
        SELECT COUNT(DISTINCT target_service) as cnt
        FROM traces
        WHERE principal_id = ? AND timestamp_ms < ?
        GROUP BY (timestamp_ms / 900000)
    """, (principal_id, window_start_ms)).fetchall()]

    if len(hist_counts) < 10:
        return None

    hist_counts.sort()
    hist_median = hist_counts[len(hist_counts) // 2]
    hist_max = hist_counts[-1]

    if cur_targets > hist_max and cur_targets >= (hist_median * 2.5):
        return emit_behavioral_change(
            db,
            principal_id=principal_id,
            change_type="TARGET_FANOUT_SURGE",
            detected_at=window_end_ms,
            old_value=f"historical median: {hist_median} targets (max: {hist_max})",
            new_value=f"current window: {cur_targets} distinct targets",
            expected_range=f"1–{hist_max} targets",
            sample_count=len(hist_counts),
            attribution_method="trace_linked",
            custom_summary=f"Target fanout surge: principal contacted {cur_targets} distinct services in window (historical normal: {hist_median})"
        )
    return None


def detect_source_fanout_surge(
    db, principal_id: str, window_start_ms: int, window_end_ms: int
) -> Optional[int]:
    """
    Counts distinct reliable source hosts/groups per principal per window.
    Excludes untrusted forwarded addresses.
    """
    cur_sources = db.execute("""
        SELECT COUNT(DISTINCT source_group)
        FROM traces
        WHERE principal_id = ? AND timestamp_ms >= ? AND timestamp_ms < ?
          AND source_group IS NOT NULL AND source_group != 'other'
    """, (principal_id, window_start_ms, window_end_ms)).fetchone()[0]

    if cur_sources < 3:
        return None

    hist_counts = [r[0] for r in db.execute("""
        SELECT COUNT(DISTINCT source_group)
        FROM traces
        WHERE principal_id = ? AND timestamp_ms < ?
          AND source_group IS NOT NULL AND source_group != 'other'
        GROUP BY (timestamp_ms / 900000)
    """, (principal_id, window_start_ms)).fetchall()]

    if len(hist_counts) < 10:
        return None

    hist_counts.sort()
    hist_median = hist_counts[len(hist_counts) // 2]
    hist_max = hist_counts[-1]

    if cur_sources > hist_max and cur_sources >= (hist_median * 2.0):
        return emit_behavioral_change(
            db,
            principal_id=principal_id,
            change_type="SOURCE_FANOUT_SURGE",
            detected_at=window_end_ms,
            old_value=f"historical median: {hist_median} source groups (max: {hist_max})",
            new_value=f"current window: {cur_sources} distinct source groups",
            expected_range=f"1–{hist_max} sources",
            sample_count=len(hist_counts),
            attribution_method="network_peer",
            custom_summary=f"Source fanout surge: principal presented from {cur_sources} distinct source subnets/groups in single window"
        )
    return None


def detect_principal_rate_surge(
    db, principal_id: str, window_start_ms: int, window_end_ms: int
) -> Optional[int]:
    """
    Compares request counts against historical windows of similar time and schedule:
    current_count > p99 AND current_count > 3 * median AND current_count - median >= min_excess.
    """
    ready, _ = evaluate_readiness(db, principal_id, "PRINCIPAL_RATE_SURGE", window_end_ms)
    if not ready:
        return None

    current_count = db.execute("""
        SELECT COUNT(*) FROM traces
        WHERE principal_id = ? AND timestamp_ms >= ? AND timestamp_ms < ?
    """, (principal_id, window_start_ms, window_end_ms)).fetchone()[0]

    if current_count < 50:
        return None

    dt = datetime.fromtimestamp(window_start_ms / 1000, tz=timezone.utc)
    hod = dt.hour

    # Fetch counts for same hour-of-day in past windows
    hist_counts = [r[0] for r in db.execute("""
        SELECT COUNT(*) as cnt FROM traces
        WHERE principal_id = ? AND timestamp_ms < ?
          AND CAST(strftime('%H', timestamp_ms/1000, 'unixepoch') AS INTEGER) = ?
        GROUP BY (timestamp_ms / 900000)
    """, (principal_id, window_start_ms, hod)).fetchall()]

    if len(hist_counts) < 5:
        return None

    hist_counts.sort()
    median = hist_counts[len(hist_counts) // 2]
    p99 = hist_counts[int(len(hist_counts) * 0.99)]

    if current_count > p99 and current_count > (3 * max(1, median)) and (current_count - median) >= 50:
        return emit_behavioral_change(
            db,
            principal_id=principal_id,
            change_type="PRINCIPAL_RATE_SURGE",
            detected_at=window_end_ms,
            old_value=f"hourly median {median} reqs/15m (p99: {p99})",
            new_value=f"{current_count} reqs/15m",
            expected_range=f"0–{p99} reqs",
            sample_count=len(hist_counts),
            attribution_method="trace_linked",
            custom_summary=f"Principal rate surge: activity surged to {current_count} reqs/15m (historical median for hour {hod:02d}:00 was {median})"
        )
    return None


def detect_explicit_auth_anomalies(
    db, principal_id: str, window_start_ms: int, window_end_ms: int
) -> List[int]:
    """
    Detects explicit authentication anomalies:
    - AUTH_FAILURE_BURST: >= 5 explicit auth failures in window
    - FAILURE_THEN_SUCCESS: Explicit failure followed by explicit success in same window
    """
    p_name = principal_id.split(":")[-1] if ":" in principal_id else principal_id
    if not p_name or p_name in ("-anonymous-", "unknown", "anonymous", ""):
        return []

    events_emitted = []

    # Check explicit auth failure count
    failures = db.execute("""
        SELECT caller_service, caller_ip, target_service, auth_evidence, COUNT(*) as cnt, MIN(timestamp_ms), MAX(timestamp_ms)
        FROM traces
        WHERE principal_id = ? AND auth_result = 'failure'
          AND timestamp_ms >= ? AND timestamp_ms < ?
        GROUP BY caller_service, caller_ip, target_service, auth_evidence
    """, (principal_id, window_start_ms, window_end_ms)).fetchall()

    for caller, ip, target, evidence, cnt, first_ts, last_ts in failures:
        if cnt >= 5:
            traces = [r[0] for r in db.execute(
                "SELECT trace_id FROM traces WHERE principal_id = ? AND auth_result = 'failure' AND timestamp_ms >= ? LIMIT 3",
                (principal_id, window_start_ms)
            ).fetchall()]

            # Check if followed by explicit success
            success_after = db.execute("""
                SELECT COUNT(*) FROM traces
                WHERE principal_id = ? AND auth_result = 'success'
                  AND timestamp_ms > ? AND timestamp_ms < ?
            """, (principal_id, last_ts, window_end_ms)).fetchone()[0]

            if success_after > 0:
                ev_id = emit_behavioral_change(
                    db,
                    principal_id=principal_id,
                    change_type="FAILURE_THEN_SUCCESS",
                    detected_at=window_end_ms,
                    caller_service=caller or "",
                    source_ip=ip or "",
                    target_service=target,
                    old_value=f"{cnt} explicit failures ({evidence})",
                    new_value=f"subsequent explicit success ({success_after} requests)",
                    expected_range="normal authorized access without prior bursts",
                    attribution_method="explicit_security_event",
                    representative_traces=traces,
                    custom_summary=f"Explicit auth failure burst ({cnt} failures) followed by successful authentication for principal '{principal_id.split(':')[-1]}'"
                )
                if ev_id:
                    events_emitted.append(ev_id)
            else:
                ev_id = emit_behavioral_change(
                    db,
                    principal_id=principal_id,
                    change_type="AUTH_FAILURE_BURST",
                    detected_at=window_end_ms,
                    caller_service=caller or "",
                    source_ip=ip or "",
                    target_service=target,
                    old_value="0 authentication failures",
                    new_value=f"{cnt} explicit authentication failures ({evidence})",
                    expected_range="0 failures",
                    attribution_method="explicit_security_event",
                    representative_traces=traces,
                    custom_summary=f"Authentication failure burst: {cnt} explicit security failures recorded for principal '{principal_id.split(':')[-1]}'"
                )
                if ev_id:
                    events_emitted.append(ev_id)

    return events_emitted
