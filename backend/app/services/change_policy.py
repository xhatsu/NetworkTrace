"""Conservative, evidence-gated episode impact policy (no notification side effects)."""
from __future__ import annotations

import math
from typing import Any


def _number(value: Any) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def evaluate_episode(signals: list[dict[str, Any]]) -> dict[str, Any]:
    # Imported lazily because normalization and the shadow v1 evaluator share helpers.
    from backend.app.services.change_episodes import (
        _is_infrastructure_ip_signal, _json_value, _signal_domain, _signal_type,
    )

    types = {_signal_type(s) for s in signals}
    domains = sorted({_signal_domain(t) for t in types})
    infrastructure_only = bool(signals) and all(_is_infrastructure_ip_signal(s) for s in signals)
    all_expected = bool(signals) and all(str(s.get("raw_status", "")).lower() == "expected" for s in signals)
    state = "changed"
    reasons = ["Novelty alone does not demonstrate operational or security impact."]
    gates: list[dict[str, Any]] = []
    metric_types = {"ERROR_RATE", "LATENCY", "TRAFFIC_SPIKE", "TRAFFIC_DROP", "PRINCIPAL_RATE_SURGE", "GRAPH_TPS_SHIFT", "GRAPH_EDGE_NOVELTY"}
    behavioral_types = {"AUTH_FAILURE_BURST", "FAILURE_THEN_SUCCESS", "SOURCE_IDENTITY_FANOUT",
                        "OPERATION_MIX_SHIFT", "CALLER_PRINCIPAL_SWITCH", "TARGET_FANOUT_SURGE", "SOURCE_FANOUT_SURGE"}
    ranks = {"changed": 0, "watch": 1, "needs_attention": 2, "critical": 3}
    for signal in signals:
        kind = _signal_type(signal)
        raw = signal.get("signal") or {}
        meta = raw.get("metadata") or _json_value(raw.get("metadata_json"), {})
        if not isinstance(meta, dict):
            meta = {}
        # Only explicit window evidence counts. Occurrence counters can include retries.
        buckets = meta.get("abnormal_bucket_starts_ms", [])
        buckets = sorted({int(v) for v in buckets if isinstance(v, int) and not isinstance(v, bool) and v >= 0 and v % 300_000 == 0}) if isinstance(buckets, list) else []
        current_bucket = meta.get("observation_bucket_start_ms")
        persistent = isinstance(current_bucket, int) and current_bucket in buckets and len({b for b in buckets if current_bucket - 600_000 <= b <= current_bucket}) >= 2
        ready = _number(meta.get("baseline_sample_count")) >= 6
        requests = _number(meta.get("total_requests"))
        errors = _number(meta.get("total_errors"))
        current = _number(raw.get("current_value"))
        baseline = _number(raw.get("baseline_value"))
        material = False
        severe = False
        if kind == "ERROR_RATE":
            material = requests >= 100 and errors >= 20 and current - baseline >= 5
            severe = requests >= 200 and errors >= 100 and current >= 50
        elif kind == "LATENCY":
            material = requests >= 100 and current >= 500 and current - baseline >= 200
            severe = requests >= 200 and current >= 5000
        elif kind == "TRAFFIC_DROP":
            # Missing telemetry is not proof of a service outage.
            material = baseline >= 1 and current <= baseline * .25 and meta.get("telemetry_healthy") is True
            severe = material and current <= baseline * .05
        elif kind in {"TRAFFIC_SPIKE", "PRINCIPAL_RATE_SURGE"}:
            # Increased demand alone is not harm. Capacity evidence must be explicit.
            material = requests >= 300 and meta.get("capacity_impact_confirmed") is True
        candidate = "watch" if kind in metric_types | behavioral_types else "changed"
        if material and ready and persistent:
            candidate = "critical" if severe else "needs_attention"
        reason = raw.get("reason") or _json_value(raw.get("reason_json"), {})
        reason = reason if isinstance(reason, dict) else {}
        auth = reason.get("impact_evidence") or {}
        reliability = reason.get("how_reliable") or {}
        if isinstance(auth, dict) and isinstance(reliability, dict) and (
            reliability.get("attribution_method") == "explicit_security_event"
            and reliability.get("collection_quality") == "healthy"
        ):
            failures = _number(auth.get("explicit_auth_failures"))
            if kind == "AUTH_FAILURE_BURST" and failures >= 50:
                candidate = "needs_attention"
            if kind == "FAILURE_THEN_SUCCESS" and failures >= 20 and _number(auth.get("same_scope_successes")) >= 1:
                candidate = "needs_attention"
        # Immediate bypass is limited to measured high-volume, near-total failure.
        if kind == "ERROR_RATE" and requests >= 1000 and errors >= 900 and current >= 90 and current - baseline >= 5:
            candidate = "critical"
        gates.append({"type": kind, "baseline_ready": ready, "persistent": persistent,
                      "material_impact": material, "level": candidate})
        if ranks[candidate] > ranks[state]:
            state = candidate
            reasons = {
                "watch": ["Deviation observed; sufficient persistence, baseline, or impact evidence is not yet available."],
                "needs_attention": ["Measured impact passed the persistence/baseline gate or explicit, scoped authentication evidence warrants investigation."],
                "critical": ["Measured severe impact meets the critical evidence gate."],
            }[state]
    if infrastructure_only:
        state = "changed"
        reasons = ["Only infrastructure or low-confidence source-IP attribution changed."]
    impact_level = state
    # Keep the legacy state for API compatibility; expose disposition separately.
    if all_expected:
        state = "expected"
        reasons = ["An operator explicitly accepted all source findings as expected."]
    return {"state": state, "is_abnormal": state in {"needs_attention", "critical"},
            "correlated": len(types) > 1, "infrastructure_only": infrastructure_only,
            "domains": domains, "reasons": reasons, "evaluation_version": "episode-v2",
            "impact_level": impact_level,
            "confidence": "established" if gates and all(g["baseline_ready"] for g in gates) else "limited",
            "disposition": "expected" if all_expected else "unreviewed", "gates": gates}
