from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class Incident(BaseModel):
    incident_id: str
    principal_id: str
    environment: str = "production"
    category: str = "behavioral"  # 'behavioral', 'authentication', 'operational', 'data_quality', 'audit'
    scope: str
    started_at: int
    last_seen_at: int
    closed_at: Optional[int] = None
    status: str = "open"  # 'open', 'investigating', 'resolved', 'suppressed', 'accepted'
    score: int = 0
    priority: str = "low"  # 'low' (<20), 'medium' (20-49), 'high' (>=50)
    confidence: float = 1.0
    family_scores: Dict[str, int] = Field(default_factory=dict)
    contributing_event_ids: List[int] = Field(default_factory=list)
    suppressed_contributions: List[Dict[str, Any]] = Field(default_factory=list)
    successor_id: Optional[str] = None
    review_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[int] = None
    created_at: int
    updated_at: int

class OperatorOverride(BaseModel):
    id: Optional[int] = None
    scope_type: str
    scope_value: str
    reason: str
    operator: str
    created_at: int
    expires_at: Optional[int] = None
