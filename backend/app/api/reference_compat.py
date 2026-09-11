from __future__ import annotations

import ipaddress
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from backend.config import settings
from backend.app.repositories.db_context import get_connection

log = logging.getLogger("tracescope-hub")
router = APIRouter(tags=["reference_compat"])

POLICY_PATH = Path(settings.db_path).parent / "policy.json"
_policy_cache: Dict[str, Any] = {"users": {}, "allow": [], "default_allow_private": True}
_policy_mtime: float = -1.0


def load_policy() -> Dict[str, Any]:
    global _policy_cache, _policy_mtime
    try:
        if not POLICY_PATH.exists():
            POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
            default_policy = {
                "users": {
                    "admin": ["*"],
                    "ops": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
                },
                "allow": [],
                "default_allow_private": True,
            }
            POLICY_PATH.write_text(json.dumps(default_policy, indent=2))
            _policy_cache = default_policy
            _policy_mtime = POLICY_PATH.stat().st_mtime
            return _policy_cache

        mt = POLICY_PATH.stat().st_mtime
        if mt == _policy_mtime:
            return _policy_cache
        with open(POLICY_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        _policy_cache = {
            "users": d.get("users") or {},
            "allow": d.get("allow") or [],
            "default_allow_private": bool(d.get("default_allow_private", True)),
        }
        _policy_mtime = mt
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
        spans_row = conn.execute("SELECT count() FROM traces").fetchone()
        spans_count = int(spans_row[0]) if (spans_row and spans_row[0] is not None) else 0

        bounds = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM traces").fetchone()
        first_seen = bounds[0] if bounds else None
        last_seen = bounds[1] if bounds else None

        svcs_row = conn.execute("SELECT COUNT(DISTINCT target_service) FROM metric_buckets WHERE bucket_size=300").fetchone()
        services_count = int(svcs_row[0]) if (svcs_row and svcs_row[0] is not None) else 0
        if services_count == 0:
            svcs_row = conn.execute("SELECT COUNT(DISTINCT target_service) FROM traces").fetchone()
            services_count = int(svcs_row[0]) if (svcs_row and svcs_row[0] is not None) else 0

        nodes_row = conn.execute("SELECT COUNT(DISTINCT service_instance) FROM traces WHERE service_instance IS NOT NULL").fetchone()
        nodes_count = int(nodes_row[0]) if (nodes_row and nodes_row[0] is not None) else 1

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
            SELECT COALESCE(NULLIF(service_instance,''), NULLIF(target_ip,''), 'default-node') AS node,
                   MAX(timestamp) AS last_seen,
                   COUNT(*) AS n_events
            FROM traces
            GROUP BY node
            ORDER BY node
            """
        ).fetchall()
    return {"nodes": [dict(r) for r in rows]}


@router.get("/api/coverage")
async def api_coverage() -> Dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(service_instance,''), NULLIF(target_ip,''), 'default-node') AS host,
                   target_service AS service_id,
                   COUNT(*) AS spans,
                   MAX(timestamp) AS last_seen
            FROM traces
            GROUP BY host, service_id
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
            SELECT COALESCE(NULLIF(principal_name,''), '-anonymous-') AS user,
                   COUNT(*) AS calls,
                   MAX(timestamp) AS last_seen
            FROM traces
            GROUP BY user
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
        max_t_row = conn.execute("SELECT (SELECT MAX(timestamp) FROM traces)").fetchone()
        now_ts = int(max_t_row[0]) if (max_t_row and max_t_row[0]) else int(time.time())
        t0 = now_ts - win

        anon_clause = "" if include_anon else " AND principal_name IS NOT NULL AND principal_name != '' AND principal_name != '-anonymous-' AND principal_name != 'unknown'"
        rows = conn.execute(
            f"""
            SELECT COALESCE(NULLIF(principal_name,''), '-anonymous-') AS u,
                   ROUND(COUNT(*) / (? / 60.0), 3) AS rpm,
                   COUNT(*) AS n,
                   MIN(timestamp) AS first_ts,
                   MAX(timestamp) AS last_ts
            FROM traces
            WHERE timestamp >= ? {anon_clause}
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
            SELECT COALESCE(NULLIF(caller_ip,''), NULLIF(caller_service,''), '-') AS caller,
                   COALESCE(NULLIF(principal_name,''), '-anonymous-') AS user,
                   target_ip AS dst_ip,
                   target_port AS dst_port,
                   COUNT(*) AS calls,
                   MAX(timestamp) AS last_seen
            FROM traces
            GROUP BY caller, user, dst_ip, dst_port
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
    target_ip = t.get("target_ip") or ""
    target_port = t.get("target_port")
    upstream = f"{target_ip}:{target_port}" if target_port else target_ip

    ts = t.get("timestamp") or 0
    ts_ms = t.get("timestamp_ms") or (ts * 1000)
    ts_us = ts_ms * 1000

    try:
        timestamp_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + f".{(ts_us % 1000000):06d}Z"
    except Exception:
        timestamp_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))

    principal = t.get("principal_name") or "-anonymous-"
    if principal == "unknown":
        principal = "-anonymous-"

    return {
        "client_ip": t.get("caller_ip") or t.get("caller_service"),
        "origin_client_ip": t.get("caller_ip") or t.get("caller_service"),
        "immediate_peer": t.get("caller_ip") or t.get("caller_service"),
        "@timestamp": timestamp_str,
        "timestamp_us": ts_us,
        "user": principal,
        "user_role": None,
        "user_department": None,
        "session_id": None,
        "user_agent": None,
        "method": t.get("http_method") or "POST",
        "route": t.get("operation") or t.get("http_route") or "/",
        "http_route": t.get("http_route") or t.get("operation"),
        "url_path": t.get("operation"),
        "status": t.get("http_status") or 200,
        "duration_ms": t.get("duration_ms") or 0.0,
        "req_bytes": 0,
        "resp_bytes": 0,
        "trace_id": t.get("trace_id"),
        "upstream": upstream or None,
        "error": t.get("outcome") if t.get("outcome") != "success" else None,
        "error_kind": t.get("status_class"),
        "service_id": t.get("target_service") or t.get("service_name"),
        "module_id": t.get("caller_service"),
        "service_group_id": None,
        "service_module_id": None,
        "environment": t.get("service_environment") or "production",
        "agent": {"name": "tracescope", "version": "0.2.0"},
    }


def _traces_query(q: Dict[str, str]) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []

    user = q.get("user")
    if user:
        if user in ("-anonymous-", "anonymous", "anon"):
            clauses.append("(principal_name IS NULL OR principal_name = '' OR principal_name = '-anonymous-' OR principal_name = 'unknown')")
        elif user.endswith("*"):
            clauses.append("principal_name LIKE ?")
            params.append(user[:-1] + "%")
        else:
            clauses.append("principal_name = ?")
            params.append(user)

    service = q.get("service") or q.get("service_id")
    if service:
        clauses.append("target_service = ?")
        params.append(service)

    caller = q.get("caller")
    if caller:
        clauses.append("(caller_service = ? OR caller_ip = ?)")
        params.extend([caller, caller])

    status = q.get("status")
    if status:
        if status.endswith("*"):
            clauses.append("status_class LIKE ?")
            params.append(status[:-1] + "%")
        elif status.isdigit():
            clauses.append("http_status = ?")
            params.append(int(status))

    since = q.get("since") or q.get("since_ts")
    if since:
        try:
            clauses.append("timestamp >= ?")
            params.append(int(float(since)))
        except ValueError:
            pass

    to_ts = q.get("to") or q.get("to_ts")
    if to_ts:
        try:
            clauses.append("timestamp <= ?")
            params.append(int(float(to_ts)))
        except ValueError:
            pass

    try:
        limit = min(int(q.get("limit", "200")), 5000)
    except ValueError:
        limit = 200

    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM traces {where_sql} ORDER BY timestamp_ms DESC LIMIT ?"
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
    q = qdict(request)
    rows = _traces_query(q)
    violations = []
    for r in rows:
        user = r.get("principal_name") or "-anonymous-"
        target = f"{r.get('target_ip') or '127.0.0.1'}:{r.get('target_port') or 80}"
        if not is_target_allowed(user, target):
            log_row = _trace_to_log_row(r)
            log_row["violation"] = True
            violations.append(log_row)
    return {"violations": violations}


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

    tmp = str(POLICY_PATH) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, POLICY_PATH)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    load_policy()
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
                   COUNT(*) AS call_count,
                   ROUND(AVG(duration_ms), 2) AS avg_duration_ms,
                   ROUND(MAX(duration_ms), 2) AS max_duration_ms
            FROM traces
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
            SELECT target_service AS service,
                   operation,
                   COUNT(*) AS call_count,
                   SUM(CASE WHEN http_status >= 400 THEN 1 ELSE 0 END) AS error_count,
                   ROUND(SUM(CASE WHEN http_status >= 400 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS error_rate
            FROM traces
            GROUP BY target_service, operation
            HAVING error_count > 0
            ORDER BY error_rate DESC, error_count DESC
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
                   operation,
                   COUNT(*) AS total_calls,
                   ROUND(AVG(duration_ms), 2) AS avg_duration_ms,
                   ROUND(SUM(CASE WHEN http_status >= 500 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS error_rate_5xx,
                   ROUND(SUM(CASE WHEN http_status >= 400 AND http_status < 500 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS error_rate_4xx
            FROM traces
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
            SELECT (timestamp / 3600) * 3600 AS hour_bucket,
                   COUNT(*) AS total_calls,
                   SUM(CASE WHEN http_status >= 500 THEN 1 ELSE 0 END) AS errors_5xx,
                   ROUND(AVG(duration_ms), 2) AS avg_duration_ms
            FROM traces
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
    lines: List[str] = []
    with get_connection() as conn:
        total_spans_row = conn.execute("SELECT count() FROM traces").fetchone()
        total_spans = int(total_spans_row[0]) if (total_spans_row and total_spans_row[0] is not None) else 0

        nodes_rows = conn.execute(
            """
            SELECT DISTINCT service_instance AS node
            FROM traces
            WHERE service_instance IS NOT NULL
            LIMIT 50
            """
        ).fetchall()
        nodes_reporting = max(1, len(nodes_rows))

        status_rows = conn.execute(
            """
            SELECT SUM(request_count - error_count) AS cnt_2xx,
                   SUM(error_count) AS cnt_err
            FROM metric_buckets
            WHERE bucket_size = 60
            """
        ).fetchone()

        c_2xx = int(status_rows["cnt_2xx"] or 0) if status_rows else 0
        c_err = int(status_rows["cnt_err"] or 0) if status_rows else 0

        rpm_rows_db = conn.execute(
            """
            SELECT principal_name AS user,
                   SUM(request_count) AS n,
                   ROUND(SUM(request_count) / 5.0, 2) AS rpm
            FROM metric_buckets
            WHERE bucket_size = 300
              AND bucket_start >= (SELECT COALESCE(MAX(bucket_start), 0) - 300 FROM metric_buckets WHERE bucket_size = 300)
              AND principal_name IS NOT NULL AND principal_name != '' AND principal_name != 'unknown'
            GROUP BY principal_name
            ORDER BY n DESC
            LIMIT 20
            """
        ).fetchall()

    lines.append("# TYPE nt_violations_total counter")
    lines.append("nt_violations_total 0")
    lines.append("# TYPE nt_nodes_reporting gauge")
    lines.append(f"nt_nodes_reporting {nodes_reporting}")
    lines.append("# TYPE nt_overflow_total counter")
    lines.append('nt_overflow_total{reason="dropped"} 0')
    lines.append('nt_overflow_total{reason="db_dropped"} 0')
    lines.append('nt_overflow_total{reason="duplicate_span"} 0')
    lines.append("# TYPE nt_otel_server_spans_total counter")
    lines.append(f'nt_otel_server_spans_total{{receiver="otel-http"}} {total_spans}')
    lines.append("# TYPE nt_requests_total counter")
    lines.append(f'nt_requests_total{{source="otel",probe="agent",status_class="2xx"}} {c_2xx}')
    lines.append(f'nt_requests_total{{source="otel",probe="agent",status_class="5xx"}} {c_err}')
    lines.append("# TYPE nt_policy_violations_total counter")
    lines.append('nt_policy_violations_total{source="otel"} 0')
    lines.append("# TYPE nt_duration_samples_total counter")
    lines.append(f'nt_duration_samples_total{{source="otel",probe="agent"}} {total_spans}')

    lines.append("# TYPE nt_user_rpm gauge")
    lines.append("# TYPE nt_user_requests_5m gauge")
    for u_row in rpm_rows_db:
        u_label = prom_escape(u_row["user"])
        lines.append(f'nt_user_rpm{{user="{u_label}"}} {u_row["rpm"]}')
        lines.append(f'nt_user_requests_5m{{user="{u_label}"}} {u_row["n"]}')

    lines.append("# TYPE nt_node_events_total counter")
    lines.append("# TYPE nt_node_up gauge")
    for n_row in nodes_rows:
        n_label = prom_escape(n_row["node"])
        lines.append(f'nt_node_events_total{{node="{n_label}"}} 1')
        lines.append(f'nt_node_up{{node="{n_label}"}} 1')

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")
