from __future__ import annotations
from typing import Optional
from pydantic import BaseModel

class MetricBucket(BaseModel):
    bucket_start: int
    bucket_size: int
    caller_service: str = ""
    target_service: str = ""
    principal_name: str = ""
    operation: str = ""
    request_count: int = 0
    error_count: int = 0
    latency_sum: float = 0.0
    latency_avg: float = 0.0
    latency_min: float = 0.0
    latency_max: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
