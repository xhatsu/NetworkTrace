"""Typed contracts for the service -> API -> principal topology surface."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TopologyMetrics(BaseModel):
    model_config = ConfigDict(extra="allow")

    tps: float = 0.0
    request_count: int = 0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    error_rate: float = 0.0
    http_4xx_rate: float = 0.0
    http_5xx_rate: float = 0.0
    timeout_count: int = 0
    tcp_reset_count: int = 0
    incomplete_count: int = 0
    request_bytes: int = 0
    response_bytes: int = 0
    total_bytes: int = 0
    average_request_bytes: float = 0.0
    average_response_bytes: float = 0.0
    request_bytes_per_second: float = 0.0
    response_bytes_per_second: float = 0.0
    bandwidth_bytes_per_second: float = 0.0
    bandwidth_bits_per_second: float = 0.0
    unique_principals: int = 0
    unique_source_ips: int = 0
    anonymous_requests: int = 0
    first_seen_ms: Optional[int] = None
    last_seen_ms: Optional[int] = None
    evidence_type: str = "direct"
    evidence_types: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    change: Dict[str, Any] = Field(default_factory=dict)


class TopologyNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    type: str
    service: Optional[str] = None
    api: Optional[str] = None
    principal: Optional[str] = None
    metrics: TopologyMetrics = Field(default_factory=TopologyMetrics)


class TopologyEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source: str
    target: str
    source_name: str
    target_name: str
    metrics: TopologyMetrics = Field(default_factory=TopologyMetrics)
    evidence_type: str = "direct"
    direct: bool = True
    inferred: bool = False


class TopologyWindow(BaseModel):
    start_ms: int
    end_ms: int
    duration_seconds: int
    label: str
    baseline: str = "previous_window"


class AnonymousTopologySummary(BaseModel):
    total_requests: int = 0
    identified_requests: int = 0
    anonymous_requests: int = 0
    identified_request_percentage: float = 0.0
    anonymous_request_percentage: float = 0.0
    anonymous_tps: float = 0.0
    top_services: List[Dict[str, Any]] = Field(default_factory=list)
    top_apis: List[Dict[str, Any]] = Field(default_factory=list)


class ServiceTopologyResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    window: TopologyWindow
    nodes: List[TopologyNode] = Field(default_factory=list)
    edges: List[TopologyEdge] = Field(default_factory=list)
    changes: Dict[str, Any] = Field(default_factory=dict)
    anonymous: AnonymousTopologySummary = Field(default_factory=AnonymousTopologySummary)
    backend: str = "clickhouse"


class TopologyExpansionResponse(ServiceTopologyResponse):
    parent: Dict[str, Any] = Field(default_factory=dict)


class TopologyDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity: Dict[str, Any]
    metrics: TopologyMetrics
    series: List[Dict[str, Any]] = Field(default_factory=list)
    changes: Dict[str, Any] = Field(default_factory=dict)
    anonymous: AnonymousTopologySummary = Field(default_factory=AnonymousTopologySummary)
    backend: str = "clickhouse"


class PrincipalIpPageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    principal: str
    items: List[Dict[str, Any]] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    page_size: int
    window: TopologyWindow
    filters: Dict[str, Any] = Field(default_factory=dict)
    backend: str = "clickhouse"
