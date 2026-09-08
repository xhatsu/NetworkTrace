from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field

class NormalizedTrace(BaseModel):
    event_uid: str
    timestamp: int
    timestamp_ms: int

    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None

    service_name: str
    service_instance: Optional[str] = None
    service_environment: str = "production"

    caller_service: Optional[str] = None
    caller_instance: Optional[str] = None
    caller_ip: Optional[str] = None

    target_service: str
    target_instance: Optional[str] = None
    target_ip: Optional[str] = None
    target_port: Optional[int] = None

    principal_name: str = "unknown"

    operation: str
    http_method: Optional[str] = None
    http_route: Optional[str] = None

    http_status: Optional[int] = None
    status_class: str = "unknown"

    duration_ms: float = Field(ge=0.0)
    duration_us: int = Field(ge=0)
    outcome: str = "unknown"

    protocol: str = "http"
    span_kind: str = "server"

    attributes_json: Optional[str] = None
    created_at: int
