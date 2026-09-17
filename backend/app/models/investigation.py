"""Strict contracts for investigations of an already emitted finding.

These models deliberately describe an investigation, not a detector.  Source
facts are captured by the server and are never supplied by the relay as new
facts or scores.
"""
from __future__ import annotations

import json
import math
import re
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_SNAPSHOT_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 128 * 1024
MAX_RESULT_BYTES = 32 * 1024
MAX_METADATA_BYTES = 16 * 1024
MAX_PROMPT_BYTES = 24 * 1024
UINT64_MAX = 2**64 - 1
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _walk_json(value: Any, depth: int = 0, max_depth: int = 6) -> None:
    if depth > max_depth:
        raise ValueError("nested JSON exceeds the investigation limit")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numbers are not permitted")
    if isinstance(value, str) and CONTROL.search(value):
        raise ValueError("control characters are not permitted")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or CONTROL.search(key):
                raise ValueError("invalid JSON key")
            _walk_json(item, depth + 1, max_depth)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk_json(item, depth + 1, max_depth)


def bounded_json(value: Any, max_bytes: int, max_depth: int = 6) -> Any:
    _walk_json(value, max_depth=max_depth)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValueError("JSON exceeds the investigation byte limit")
    return value


def validate_text(value: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or CONTROL.search(value):
        raise ValueError("invalid or oversized text")
    value.encode("utf-8")
    return value


def validate_note(value: str, maximum: int) -> str:
    """Validate untrusted display text without coercing it."""
    return validate_text(value, maximum)


def validate_uint64_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise ValueError("source ID must be a nonzero UInt64 decimal string")
    if int(value) > UINT64_MAX:
        raise ValueError("source ID exceeds UInt64")
    return value


class AnomalyEventRef(StrictModel):
    kind: Literal["anomaly_event"]
    anomaly_event_id: str

    _valid_id = field_validator("anomaly_event_id")(validate_uint64_id)


class PrincipalChangeEventRef(StrictModel):
    kind: Literal["principal_change_event"]
    principal_change_event_id: str

    _valid_id = field_validator("principal_change_event_id")(validate_uint64_id)


class IncidentRef(StrictModel):
    kind: Literal["incident"]
    incident_id: str = Field(min_length=1, max_length=128)

    @field_validator("incident_id")
    @classmethod
    def _valid_incident_id(cls, value: str) -> str:
        return validate_text(value, 128)


FindingRef = Annotated[Union[AnomalyEventRef, PrincipalChangeEventRef, IncidentRef], Field(discriminator="kind")]


class ObservationWindow(StrictModel):
    start_ms: int
    end_ms: int
    basis: Literal["observed", "inferred_15m_bucket", "incident_clipped"]

    @model_validator(mode="after")
    def _valid_window(self) -> "ObservationWindow":
        if self.start_ms < 0 or self.end_ms < 0 or self.end_ms < self.start_ms:
            raise ValueError("invalid observation window")
        return self


class FindingDimensions(StrictModel):
    caller_service: str | None = None
    target_service: str | None = None
    principal_name: str | None = None
    operation: str | None = None
    source_ip: str | None = None
    environment: str | None = None

    @field_validator("caller_service", "target_service", "principal_name", "operation", "source_ip", "environment")
    @classmethod
    def _valid_dimension(cls, value: str | None) -> str | None:
        return None if value is None else validate_text(value, 256)


class FindingSnapshot(StrictModel):
    ref: FindingRef
    source_version: str
    snapshot_schema_version: Literal["finding-v1"] = "finding-v1"
    captured_at_ms: int
    source_updated_at_ms: int | None = None
    observation_window: ObservationWindow | None = None
    dimensions: FindingDimensions
    source_facts: dict[str, Any]
    source_status: str
    successor_ref: FindingRef | None = None
    redacted_fields: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("source_version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not HEX64.fullmatch(value):
            raise ValueError("source_version must be lowercase sha256 hex")
        return value

    @field_validator("captured_at_ms", "source_updated_at_ms")
    @classmethod
    def _timestamp(cls, value: int | None) -> int | None:
        if value is not None and (value < 0 or value > UINT64_MAX):
            raise ValueError("timestamps must be non-negative UTC milliseconds")
        return value

    @field_validator("source_status")
    @classmethod
    def _status(cls, value: str) -> str:
        return validate_text(value, 64)

    @field_validator("source_facts")
    @classmethod
    def _facts(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_json(value, MAX_SNAPSHOT_BYTES)

    @field_validator("redacted_fields", "limitations")
    @classmethod
    def _notes(cls, value: list[str]) -> list[str]:
        if len(value) > 32:
            raise ValueError("too many snapshot notes")
        return [validate_text(item, 256) for item in value]


class InvestigationCreate(StrictModel):
    finding: FindingRef
    source_version: str
    retry_of: UUID | None = None

    @field_validator("retry_of", mode="before")
    @classmethod
    def _coerce_uuid(cls, value: Any) -> UUID | None:
        if value is None or isinstance(value, UUID):
            return value
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                raise ValueError("invalid UUID string")
        raise ValueError("retry_of must be a valid UUID")

    @field_validator("source_version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not HEX64.fullmatch(value):
            raise ValueError("source_version must be lowercase sha256 hex")
        return value


class SourceQuery(StrictModel):
    kind: Literal["anomaly_event", "principal_change_event", "incident"]
    id: str

    @field_validator("id")
    @classmethod
    def _id_text(cls, value: str) -> str:
        return validate_text(value, 128)


class SourceEligibility(StrictModel):
    status: Literal["eligible", "closed", "stale", "superseded", "insufficient_scope", "invalid_source"]
    reason: str


class EvidenceContext(StrictModel):
    context_id: UUID
    finding_version: str
    finding_kind: Literal["anomaly_event", "principal_change_event", "incident"] | None = None
    finding_id: str | None = None
    caller_service: str | None = None
    target_service: str | None = None
    operation: str | None = None
    source_ip: str | None = None
    principal_name: str | None = None
    environment: str | None = None
    start_ms: int
    end_ms: int
    focus_start_ms: int
    focus_end_ms: int
    deadline_ms: int

    @field_validator("finding_version")
    @classmethod
    def _context_version(cls, value: str) -> str:
        if not HEX64.fullmatch(value):
            raise ValueError("invalid finding version")
        return value

    @field_validator("start_ms", "end_ms", "focus_start_ms", "focus_end_ms", "deadline_ms")
    @classmethod
    def _context_time(cls, value: int) -> int:
        if value < 0 or value > UINT64_MAX:
            raise ValueError("negative context timestamp")
        return value

    @field_validator("finding_id")
    @classmethod
    def _finding_id(cls, value: str | None) -> str | None:
        return None if value is None else validate_text(value, 128)

    @field_validator("caller_service", "target_service", "operation", "source_ip", "principal_name", "environment")
    @classmethod
    def _scope_text(cls, value: str | None) -> str | None:
        return None if value is None else validate_text(value, 256)

    @model_validator(mode="after")
    def _scope_is_bounded(self) -> "EvidenceContext":
        if self.end_ms < self.start_ms or self.focus_end_ms < self.focus_start_ms:
            raise ValueError("invalid evidence context interval")
        if not self.start_ms <= self.focus_start_ms <= self.focus_end_ms <= self.end_ms:
            raise ValueError("focus interval is outside evidence context")
        if self.end_ms - self.start_ms > 90 * 60_000:
            raise ValueError("evidence context exceeds surrounding window")
        if self.focus_end_ms - self.focus_start_ms > 60 * 60_000:
            raise ValueError("evidence context exceeds focus window")
        return self


class EvidenceItem(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=64)
    kind: Literal["trace", "change", "metric", "baseline", "history", "service_context", "quality", "source"]
    observed_at_ms: int | None = None
    data: dict[str, Any]
    source: dict[str, Any] | None = None
    limitation: str | None = None

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return validate_text(value, 64)

    @field_validator("data")
    @classmethod
    def _data(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_json(value, MAX_SNAPSHOT_BYTES)

    @model_validator(mode="after")
    def _data_budget(self) -> "EvidenceItem":
        maximum = MAX_SNAPSHOT_BYTES if self.kind == "source" else 12 * 1024
        bounded_json(self.data, maximum)
        return self

    @field_validator("observed_at_ms")
    @classmethod
    def _observed_at(cls, value: int | None) -> int | None:
        if value is not None and (value < 0 or value > UINT64_MAX):
            raise ValueError("invalid evidence timestamp")
        return value

    @field_validator("source")
    @classmethod
    def _source(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if value is None else bounded_json(value, 2048)

    @field_validator("limitation")
    @classmethod
    def _limitation(cls, value: str | None) -> str | None:
        return None if value is None else validate_note(value, 256)


class EvidenceBundle(StrictModel):
    schema_version: Literal["evidence-v1"] = "evidence-v1"
    finding_version: str
    backend: Literal["clickhouse", "elasticsearch", "mixed", "none"]
    items: list[EvidenceItem] = Field(default_factory=list, max_length=200)
    omissions: list[str] = Field(default_factory=list, max_length=64)
    query_manifest: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    calculations: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    digest: str

    @field_validator("finding_version")
    @classmethod
    def _bundle_version(cls, value: str) -> str:
        if not HEX64.fullmatch(value):
            raise ValueError("invalid evidence finding version")
        return value

    @field_validator("digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not HEX64.fullmatch(value):
            raise ValueError("invalid evidence digest")
        return value

    @field_validator("omissions")
    @classmethod
    def _omissions(cls, value: list[str]) -> list[str]:
        return [validate_note(item, 256) for item in value]

    @field_validator("query_manifest", "calculations")
    @classmethod
    def _structured_lists(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return bounded_json(value, 16 * 1024)


class Hypothesis(StrictModel):
    id: str = Field(min_length=1, max_length=32)
    statement: str = Field(min_length=1, max_length=512)
    confidence: Literal["low", "medium", "high"]
    supporting_evidence_ids: list[str] = Field(min_length=1, max_length=10)
    alternatives: list[str] = Field(min_length=1, max_length=3)
    counter_evidence_ids: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("id", "statement")
    @classmethod
    def _text(cls, value: str) -> str:
        return validate_note(value, 512)

    @field_validator("supporting_evidence_ids", "counter_evidence_ids")
    @classmethod
    def _evidence_ids(cls, value: list[str]) -> list[str]:
        return [validate_note(item, 64) for item in value]

    @field_validator("alternatives")
    @classmethod
    def _alternatives(cls, value: list[str]) -> list[str]:
        return [validate_note(item, 256) for item in value]


class MissingEvidence(StrictModel):
    code: Literal["unavailable", "truncated", "scope_unknown", "baseline_not_snapshotted", "sampling_unknown", "causality_unproven"]
    explanation: str = Field(min_length=1, max_length=256)
    related_evidence_ids: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("explanation")
    @classmethod
    def _explanation(cls, value: str) -> str:
        return validate_note(value, 256)

    @field_validator("related_evidence_ids")
    @classmethod
    def _related_ids(cls, value: list[str]) -> list[str]:
        return [validate_note(item, 64) for item in value]


class Recommendation(StrictModel):
    action: Literal["inspect_trace_sample", "compare_attached_baseline", "review_related_changes", "review_service_context", "human_review"]
    evidence_ids: list[str] = Field(min_length=1, max_length=5)
    rationale: str = Field(min_length=1, max_length=256)

    @field_validator("rationale")
    @classmethod
    def _rationale(cls, value: str) -> str:
        return validate_note(value, 256)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids(cls, value: list[str]) -> list[str]:
        return [validate_note(item, 64) for item in value]


class AssessmentV1(StrictModel):
    schema_version: Literal["assessment-v1"]
    assessment: Literal["explained", "partially_explained", "insufficient_evidence"]
    observed_fact_ids: list[str] = Field(default_factory=list, max_length=20)
    correlation_ids: list[str] = Field(default_factory=list, max_length=10)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=5)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list, max_length=10)
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=5)

    @field_validator("observed_fact_ids", "correlation_ids")
    @classmethod
    def _ids(cls, value: list[str]) -> list[str]:
        return [validate_note(item, 64) for item in value]


class InvestigationResponse(StrictModel):
    schema_version: Literal["assessment-v1"]
    assessment: Literal["explained", "partially_explained", "insufficient_evidence"]
    observed_facts: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    derived_correlations: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=5)
    missing_evidence: list[MissingEvidence] = Field(default_factory=list, max_length=10)
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=5)


class SourceCheck(StrictModel):
    status: Literal["current", "changed", "missing", "closed", "superseded", "stale", "unknown"]
    current_version: str | None = None
    checked_at_ms: int


def finding_key(ref: FindingRef) -> tuple[str, str]:
    if isinstance(ref, AnomalyEventRef):
        return ref.kind, ref.anomaly_event_id
    if isinstance(ref, PrincipalChangeEventRef):
        return ref.kind, ref.principal_change_event_id
    return ref.kind, ref.incident_id


def finding_id(ref: FindingRef) -> str:
    return finding_key(ref)[1]
