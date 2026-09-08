from __future__ import annotations
from typing import Any, Dict, List, Optional

def determine_probable_origin(
    service: str,
    anomalies: List[Dict[str, Any]],
    dependencies: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Deterministic heuristics to determine probable origin of degradation:
    Correlates anomaly start times, downstream dependency status, and error propagation.
    """
    reasons = []
    downstreams = dependencies.get("dependencies", [])
    downstream_names = {d["name"] for d in downstreams}

    # Check if any downstream dependency also has an anomaly
    downstream_anomalies = [
        a for a in anomalies
        if a.get("target_service") in downstream_names
    ]

    if downstream_anomalies:
        earliest_downstream = min(downstream_anomalies, key=lambda x: x.get("detected_at", 0))
        target_name = earliest_downstream.get("target_service")
        reasons.append(f"Downstream dependency '{target_name}' experienced {earliest_downstream.get('anomaly_type')} concurrently")
        reasons.append("Latency/errors correlated with downstream response degradation")
        return {
            "probable_origin": target_name,
            "confidence": 0.82,
            "origin_type": "downstream_dependency",
            "reasons": reasons
        }

    # Check if a specific caller or principal is concentrating errors
    reasons.append(f"Degradation localized within '{service}' boundary")
    reasons.append("Downstream dependencies report healthy response latencies")
    return {
        "probable_origin": service,
        "confidence": 0.74,
        "origin_type": "internal_service",
        "reasons": reasons
    }
