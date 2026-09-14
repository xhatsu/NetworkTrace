"""Persist robust behavioral expectations for reuse across detector runs and API reads."""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
from backend.app.models.baseline import BaselineMetric
from backend.app.repositories.db_context import get_connection, db_transaction

class BaselineRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def save_baselines(self, baselines: List[BaselineMetric]) -> None:
        if not baselines:
            return
        sql = """
        INSERT INTO baseline_metrics (
          dimension_type, dimension_key, hour_of_day, day_of_week, sample_count,
          rps_median, rps_mad, latency_p50_median, latency_p95_median, latency_p95_mad,
          error_rate_median, error_rate_mad, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        now = int(time.time() * 1000)
        with db_transaction(self.db_path) as db:
            db.executemany(sql, [[
                b.dimension_type, b.dimension_key, b.hour_of_day, b.day_of_week, b.sample_count,
                b.rps_median, b.rps_mad, b.latency_p50_median, b.latency_p95_median, b.latency_p95_mad,
                b.error_rate_median, b.error_rate_mad, now
            ] for b in baselines])

    def get_baseline(
        self,
        dimension_type: str,
        dimension_key: str,
        hour_of_day: Optional[int] = None,
        day_of_week: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        with get_connection(self.db_path) as db:
            if hour_of_day is not None and day_of_week is not None:
                row = db.execute("""
                    SELECT * FROM baseline_metrics FINAL
                    WHERE dimension_type = ? AND dimension_key = ? AND hour_of_day = ? AND day_of_week = ?
                """, (dimension_type, dimension_key, hour_of_day, day_of_week)).fetchone()
                if row:
                    return dict(row)

            # fallback to overall average across hours
            row = db.execute("""
                SELECT
                  AVG(rps_median) as rps_median,
                  AVG(rps_mad) as rps_mad,
                  AVG(latency_p50_median) as latency_p50_median,
                  AVG(latency_p95_median) as latency_p95_median,
                  AVG(latency_p95_mad) as latency_p95_mad,
                  AVG(error_rate_median) as error_rate_median,
                  AVG(error_rate_mad) as error_rate_mad,
                  SUM(sample_count) as sample_count
                FROM baseline_metrics FINAL
                WHERE dimension_type = ? AND dimension_key = ?
            """, (dimension_type, dimension_key)).fetchone()
            if row and row["sample_count"]:
                return dict(row)
            return None
