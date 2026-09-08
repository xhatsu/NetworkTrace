from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

class ServiceEdge(BaseModel):
    caller_service: str
    target_service: str
    first_seen: int
    last_seen: int
    request_count: int = 0
    error_count: int = 0
    error_rate: float = 0.0
    avg_latency: float = 0.0
    p95_latency: float = 0.0
    principal_count: int = 0
    operation_count: int = 0

class PrincipalServiceEdge(BaseModel):
    principal_name: str
    caller_service: str
    target_service: str
    first_seen: int
    last_seen: int
    request_count: int = 0
    error_rate: float = 0.0
    p95_latency: float = 0.0

class TopologyNode(BaseModel):
    name: str
    type: str = "service"
    rps: float = 0.0
    p95_ms: float = 0.0
    error_rate: float = 0.0
    anomaly_status: str = "normal"
    environment: str = "production"

class TopologyEdge(BaseModel):
    caller_service: str
    target_service: str
    rps: float = 0.0
    p95_latency: float = 0.0
    error_rate: float = 0.0
    principal_count: int = 0
    operation_count: int = 0
    top_principals: List[Dict[str, Any]] = []
    top_operations: List[Dict[str, Any]] = []
    anomaly_score: int = 0

class TopologyGraph(BaseModel):
    nodes: List[TopologyNode]
    edges: List[TopologyEdge]
