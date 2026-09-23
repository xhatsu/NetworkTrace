"""Persist and query rollups so high-cardinality raw telemetry stays off dashboard hot paths."""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
from backend.app.models.aggregate import MetricBucket
from backend.app.repositories.db_context import get_connection, db_transaction

class AggregateRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def save_buckets(self, buckets: List[MetricBucket]) -> None:
        if not buckets:
            return
        cols = [
            "bucket_start", "bucket_size", "caller_service", "target_service",
            "principal_name", "operation", "request_count", "error_count",
            "latency_sum", "latency_avg", "latency_min", "latency_max",
            "latency_p50", "latency_p95", "latency_p99", "created_at"
        ]
        sql = f"""
        INSERT INTO metric_buckets ({','.join(cols)})
        VALUES ({','.join('?' for _ in cols)})
        """
        now = int(time.time() * 1000)
        with db_transaction(self.db_path) as db:
            db.executemany(sql, [[
                b.bucket_start, b.bucket_size, b.caller_service, b.target_service,
                b.principal_name, b.operation, b.request_count, b.error_count,
                b.latency_sum, b.latency_avg, b.latency_min, b.latency_max,
                b.latency_p50, b.latency_p95, b.latency_p99, now
            ] for b in buckets])

    def query_series(
        self,
        start_sec: int,
        end_sec: int,
        bucket_size: int = 60,
        service: Optional[str] = None,
        principal: Optional[str] = None,
        caller: Optional[str] = None,
        operation: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses = ["bucket_size = ?", "bucket_start >= ?", "bucket_start < ?"]
        args: List[Any] = [bucket_size, start_sec, end_sec]
        if service:
            clauses.append("target_service = ?")
            args.append(service)
        if principal:
            clauses.append("principal_name = ?")
            args.append(principal)
        if caller:
            clauses.append("caller_service = ?")
            args.append(caller)
        if operation:
            clauses.append("operation = ?")
            args.append(operation)

        where = " AND ".join(clauses)
        sql = f"""
        SELECT
          bucket_start,
          SUM(request_count) as requests,
          SUM(error_count) as errors,
          ROUND(CASE WHEN SUM(request_count) > 0 THEN SUM(error_count) * 1.0 / SUM(request_count) ELSE 0 END, 4) as error_rate,
          ROUND(CASE WHEN SUM(request_count) > 0 THEN SUM(latency_sum) / SUM(request_count) ELSE 0 END, 2) as latency_avg,
          ROUND(MAX(latency_p50), 2) as latency_p50,
          ROUND(MAX(latency_p95), 2) as latency_p95,
          ROUND(MAX(latency_p99), 2) as latency_p99
        FROM metric_buckets FINAL
        WHERE {where}
        GROUP BY bucket_start
        ORDER BY bucket_start ASC
        """
        with get_connection(self.db_path) as db:
            return [dict(r) for r in db.execute(sql, args)]

    def query_summary(
        self,
        start_sec: int,
        end_sec: int,
        bucket_size: int = 60,
        service: Optional[str] = None,
        principal: Optional[str] = None,
    ) -> Dict[str, Any]:
        clauses = ["bucket_size = ?", "bucket_start >= ?", "bucket_start < ?"]
        args: List[Any] = [bucket_size, start_sec, end_sec]
        if service:
            clauses.append("target_service = ?")
            args.append(service)
        if principal:
            clauses.append("principal_name = ?")
            args.append(principal)

        where = " AND ".join(clauses)
        sql = f"""
        SELECT
          COALESCE(SUM(request_count), 0) as total_requests,
          COALESCE(SUM(error_count), 0) as total_errors,
          COUNT(DISTINCT target_service) as active_services,
          COUNT(DISTINCT principal_name) as active_principals,
          ROUND(CASE WHEN SUM(request_count) > 0 THEN SUM(error_count) * 1.0 / SUM(request_count) ELSE 0 END, 4) as error_rate,
          ROUND(CASE WHEN SUM(request_count) > 0 THEN SUM(latency_sum) / SUM(request_count) ELSE 0 END, 2) as latency_avg,
          ROUND(MAX(latency_p95), 2) as latency_p95
        FROM metric_buckets FINAL
        WHERE {where}
        """
        with get_connection(self.db_path) as db:
            row = dict(db.execute(sql, args).fetchone() or {})
            time_span = max(1, end_sec - start_sec)
            row["rps"] = round((row.get("total_requests") or 0) / time_span, 2)
            return row
