"""Traverse stored service relationships to make incident impact explainable and bounded."""
from __future__ import annotations
from typing import Any, Dict, List, Set, Optional
from backend.app.repositories.db_context import get_connection

def calculate_blast_radius(
    service: str,
    start_sec: int,
    end_sec: int,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    with get_connection(db_path) as db:
        # 1. Direct callers (level 1)
        direct_callers = [dict(r) for r in db.execute("""
            SELECT caller_service as name, SUM(request_count) as requests,
                   ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count), 0), 4) as error_rate
            FROM metric_buckets
            WHERE target_service = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
              AND caller_service != '' AND caller_service != ?
            GROUP BY caller_service
            ORDER BY requests DESC
        """, (service, start_sec, end_sec, service)).fetchall()]

        direct_caller_names = {c["name"] for c in direct_callers}

        # 2. Indirect callers (level 2) calling direct callers
        indirect_callers = []
        if direct_caller_names:
            placeholders = ",".join("?" for _ in direct_caller_names)
            query = f"""
                SELECT caller_service as name, target_service as via, SUM(request_count) as requests
                FROM metric_buckets
                WHERE target_service IN ({placeholders}) AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
                  AND caller_service != '' AND caller_service != ?
                GROUP BY caller_service, target_service
                ORDER BY requests DESC
            """
            params = list(direct_caller_names) + [start_sec, end_sec, service]
            for r in db.execute(query, params).fetchall():
                if r["name"] not in direct_caller_names and r["name"] != service:
                    indirect_callers.append(dict(r))

        # 3. Affected principals
        affected_principals = [dict(r) for r in db.execute("""
            SELECT principal_name as name, SUM(request_count) as requests,
                   ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count), 0), 4) as error_rate
            FROM metric_buckets
            WHERE target_service = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
              AND principal_name != ''
            GROUP BY principal_name
            ORDER BY requests DESC
        """, (service, start_sec, end_sec)).fetchall()]

        # 4. Affected operations
        affected_operations = [dict(r) for r in db.execute("""
            SELECT operation as name, SUM(request_count) as requests,
                   ROUND(MAX(latency_p95), 2) as p95_latency,
                   ROUND(SUM(error_count)*1.0 / NULLIF(SUM(request_count), 0), 4) as error_rate
            FROM metric_buckets
            WHERE target_service = ? AND bucket_size = 60 AND bucket_start >= ? AND bucket_start < ?
            GROUP BY operation
            ORDER BY requests DESC
        """, (service, start_sec, end_sec)).fetchall()]

        total_affected_requests = sum(c["requests"] for c in direct_callers)

        return {
            "root_service": service,
            "direct_callers": direct_callers,
            "indirect_callers": indirect_callers,
            "affected_principals": affected_principals,
            "affected_operations": affected_operations,
            "total_affected_callers": len(direct_callers) + len(set(i["name"] for i in indirect_callers)),
            "estimated_affected_requests": total_affected_requests
        }
