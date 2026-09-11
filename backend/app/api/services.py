from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from backend.app.repositories.db_context import get_connection
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.topology_repository import TopologyRepository

router = APIRouter(prefix="/api/v1", tags=["services"])

def _time_window(from_t: Optional[int], to_t: Optional[int]) -> tuple[int, int]:
    if from_t and to_t:
        start_sec = from_t if from_t < 10_000_000_000 else int(from_t / 1000)
        end_sec = to_t if to_t < 10_000_000_000 else int(to_t / 1000)
        return start_sec, end_sec
    with get_connection() as db:
        min_max = db.execute("SELECT MIN(bucket_start), MAX(bucket_start) FROM metric_buckets").fetchone()
        if min_max and min_max[1]:
            return max(min_max[0], min_max[1] - 86400), min_max[1] + 300
    now = int(time.time())
    return now - 3600, now

@router.get("/services")
async def list_services(
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
    q: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    start_sec, end_sec = _time_window(from_time, to_time)
    time_span = max(1, end_sec - start_sec)

    with get_connection() as db:
        # Check open anomalies to attach anomaly flag
        abnormal = {r[0] for r in db.execute("SELECT target_service FROM anomaly_events WHERE status = 'open'").fetchall()}

        query = """
            SELECT
              target_service as name,
              SUM(request_count) as total_requests,
              SUM(error_count) as total_errors,
              ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) as error_rate,
              ROUND(MAX(latency_p95), 2) as p95_latency,
              COUNT(DISTINCT operation) as operations_count,
              COUNT(DISTINCT principal_name) as principal_count
            FROM metric_buckets
            WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
        """
        params: List[Any] = [start_sec, end_sec]
        if q:
            query += " AND target_service LIKE ?"
            params.append(f"%{q}%")
        query += " GROUP BY target_service ORDER BY total_requests DESC LIMIT ?"
        params.append(limit)

        rows = [dict(r) for r in db.execute(query, params).fetchall()]
        meta_rows = {r["name"]: dict(r) for r in db.execute("SELECT name, environment, service_group, service_module, first_seen_ms, last_seen_ms FROM services").fetchall()}
        for r in rows:
            m = meta_rows.get(r["name"], {})
            r["environment"] = m.get("environment", "production")
            r["service_group"] = m.get("service_group", "Core")
            r["service_module"] = m.get("service_module", "Default")
            r["first_seen_ms"] = m.get("first_seen_ms", start_sec * 1000)
            r["last_seen_ms"] = m.get("last_seen_ms", end_sec * 1000)
            r["rps"] = round((r["total_requests"] or 0) / time_span, 2)
            r["anomaly_status"] = "abnormal" if r["name"] in abnormal else "normal"

        if not rows:
            rows = [dict(r) for r in db.execute("SELECT name, environment, service_group, service_module, first_seen_ms, last_seen_ms FROM services ORDER BY last_seen_ms DESC LIMIT ?", (limit,)).fetchall()]
            for r in rows:
                r["total_requests"] = 0
                r["rps"] = 0.0
                r["p95_latency"] = 0.0
                r["error_rate"] = 0.0
                r["anomaly_status"] = "normal"
        return {"items": rows, "count": len(rows)}

@router.get("/services/{service}")
async def get_service_detail(
    service: str,
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to")
) -> Dict[str, Any]:
    start_sec, end_sec = _time_window(from_time, to_time)
    time_span = max(1, end_sec - start_sec)
    top_repo = TopologyRepository()

    with get_connection() as db:
        # Summary
        summary_row = db.execute("""
            SELECT
              SUM(request_count) as total_requests,
              SUM(error_count) as total_errors,
              ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) as error_rate,
              ROUND(MAX(latency_p95), 2) as p95_latency,
              ROUND(AVG(latency_avg), 2) as avg_latency
            FROM metric_buckets
            WHERE target_service = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
        """, (service, start_sec, end_sec)).fetchone()

        if not summary_row or not summary_row["total_requests"]:
            # Fallback check
            exists = db.execute("SELECT 1 FROM traces WHERE service_name = ? OR target_service = ? LIMIT 1", (service, service)).fetchone()
            if not exists:
                exists = db.execute("SELECT 1 FROM services WHERE name = ? LIMIT 1", (service,)).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Service not found")

        # Operations
        operations = [dict(r) for r in db.execute("""
            SELECT operation as name, SUM(request_count) as requests,
                   ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) as error_rate,
                   ROUND(MAX(latency_p50), 2) as p50_ms,
                   ROUND(MAX(latency_p95), 2) as p95_ms,
                   ROUND(MAX(latency_p99), 2) as p99_ms,
                   ROUND(MAX(latency_p95), 2) as p95_latency
            FROM metric_buckets
            WHERE target_service = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
            GROUP BY operation ORDER BY requests DESC
        """, (service, start_sec, end_sec)).fetchall()]
        for op in operations:
            reqs = op.get("requests", 0) or 0
            err_rate = op.get("error_rate") or 0.0
            errs = int(reqs * err_rate)
            op["failure_rate"] = err_rate
            op["p50_ms"] = op.get("p50_ms") or 0.0
            op["p95_ms"] = op.get("p95_ms") or 0.0
            op["p99_ms"] = op.get("p99_ms") or 0.0
            op["slow_rate"] = 0.02 if (op.get("p95_ms") or 0) > 800 else 0.005
            op["status_5xx"] = errs
            op["status_4xx"] = 0
            op["status_2xx"] = max(0, reqs - errs)

        # Principals
        principals = [dict(r) for r in db.execute("""
            SELECT principal_name as name, SUM(request_count) as requests,
                   ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) as error_rate,
                   ROUND(MAX(latency_p95), 2) as p95_latency
            FROM metric_buckets
            WHERE target_service = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
              AND principal_name != ''
            GROUP BY principal_name ORDER BY requests DESC
        """, (service, start_sec, end_sec)).fetchall()]

        accounts = [{"username": r["name"], "requests": r["requests"]} for r in principals]

        # Instances
        instances = [dict(r) for r in db.execute("""
            SELECT service_instance as name, COUNT(*) as requests,
                   ROUND(AVG(duration_ms), 2) as avg_latency,
                   ROUND(SUM(CASE WHEN http_status >= 400 OR outcome = 'failure' THEN 1.0 ELSE 0.0 END) / COUNT(*), 4) as error_rate
            FROM traces
            WHERE target_service = ? AND timestamp_ms >= ? AND timestamp_ms < ?
              AND service_instance IS NOT NULL
            GROUP BY service_instance ORDER BY requests DESC
        """, (service, start_sec * 1000, end_sec * 1000)).fetchall()]

        meta_row = db.execute("SELECT name, environment, service_group, service_module, first_seen_ms, last_seen_ms FROM services WHERE name = ?", (service,)).fetchone()
        service_meta = dict(meta_row) if meta_row else {
            "name": service,
            "environment": "production",
            "service_group": "Core",
            "service_module": "Default",
            "first_seen_ms": start_sec * 1000,
            "last_seen_ms": end_sec * 1000
        }

    deps = top_repo.get_service_dependencies(service, start_sec, end_sec)
    callers = deps.get("callers", [])
    dependencies = deps.get("dependencies", [])
    incoming = [{"name": c.get("caller_service", c.get("name", "client")), "requests": c.get("requests", 0), "evidence": "confirmed"} for c in callers]
    outgoing = [{"name": d.get("target_service", d.get("name", "downstream")), "requests": d.get("requests", 0), "evidence": "confirmed"} for d in dependencies]

    agg_repo = AggregateRepository()
    series = agg_repo.query_series(start_sec, end_sec, bucket_size=60, service=service)

    total_reqs = (summary_row["total_requests"] if summary_row else 0) or 0
    return {
        "service": service,
        "service_meta": service_meta,
        "name": service,
        "service_name": service,
        "health": {
            "rps": round(total_reqs / time_span, 2),
            "total_requests": total_reqs,
            "error_rate": (summary_row["error_rate"] if summary_row else 0.0) or 0.0,
            "p95_latency_ms": (summary_row["p95_latency"] if summary_row else 0.0) or 0.0,
            "avg_latency_ms": (summary_row["avg_latency"] if summary_row else 0.0) or 0.0
        },
        "operations": operations,
        "principals": principals,
        "accounts": accounts,
        "instances": instances,
        "callers": callers,
        "incoming": incoming,
        "dependencies": dependencies,
        "outgoing": outgoing,
        "series": series
    }

@router.get("/services/{service}/metrics")
async def get_service_metrics(
    service: str,
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
    bucket: int = 60
) -> List[Dict[str, Any]]:
    start_sec, end_sec = _time_window(from_time, to_time)
    agg_repo = AggregateRepository()
    return agg_repo.query_series(start_sec, end_sec, bucket_size=bucket, service=service)

@router.get("/services/{service}/dependencies")
async def get_service_deps(
    service: str,
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to")
) -> Dict[str, Any]:
    start_sec, end_sec = _time_window(from_time, to_time)
    top_repo = TopologyRepository()
    return top_repo.get_service_dependencies(service, start_sec, end_sec)
