from __future__ import annotations
from typing import Any, Dict, List, Optional
from backend.app.repositories.db_context import get_connection

class PrincipalRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def list_principals(self, start_sec: int, end_sec: int, limit: int = 100) -> List[Dict[str, Any]]:
        time_span = max(1, end_sec - start_sec)
        with get_connection(self.db_path) as db:
            rows = db.execute("""
                SELECT
                  principal_name,
                  SUM(request_count) as total_requests,
                  SUM(error_count) as total_errors,
                  ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count),0), 4) as error_rate,
                  ROUND(MAX(latency_p95), 2) as p95_latency,
                  COUNT(DISTINCT target_service) as services_used,
                  COUNT(DISTINCT operation) as operations_count,
                  MAX(bucket_start) as last_seen_sec
                FROM metric_buckets
                WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                  AND principal_name != ''
                GROUP BY principal_name
                ORDER BY total_requests DESC
                LIMIT ?
            """, (start_sec, end_sec, limit)).fetchall()

            # fallback to traces if metric_buckets empty
            if not rows:
                rows = db.execute("""
                    SELECT
                      principal_name,
                      COUNT(*) as total_requests,
                      SUM(CASE WHEN http_status >= 400 OR outcome = 'failure' THEN 1 ELSE 0 END) as total_errors,
                      ROUND(SUM(CASE WHEN http_status >= 400 OR outcome = 'failure' THEN 1.0 ELSE 0 END) / COUNT(*), 4) as error_rate,
                      ROUND(AVG(duration_ms), 2) as p95_latency,
                      COUNT(DISTINCT target_service) as services_used,
                      COUNT(DISTINCT operation) as operations_count,
                      MAX(timestamp) as last_seen_sec
                    FROM traces
                    WHERE timestamp_ms >= ? AND timestamp_ms < ?
                    GROUP BY principal_name
                    ORDER BY total_requests DESC
                    LIMIT ?
                """, (start_sec * 1000, end_sec * 1000, limit)).fetchall()

            result = []
            for r in rows:
                d = dict(r)
                d["rps"] = round((d["total_requests"] or 0) / time_span, 2)
                result.append(d)
            return result

    def get_principal_profile(self, principal_name: str, start_sec: int, end_sec: int) -> Optional[Dict[str, Any]]:
        with get_connection(self.db_path) as db:
            # targets used
            targets = [dict(r) for r in db.execute("""
                SELECT
                  target_service,
                  SUM(request_count) as requests,
                  ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count), 0), 4) as error_rate,
                  ROUND(MAX(latency_p95), 2) as p95_latency
                FROM metric_buckets
                WHERE principal_name = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                GROUP BY target_service
                ORDER BY requests DESC
            """, (principal_name, start_sec, end_sec)).fetchall()]

            # operations
            operations = [dict(r) for r in db.execute("""
                SELECT
                  operation,
                  target_service,
                  SUM(request_count) as requests,
                  ROUND(MAX(latency_p95), 2) as p95_latency
                FROM metric_buckets
                WHERE principal_name = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                GROUP BY operation, target_service
                ORDER BY requests DESC
            """, (principal_name, start_sec, end_sec)).fetchall()]

            # callers (source services)
            callers = [dict(r) for r in db.execute("""
                SELECT
                  caller_service,
                  SUM(request_count) as requests
                FROM metric_buckets
                WHERE principal_name = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                  AND caller_service != ''
                GROUP BY caller_service
                ORDER BY requests DESC
            """, (principal_name, start_sec, end_sec)).fetchall()]

            # active hours distribution
            hours = [dict(r) for r in db.execute("""
                SELECT
                  (bucket_start % 86400) / 3600 as hour,
                  SUM(request_count) as requests
                FROM metric_buckets
                WHERE principal_name = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                GROUP BY hour
                ORDER BY hour ASC
            """, (principal_name, start_sec, end_sec)).fetchall()]

            total_reqs = sum(t["requests"] for t in targets)
            if total_reqs == 0 and not targets:
                # check traces table
                exists = db.execute("SELECT 1 FROM traces WHERE principal_name = ? LIMIT 1", (principal_name,)).fetchone()
                if not exists:
                    return None

            return {
                "principal_name": principal_name,
                "targets": targets,
                "operations": operations,
                "callers": callers,
                "active_hours": hours,
                "total_requests": total_reqs
            }
