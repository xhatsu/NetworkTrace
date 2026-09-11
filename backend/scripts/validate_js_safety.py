#!/usr/bin/env python3
"""
Validates API payloads against frontend TypeScript contracts to detect any potential
JavaScript runtime errors (.toFixed on undefined, .length on undefined, .map on undefined, etc.)
"""
import sys
import json

def check_payload(endpoint, data):
    errors = []

    if endpoint.startswith("/api/v1/services/") and endpoint.endswith("/users"):
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            errors.append("Expected 'items' array for service users")

    elif endpoint == "/api/agent/stats":
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            errors.append("Expected 'items' array for fleet agent stats")

    elif endpoint.startswith("/api/agent/stats/") and endpoint.endswith("/history"):
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            errors.append("Expected 'items' array for agent history")

    elif endpoint.startswith("/api/agent/stats/"):
        if not isinstance(data, dict):
            errors.append("Expected dict root for agent node detail")

    elif endpoint.startswith("/api/v1/anomalies/") and endpoint.endswith("/users"):
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            errors.append("Expected 'items' array for anomaly users")

    elif endpoint == "/api/v1/users":
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            errors.append("Expected 'items' array in users response")
        for item in data.get("items", []) if isinstance(data, dict) else []:
            if not item.get("principal_name"):
                errors.append("User inventory item missing principal_name")

    elif endpoint == "/api/v1/users/summary":
        if not isinstance(data, dict):
            errors.append("Expected dict for user summary")

    elif endpoint.startswith("/api/v1/users/"):
        if not isinstance(data, dict):
            errors.append("Expected dict for user profile response")
        elif endpoint.endswith(("/timeline", "/changes", "/callers", "/sources", "/targets", "/operations")):
            if not isinstance(data.get("items"), list):
                errors.append("Expected 'items' array for user detail collection")
        elif not data.get("principal_name"):
            errors.append("User profile missing principal_name")

    elif endpoint == "/api/v1/user-changes":
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            errors.append("Expected 'items' array in user changes response")

    elif endpoint.startswith("/api/v1/user-graph"):
        if not isinstance(data, dict):
            errors.append("Expected dict for user graph")
        else:
            for key in ["nodes", "edges"]:
                if not isinstance(data.get(key), list):
                    errors.append(f"User graph '{key}' must be list")

    elif endpoint == "/api/v1/user-analytics":
        if not isinstance(data, dict):
            errors.append("Expected dict for user analytics")

    elif endpoint == "/api/v1/overview":
        if not isinstance(data, dict):
            errors.append("Expected dict root")
        else:
            for k in ["kpis", "series", "top_services", "top_principals", "recent_anomalies"]:
                if k not in data:
                    errors.append(f"Missing key in overview: {k}")
            for a in data.get("recent_anomalies", []):
                if a.get("percent_change") is None and a.get("delta_percentage") is None and a.get("absolute_difference") is None:
                    errors.append(f"Anomaly missing change metric: {a}")

    elif endpoint == "/api/v1/anomalies":
        items = data.get("items")
        if not isinstance(items, list):
            errors.append("Expected 'items' array in anomalies response")
        else:
            for i, a in enumerate(items[:20]):
                if "percent_change" not in a and "delta_percentage" not in a:
                    errors.append(f"Item {i} missing percent_change and delta_percentage")
                if "absolute_difference" not in a and "current_value" not in a:
                    errors.append(f"Item {i} missing absolute_difference")

    elif endpoint.startswith("/api/v1/anomalies/"):
        if not isinstance(data, dict):
            errors.append("Expected dict for anomaly detail")
        else:
            for req_list in ["limitations", "trace_ids"]:
                val = data.get(req_list)
                if not isinstance(val, list):
                    errors.append(f"Anomaly detail '{req_list}' must be list, got {type(val).__name__}")
            for req_ts in ["window_start_ms", "window_end_ms"]:
                if req_ts not in data or data[req_ts] is None:
                    errors.append(f"Anomaly detail missing timestamp window: {req_ts}")
            rc = data.get("root_cause")
            if rc and isinstance(rc, dict) and "confidence_score" in rc:
                conf = rc["confidence_score"]
                if conf is not None and not isinstance(conf, (int, float)):
                    errors.append(f"confidence_score is not numeric: {conf}")

    elif endpoint == "/api/v1/services":
        items = data.get("items")
        if not isinstance(items, list):
            errors.append("Expected 'items' array in services response")
        else:
            for i, s in enumerate(items):
                if "name" not in s:
                    errors.append(f"Service {i} missing 'name'")
                for num_key in ["p95_ms", "error_rate", "rps"]:
                    v = s.get(num_key)
                    if v is not None and not isinstance(v, (int, float)):
                        errors.append(f"Service {s.get('name')} {num_key} not numeric: {v}")

    elif endpoint.startswith("/api/v1/services/"):
        if not isinstance(data, dict):
            errors.append("Expected dict for service detail")
        else:
            for req_list in ["operations", "callers", "dependencies", "instances"]:
                val = data.get(req_list)
                if not isinstance(val, list):
                    errors.append(f"Service detail '{req_list}' must be list, got {type(val).__name__}")
            for op in data.get("operations", []):
                for num_key in ["p95_ms", "failure_rate", "requests"]:
                    v = op.get(num_key)
                    if v is not None and not isinstance(v, (int, float)):
                        errors.append(f"Operation {op.get('name')} {num_key} not numeric: {v}")

    elif endpoint == "/api/v1/principals":
        items = data.get("items")
        if not isinstance(items, list):
            errors.append("Expected 'items' array in principals response")
        else:
            for i, p in enumerate(items):
                if "principal_name" not in p:
                    errors.append(f"Principal {i} missing 'principal_name'")
                for num_key in ["p95_latency", "error_rate", "total_requests"]:
                    v = p.get(num_key)
                    if v is not None and not isinstance(v, (int, float)):
                        errors.append(f"Principal {p.get('principal_name')} {num_key} not numeric: {v}")

    elif endpoint.startswith("/api/v1/principals/"):
        if not isinstance(data, dict):
            errors.append("Expected dict for principal detail")
        else:
            for req_list in ["targets", "operations", "callers", "hourly_profile"]:
                val = data.get(req_list)
                if not isinstance(val, list):
                    errors.append(f"Principal detail '{req_list}' must be list, got {type(val).__name__}")
            for t in data.get("targets", []):
                for num_key in ["p95_latency", "error_rate", "requests"]:
                    v = t.get(num_key)
                    if v is not None and not isinstance(v, (int, float)):
                        errors.append(f"Target {t.get('target_service')} {num_key} not numeric: {v}")
            for o in data.get("operations", []):
                for num_key in ["p95_latency", "error_rate", "requests"]:
                    v = o.get(num_key)
                    if v is not None and not isinstance(v, (int, float)):
                        errors.append(f"Operation {o.get('operation')} {num_key} not numeric: {v}")

    elif endpoint == "/api/v1/topology":
        if not isinstance(data, dict):
            errors.append("Expected dict for topology")
        else:
            for req_list in ["nodes", "edges"]:
                val = data.get(req_list)
                if not isinstance(val, list):
                    errors.append(f"Topology '{req_list}' must be list, got {type(val).__name__}")
            for edge in data.get("edges", []):
                for num_key in ["p95_ms", "error_rate", "traffic"]:
                    v = edge.get(num_key)
                    if v is not None and not isinstance(v, (int, float)):
                        errors.append(f"Edge {num_key} not numeric: {v}")

    elif endpoint == "/api/v1/traces":
        items = data.get("items")
        if not isinstance(items, list):
            errors.append("Expected 'items' array in traces response")
        else:
            for t in items[:20]:
                if "trace_id" not in t:
                    errors.append("Trace missing trace_id")
                v = t.get("duration_ms")
                if v is not None and not isinstance(v, (int, float)):
                    errors.append(f"duration_ms not numeric: {v}")

    elif endpoint.startswith("/api/v1/traces/"):
        if not isinstance(data, dict):
            errors.append("Expected dict for trace detail")
        else:
            spans = data.get("spans")
            if not isinstance(spans, list):
                errors.append(f"Trace detail 'spans' must be list, got {type(spans).__name__}")

    return errors

def main():
    if len(sys.argv) < 2:
        print("Usage: validate_js_safety.py <endpoint>")
        sys.exit(1)
    endpoint = sys.argv[1]
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception as exc:
        print(f"FAIL: Malformed JSON response: {exc}")
        sys.exit(1)
    
    errors = check_payload(endpoint, data)
    if errors:
        print(f"FAIL: {len(errors)} potential JavaScript crash condition(s):")
        for e in errors[:5]:
            print(f"  - {e}")
        sys.exit(2)
    else:
        print("SAFE: All frontend contract fields valid and non-crashing.")
        sys.exit(0)

if __name__ == "__main__":
    main()
