"""Preserve legacy hub integrations while keeping policy decisions at the API edge."""
from __future__ import annotations

import ipaddress
import json
import logging
import time
from typing import Any, Dict, List
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from backend.config import settings
from backend.app.repositories.db_context import get_connection

log = logging.getLogger("tracescope-hub")
router = APIRouter(tags=["reference_compat"])

_DEFAULT_POLICY: Dict[str, Any] = {
    "users": {"admin": ["*"], "ops": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]},
    "allow": [],
    "default_allow_private": True,
}
_policy_cache: Dict[str, Any] = dict(_DEFAULT_POLICY)


def load_policy() -> Dict[str, Any]:
    global _policy_cache
    try:
        with get_connection() as db:
            row = db.execute(
                "SELECT policy_json FROM security_policy FINAL WHERE policy_key='default' LIMIT 1"
            ).fetchone()
        if row is None:
            return _policy_cache
        d = json.loads(row[0])
        _policy_cache = {
            "users": d.get("users") or {},
            "allow": d.get("allow") or [],
            "default_allow_private": bool(d.get("default_allow_private", True)),
        }
    except Exception as e:
        log.warning("policy load error: %s", e)
    return _policy_cache


def is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def match_rule(rule: str, target: str) -> bool:
    if rule == "*" or rule == target:
        return True
    ip_part, _, port_part = target.rpartition(":")
    if rule.startswith("*:"):
        return rule[2:] == port_part
    try:
        net = ipaddress.ip_network(rule, strict=False)
        return ipaddress.ip_address(ip_part) in net
    except ValueError:
        return False


def is_target_allowed(user: str, target: str) -> bool:
    pol = load_policy()
    ip_part = target.rpartition(":")[0] or target
    for rule in pol.get("allow", []):
        u, _, t = rule.partition("->")
        if u.strip() == user:
            if t.strip() and match_rule(t.strip(), target):
                return True
    rules = pol.get("users", {}).get(user)
    if rules is not None:
        if any(r.strip() == "*" or match_rule(r.strip(), target) for r in rules):
            return True
        return False
    return bool(pol.get("default_allow_private", True) and is_private_ip(ip_part))


def prom_escape(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def qdict(request: Request) -> Dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.url.query).items()}


# =========================================================================
# System Health & Status
# =========================================================================

@router.get("/healthz")
async def healthz() -> Dict[str, Any]:
    return {"ok": True, "telemetry_source": "otel"}


@router.get("/api/otel/status")
async def api_otel_status() -> Dict[str, Any]:
    with get_connection() as conn:
        rollup = conn.execute("""
            SELECT sum(request_count), min(bucket_start)*1000, max(bucket_start+bucket_size)*1000
            FROM metric_buckets FINAL WHERE bucket_size=300
        """).fetchone()
        spans_count = int(rollup[0] or 0) if rollup else 0
        bounds = (rollup[1], rollup[2]) if rollup else (None, None)
        first_seen = bounds[0] if bounds else None
        last_seen = bounds[1] if bounds else None

        svcs_row = conn.execute("SELECT COUNT(DISTINCT target_service) FROM metric_buckets WHERE bucket_size=300").fetchone()
        services_count = int(svcs_row[0]) if (svcs_row and svcs_row[0] is not None) else 0
        nodes_count = services_count or 1

    return {
        "source": "otel",
        "signal": "traces",
        "request_span_kind": "server",
        "request_record_kinds": ["otel_server_span", "elastic_apm_transaction"],
        "spans": spans_count,
        "services": services_count,
        "nodes": nodes_count,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "duplicate_spans_dropped": 0,
        "db_queue_dropped": 0,
        "accepted_formats": [
            "otlp/http-json",
            "otlp/http-protobuf",
            "elastic-apm-7.x-transaction",
        ],
    }


# =========================================================================
# Node & Coverage Ingestion Status
# =========================================================================

@router.get("/api/nodes")
async def api_nodes() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT target_service AS node, max(last_seen_ms) AS last_seen,
                   sum(request_count) AS n_events
            FROM topology_service_edges_5m FINAL
            GROUP BY target_service ORDER BY node
            """
        ).fetchall()
    return {"nodes": [dict(r) for r in rows]}


@router.get("/api/coverage")
async def api_coverage() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT target_service AS host, target_service AS service_id,
                   sum(request_count) AS spans, max(last_seen_ms) AS last_seen
            FROM topology_service_edges_5m FINAL
            GROUP BY target_service
            ORDER BY last_seen DESC
            LIMIT 1000
            """
        ).fetchall()
    return {"source": "otel", "coverage": [dict(r) for r in rows]}


@router.get("/api/users")
async def api_users() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT principal_name AS user, total_requests AS calls, last_seen
            FROM principals FINAL
            ORDER BY calls DESC, user
            """
        ).fetchall()
    return {"users": [dict(r) for r in rows]}


@router.get("/api/rpm")
async def api_rpm(request: Request) -> Dict[str, Any]:
    q = qdict(request)
    win_str = q.get("window", "300")
    try:
        win = max(60, min(int(win_str), 86400))
    except ValueError:
        win = 300

    include_anon = q.get("anon") == "1"
    with get_connection() as conn:
        max_t_row = conn.execute("SELECT MAX(bucket_start) FROM metric_buckets FINAL WHERE bucket_size=300").fetchone()
        now_ts = int(max_t_row[0]) + 300 if (max_t_row and max_t_row[0]) else int(time.time())
        t0 = now_ts - win

        anon_clause = "" if include_anon else " AND principal_name NOT IN ('', '-anonymous-', 'unknown')"
        rows = conn.execute(
            f"""
            SELECT COALESCE(NULLIF(principal_name,''), '-anonymous-') AS u,
                   ROUND(SUM(request_count) / (? / 60.0), 3) AS rpm,
                   SUM(request_count) AS n,
                   MIN(bucket_start) AS first_ts,
                   MAX(bucket_start+bucket_size) AS last_ts
            FROM metric_buckets FINAL
            WHERE bucket_size=300 AND bucket_start>=? {anon_clause}
            GROUP BY u
            ORDER BY rpm DESC
            """,
            (float(win), t0),
        ).fetchall()

    return {"window_sec": win, "rpm": [dict(r) for r in rows]}


@router.get("/api/callers")
async def api_callers() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(caller_service,''), '-') AS caller,
                   COALESCE(NULLIF(principal,''), '-anonymous-') AS user,
                   target_service AS dst_ip, 0 AS dst_port,
                   SUM(request_count) AS calls, MAX(last_seen_ms) AS last_seen
            FROM topology_principal_edges_5m FINAL
            GROUP BY caller,user,dst_ip
            """
        ).fetchall()

    callers: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        caller = row["caller"]
        item = callers.setdefault(
            caller,
            {"caller": caller, "calls": 0, "last_seen": 0, "targets": set(), "users": set()},
        )
        item["calls"] += int(row["calls"] or 0)
        item["last_seen"] = max(item["last_seen"], row["last_seen"] or 0)
        if row["dst_ip"]:
            target = f"{row['dst_ip']}:{row['dst_port']}" if row["dst_port"] else str(row["dst_ip"])
            if len(item["targets"]) < 20:
                item["targets"].add(target)
        if row["user"] not in ("-anonymous-", "unknown") and len(item["users"]) < 10:
            item["users"].add(row["user"])

    out = []
    for item in sorted(callers.values(), key=lambda value: -value["calls"]):
        item["targets"] = sorted(item["targets"])
        item["users"] = sorted(item["users"])
        out.append(item)
    return {"callers": out}


# =========================================================================
# Structured Logs & Kibana Export
# =========================================================================

def _trace_to_log_row(t: Dict[str, Any]) -> Dict[str, Any]:
    ts_ms = int(t.get("timestamp_ms") or 0)
    ts = ts_ms / 1000
    ts_us = ts_ms * 1000

    try:
        timestamp_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + f".{(ts_us % 1000000):06d}Z"
    except Exception:
        timestamp_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))

    principal = t.get("principal_name") or "-anonymous-"
    if principal == "unknown":
        principal = "-anonymous-"

    return {
        "client_ip": t.get("source_ip") or t.get("caller_service"),
        "origin_client_ip": t.get("source_ip") or t.get("caller_service"),
        "immediate_peer": t.get("source_ip") or t.get("caller_service"),
        "@timestamp": timestamp_str,
        "timestamp_us": ts_us,
        "user": principal,
        "user_role": None,
        "user_department": None,
        "session_id": None,
        "user_agent": None,
        "method": None,
        "route": t.get("operation") or "/",
        "http_route": t.get("operation"),
        "url_path": t.get("operation"),
        "status": None,
        "request_count": int(t.get("request_count") or 0),
        "error_count": int(t.get("error_count") or 0),
        "auth_failure_count": int(t.get("auth_failure_count") or 0),
        "http_5xx_count": int(t.get("http_5xx_count") or 0),
        "duration_ms": t.get("p95_latency_ms") or 0.0,
        "req_bytes": int(t.get("request_bytes") or 0),
        "resp_bytes": int(t.get("response_bytes") or 0),
        "trace_id": None,
        "upstream": t.get("target_service"),
        "error": "aggregate errors" if t.get("error_count") else None,
        "error_kind": "5m rollup",
        "service_id": t.get("target_service"),
        "module_id": t.get("caller_service"),
        "service_group_id": None,
        "service_module_id": None,
        "environment": "production",
        "agent": {"name": "tracescope", "version": "0.2.0"},
    }


def _traces_query(q: Dict[str, str]) -> List[Dict[str, Any]]:
    clauses: List[str] = ["1=1"]
    params: List[Any] = []

    user = q.get("user")
    if user:
        if user in ("-anonymous-", "anonymous", "anon"):
            clauses.append("principal IN ('', '-anonymous-', 'unknown')")
        elif user.endswith("*"):
            clauses.append("principal LIKE ?")
            params.append(user[:-1] + "%")
        else:
            clauses.append("principal = ?")
            params.append(user)

    service = q.get("service") or q.get("service_id")
    if service:
        clauses.append("target_service = ?")
        params.append(service)

    caller = q.get("caller")
    if caller:
        clauses.append("caller_service = ?")
        params.append(caller)

    status = q.get("status")
    if status:
        if status.endswith("*"):
            if status.startswith("4"):
                clauses.append("http_4xx_count > 0")
            elif status.startswith("5"):
                clauses.append("http_5xx_count > 0")
        elif status.isdigit():
            status_code = int(status)
            if status_code in (401, 403):
                clauses.append("auth_failure_count > 0")
            elif status_code >= 500:
                clauses.append("http_5xx_count > 0")
            elif status_code >= 400:
                clauses.append("http_4xx_count > 0")

    since = q.get("since") or q.get("since_ts")
    if since:
        try:
            clauses.append("bucket_start >= ?")
            params.append(int(float(since)))
        except ValueError:
            pass

    to_ts = q.get("to") or q.get("to_ts")
    if to_ts:
        try:
            clauses.append("bucket_start <= ?")
            params.append(int(float(to_ts)))
        except ValueError:
            pass

    try:
        limit = min(int(q.get("limit", "200")), 5000)
    except ValueError:
        limit = 200

    where_sql = " AND ".join(clauses)
    sql = f"""
        SELECT bucket_start*1000 timestamp_ms, caller_service,
               principal, target_service, target_api operation,
               sum(request_count) request_count, sum(error_count) error_count,
               sum(auth_failure_count) auth_failure_count,
               sum(http_4xx_count) http_4xx_count, sum(http_5xx_count) http_5xx_count,
               max(p95_latency_ms) p95_latency_ms,
               sum(request_bytes) request_bytes, sum(response_bytes) response_bytes,
               source_ip
        FROM (
            SELECT bucket_start,caller_service,principal,target_service,target_api,
                   request_count,error_count,auth_failure_count,http_4xx_count,
                   http_5xx_count,p95_latency_ms,request_bytes,response_bytes,
                   '' source_ip
            FROM topology_principal_edges_5m FINAL
            WHERE {where_sql}
        )
        GROUP BY bucket_start,caller_service,principal,target_service,target_api,source_ip
        ORDER BY timestamp_ms DESC LIMIT ?
    """
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


@router.get("/api/logs")
async def api_logs(request: Request) -> Dict[str, Any]:
    rows = _traces_query(qdict(request))
    return {"logs": [_trace_to_log_row(r) for r in rows]}


@router.get("/api/export/logs")
async def api_export_logs(request: Request) -> PlainTextResponse:
    q = qdict(request)
    q.pop("limit", None)
    try:
        limit = min(int(q.pop("max", "20000")), 50000)
    except ValueError:
        limit = 20000

    q["limit"] = str(limit)
    rows = _traces_query(q)
    out = [json.dumps(_trace_to_log_row(r), ensure_ascii=False) for r in rows[:limit]]
    body = "\n".join(out)
    return PlainTextResponse(body or "", media_type="application/x-ndjson")


@router.get("/api/violations")
async def api_violations(request: Request) -> Dict[str, Any]:
    # Network target IP/port evidence is not part of the read model. Returning
    # an empty result is safer than rebuilding policy checks from raw spans.
    return {"violations": [], "detail": "Network target evidence is unavailable in aggregate read models."}


# =========================================================================
# Security Policy Store
# =========================================================================

@router.get("/api/policy")
async def api_policy() -> Dict[str, Any]:
    return load_policy()


@router.post("/api/policy")
async def api_policy_post(request: Request) -> Dict[str, Any]:
    try:
        body = await request.body()
        d = json.loads(body.decode("utf-8") if body else "{}")
    except Exception:
        d = {}

    try:
        normalized = {
            "users": d.get("users") or {},
            "allow": d.get("allow") or [],
            "default_allow_private": bool(d.get("default_allow_private", True)),
        }
        with get_connection() as db:
            db.execute(
                "INSERT INTO security_policy(policy_key,policy_json,updated_at) VALUES('default',?,?)",
                (json.dumps(normalized, separators=(",", ":")), int(time.time() * 1000)),
            )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    global _policy_cache
    _policy_cache = normalized
    return {"ok": True}


# =========================================================================
# Endpoint & Traffic Diagnostics
# =========================================================================

@router.get("/api/endpoints/slow")
async def api_endpoints_slow() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT target_service AS service,
                   operation,
                   SUM(request_count) AS call_count,
                   ROUND(SUM(latency_sum) / GREATEST(SUM(request_count),1), 2) AS avg_duration_ms,
                   ROUND(MAX(latency_p95), 2) AS max_duration_ms
            FROM metric_buckets FINAL
            WHERE bucket_size=300
            GROUP BY target_service, operation
            HAVING call_count >= 5
            ORDER BY avg_duration_ms DESC
            LIMIT 20
            """
        ).fetchall()
    return {"slow": [dict(r) for r in rows]}


@router.get("/api/endpoints/errors")
async def api_endpoints_errors() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT service,operation,call_count,agg_errors AS error_count,error_rate
            FROM (
                SELECT target_service AS service,
                       operation,
                       SUM(request_count) AS call_count,
                       SUM(error_count) AS agg_errors,
                       ROUND(SUM(error_count) * 100.0 / GREATEST(SUM(request_count),1), 2) AS error_rate
                FROM metric_buckets FINAL
                WHERE bucket_size=300
                GROUP BY target_service, operation
            )
            WHERE agg_errors > 0
            ORDER BY error_rate DESC, agg_errors DESC
            LIMIT 20
            """
        ).fetchall()
    return {"errors": [dict(r) for r in rows]}


@router.get("/api/endpoints/health")
async def api_endpoints_health() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT target_service AS service,
                   target_api AS operation,
                   SUM(request_count) AS total_calls,
                   ROUND(SUM(latency_sum) / GREATEST(SUM(request_count),1), 2) AS avg_duration_ms,
                   ROUND(SUM(http_5xx_count) * 100.0 / GREATEST(SUM(request_count),1), 2) AS error_rate_5xx,
                   ROUND(SUM(http_4xx_count) * 100.0 / GREATEST(SUM(request_count),1), 2) AS error_rate_4xx
            FROM topology_api_edges_5m FINAL
            GROUP BY target_service, operation
            ORDER BY total_calls DESC
            LIMIT 50
            """
        ).fetchall()
    return {"endpoints": [dict(r) for r in rows]}


@router.get("/api/traffic/hourly")
async def api_traffic_hourly() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT intDiv(bucket_start, 3600) * 3600 AS hour_bucket,
                   SUM(request_count) AS total_calls,
                   SUM(error_count) AS errors_5xx,
                   ROUND(SUM(latency_sum) / GREATEST(SUM(request_count),1), 2) AS avg_duration_ms
            FROM metric_buckets FINAL
            WHERE bucket_size=300
            GROUP BY hour_bucket
            ORDER BY hour_bucket DESC
            LIMIT 168
            """
        ).fetchall()
    return {"hourly": [dict(r) for r in rows]}


@router.get("/api/traffic/anomalies")
async def api_traffic_anomalies() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id,
                   anomaly_type AS detector,
                   entity_id AS service_name,
                   severity,
                   status,
                   explanation,
                   window_start_ms,
                   window_end_ms,
                   percent_change AS score,
                   last_detected_ms AS created_at
            FROM anomalies
            ORDER BY window_start_ms DESC
            LIMIT 50
            """
        ).fetchall()
    return {"anomalies": [dict(r) for r in rows]}


# =========================================================================
# Prometheus Exposition Metrics
# =========================================================================

@router.get("/metrics")
async def prometheus_metrics() -> PlainTextResponse:
    from backend.app.services.prometheus_metrics import prometheus_registry
    content = prometheus_registry.render(role="all")
    return PlainTextResponse(content, media_type="text/plain; version=0.0.4; charset=utf-8")
