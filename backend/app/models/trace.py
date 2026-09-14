"""Define the sanitized canonical trace accepted by the ClickHouse ingest boundary."""
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

    # Canonical request observation fields
    environment: str = "production"
    principal_id: str = ""
    identity_source: str = "unknown"
    auth_result: str = "unknown"
    auth_evidence: str = "unknown"
    caller_resolution_method: str = "none"
    caller_confidence: float = 0.0
    network_peer_ip: Optional[str] = None
    original_client_ip: Optional[str] = None
    original_client_ip_trusted: int = 0
    source_group: Optional[str] = None
    operation_key: str = "unknown"
    soap_fault_code: Optional[str] = None
    outcome_class: str = "unknown"
    sampling_context: Optional[str] = None
    dedup_key: Optional[str] = None

    from pydantic import model_validator

    @model_validator(mode="after")
    def populate_canonical_defaults(self):
        if not self.principal_id and self.principal_name and self.principal_name != "unknown":
            env = self.service_environment or self.environment or "production"
            self.principal_id = f"{env}:{self.principal_name}"
        if not self.operation_key or self.operation_key == "unknown":
            if self.target_service and self.operation:
                self.operation_key = f"{self.target_service}/{self.operation}"
            elif self.operation:
                self.operation_key = self.operation
        return self
