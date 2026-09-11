from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

class AnomalyReason(BaseModel):
    type: str
    contribution: int
    baseline: float
    current: float
    text: str = ""

class AnomalyEvent(BaseModel):
    id: Optional[int] = None
    detected_at: int
    anomaly_type: str
    severity: str
    score: int
    confidence: float = 1.0
    caller_service: Optional[str] = None
    target_service: Optional[str] = None
    principal_name: Optional[str] = None
    source_ip: Optional[str] = None
    operation: Optional[str] = None
    baseline_value: Optional[float] = None
    current_value: Optional[float] = None
    delta_percentage: Optional[float] = None
    first_seen: Optional[int] = None
    last_seen: Optional[int] = None
    status: str = "open"
    acknowledged: int = 0
    reasons: List[AnomalyReason] = []
    metadata: Dict[str, Any] = {}
