"""Build dashboard-ready estate summaries from precomputed ClickHouse rollups."""
from __future__ import annotations
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter, Query
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.anomaly_repository import AnomalyRepository
from backend.app.repositories.db_context import get_connection
from backend.app.api.anomalies import format_anomaly

router = APIRouter(prefix="/api/v1", tags=["overview"])

@router.get("/overview")
async def get_overview(
    from_time: Optional[int] = Query(None, alias="from"),
    to_time: Optional[int] = Query(None, alias="to"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    bucket: int = 60
) -> Dict[str, Any]:
    agg_repo = AggregateRepository()
    anomaly_repo = AnomalyRepository()

    # Determine window in seconds
    now_sec = int(time.time())
    if from_time and to_time:
        start_sec = from_time if from_time < 10_000_000_000 else int(from_time / 1000)
        end_sec = to_time if to_time < 10_000_000_000 else int(to_time / 1000)
    else:
        # Check available data bounds
        with get_connection() as db:
            min_max = db.execute("SELECT MIN(bucket_start), MAX(bucket_start) FROM metric_buckets").fetchone()
            if min_max and min_max[1]:
                end_sec = min_max[1] + 300
                start_sec = max(min_max[0], end_sec - 86400) # last 24h of data
            else:
                end_sec = now_sec
                start_sec = now_sec - 3600

    time_span = max(1, end_sec - start_sec)
    summary = agg_repo.query_summary(start_sec, end_sec, bucket_size=60)
    series = agg_repo.query_series(start_sec, end_sec, bucket_size=bucket)

    # Anomaly counts
    anomalies = anomaly_repo.list_anomalies(start_ms=start_sec * 1000, end_ms=end_sec * 1000, limit=200)
    open_anomalies = [format_anomaly(a) for a in anomalies if a.get("status") == "open"]
    critical_anomalies = [a for a in open_anomalies if a.get("severity") == "critical"]

    # Top rankings
    with get_connection() as db:
        top_services = [dict(r) for r in db.execute("""
            SELECT target_service as name, SUM(request_count) as requests,
                   ROUND(SUM(request_count)*1.0 / ?, 2) as rps,
                   ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) as error_rate,
                   ROUND(MAX(latency_p95), 2) as p95_latency
            FROM metric_buckets
            WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
            GROUP BY target_service ORDER BY requests DESC LIMIT 6
        """, (time_span, start_sec, end_sec)).fetchall()]

        top_principals = [dict(r) for r in db.execute("""
            SELECT principal_name as name, SUM(request_count) as requests,
                   ROUND(SUM(request_count)*1.0 / ?, 2) as rps,
                   ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) as error_rate,
                   ROUND(MAX(latency_p95), 2) as p95_latency
            FROM metric_buckets
            WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ? AND principal_name != ''
            GROUP BY principal_name ORDER BY requests DESC LIMIT 6
        """, (time_span, start_sec, end_sec)).fetchall()]

        slowest_operations = [dict(r) for r in db.execute("""
            SELECT operation as name, target_service as service,
                   ROUND(MAX(latency_p95), 2) as p95_latency,
                   SUM(request_count) as requests
            FROM metric_buckets
            WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
            GROUP BY operation, target_service ORDER BY p95_latency DESC LIMIT 6
        """, (start_sec, end_sec)).fetchall()]

    return {
        "kpis": {
            "current_rps": summary.get("rps", 0.0),
            "total_requests": summary.get("total_requests", 0),
            "error_rate": summary.get("error_rate", 0.0),
            "p95_latency_ms": summary.get("latency_p95", 0.0),
            "active_services": summary.get("active_services", 0),
            "active_principals": summary.get("active_principals", 0),
            "open_anomalies": len(open_anomalies),
            "critical_anomalies": len(critical_anomalies)
        },
        "series": series,
        "anomalies": open_anomalies[:8],
        "recent_anomalies": open_anomalies[:8],
        "top_services": top_services,
        "top_principals": top_principals,
        "slowest_operations": slowest_operations,
        "time_window": {"from": start_sec, "to": end_sec, "bucket": bucket}
    }
