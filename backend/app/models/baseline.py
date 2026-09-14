"""Define robust normal-behavior summaries persisted independently of detector code."""
from __future__ import annotations
from pydantic import BaseModel

class BaselineMetric(BaseModel):
    dimension_type: str
    dimension_key: str
    hour_of_day: int
    day_of_week: int
    sample_count: int = 0
    rps_median: float = 0.0
    rps_mad: float = 0.0
    latency_p50_median: float = 0.0
    latency_p95_median: float = 0.0
    latency_p95_mad: float = 0.0
    error_rate_median: float = 0.0
    error_rate_mad: float = 0.0
