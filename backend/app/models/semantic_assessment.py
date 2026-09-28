"""Provider-neutral contract for automatic L4 semantic assessments."""
from __future__ import annotations

import math
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AssessmentStatus = Literal["not_evaluated", "pending", "succeeded", "failed", "stale"]
AssessmentCategory = Literal[
    "access_behavior", "traffic", "performance", "errors", "authentication",
    "infrastructure", "identity", "mixed", "normal_variation", "insufficient_evidence",
]
AssessmentPriority = Literal["informational", "watch", "investigate", "urgent"]
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class SemanticAssessmentV1(BaseModel):
    """UI/API assessment record; it never changes the deterministic L3 result."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: AssessmentStatus = "not_evaluated"
    provider: Literal["jev"] | None = None
    provider_model: str | None = None
    provider_request_id: str | None = None
    assessment_version: Literal["semantic-v1"] = "semantic-v1"
    episode_version: str | None = None
    abnormal_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    category: AssessmentCategory | None = None
    category_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    category_probabilities: dict[AssessmentCategory, float] = Field(default_factory=dict)
    priority: AssessmentPriority | None = None
    priority_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    priority_probabilities: dict[AssessmentPriority, float] = Field(default_factory=dict)
    summary: str | None = Field(default=None, max_length=600)
    supporting_signal_ids: list[str] = Field(default_factory=list, max_length=100)
    caveats: list[str] = Field(default_factory=list, max_length=20)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    evaluated_at: int | None = Field(default=None, ge=0)

    @field_validator("episode_version")
    @classmethod
    def _episode_version_is_sha256(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_HEX.fullmatch(value):
            raise ValueError("episode_version must be lowercase SHA-256 hex")
        return value

    @field_validator("abnormal_probability")
    @classmethod
    def _probability_is_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("abnormal_probability must be finite")
        return value

    @field_validator("cost_usd")
    @classmethod
    def _cost_is_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("cost_usd must be finite")
        return value

    @field_validator("summary")
    @classmethod
    def _summary_is_trimmed(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _successful_assessment_is_complete(self) -> "SemanticAssessmentV1":
        if self.status == "succeeded":
            required = (self.provider, self.episode_version, self.abnormal_probability,
                        self.category, self.priority, self.evaluated_at)
            if any(value is None for value in required):
                raise ValueError("a succeeded assessment must include its result and evaluation time")
        return self


class JevNoulAnswerV1(BaseModel):
    """TypeSafe Noul answer: probability that a yes/no judgment is true."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["noul"]
    noul: float = Field(ge=0.0, le=1.0, strict=False)

    @field_validator("noul")
    @classmethod
    def _probability_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("noul must be finite")
        return value


class JevChoiceAnswerV1(BaseModel):
    """TypeSafe Choice answer with a selected option and full distribution."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0, strict=False)

    @field_validator("probabilities", mode="before")
    @classmethod
    def _probabilities_are_numeric(cls, value: object) -> dict[str, float]:
        if not isinstance(value, dict) or any(
            not isinstance(probability, (int, float)) or isinstance(probability, bool)
            for probability in value.values()
        ):
            raise ValueError("choice probabilities must be a numeric object")
        return {str(option): float(probability) for option, probability in value.items()}

    @field_validator("probabilities")
    @classmethod
    def _probabilities_are_finite(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(probability) or probability < 0.0 or probability > 1.0
               for probability in value.values()):
            raise ValueError("choice probabilities must be finite values between 0 and 1")
        if value and not math.isclose(sum(value.values()), 1.0, abs_tol=0.02):
            raise ValueError("choice probabilities must sum to 1")
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value


JevAnswerV1 = Annotated[
    Union[JevNoulAnswerV1, JevChoiceAnswerV1], Field(discriminator="type")
]


class JevUsageV1(BaseModel):
    """Usage and input cost reported by OpenRouter's Decisions API."""

    model_config = ConfigDict(extra="ignore", strict=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost: float | None = Field(default=None, ge=0.0, strict=False)

    @field_validator("cost")
    @classmethod
    def _cost_is_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("cost must be finite")
        return value


class JevDecisionResponseV1(BaseModel):
    """Typed OpenRouter Decisions response; unknown envelope metadata is ignored."""

    model_config = ConfigDict(extra="ignore", strict=True)

    model: str
    answers: dict[str, JevAnswerV1]
    usage: JevUsageV1
    id: str | None = None
    provider: str | None = None


class SemanticAssessmentInputV1(BaseModel):
    """Compact provider input contract. It intentionally has no raw IP or payload fields."""

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    schema_name: Literal["networktrace-semantic-input-v1"] = Field(
        default="networktrace-semantic-input-v1", alias="schema"
    )
    episode_version: str
    episode: dict[str, object]
    behavior: dict[str, object] = Field(default_factory=dict)
    context: dict[str, object] = Field(default_factory=dict)
    detector_reasons: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("episode_version")
    @classmethod
    def _input_episode_version_is_sha256(cls, value: str) -> str:
        if not SHA256_HEX.fullmatch(value):
            raise ValueError("episode_version must be lowercase SHA-256 hex")
        return value
