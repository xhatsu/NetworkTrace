"""Provider boundary for typed Jev L4 assessments through OpenRouter."""
from __future__ import annotations

import time
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from backend.app.models.semantic_assessment import (
    AssessmentCategory,
    AssessmentPriority,
    JevChoiceAnswerV1,
    JevDecisionResponseV1,
    JevNoulAnswerV1,
    SemanticAssessmentInputV1,
    SemanticAssessmentV1,
)
from backend.config import settings


CATEGORY_CRITERIA: dict[AssessmentCategory, str] = {
    "access_behavior": "Novel target or access pattern.",
    "traffic": "Request volume or traffic rate change.",
    "performance": "Latency or resource performance change.",
    "errors": "Failures or error-rate change.",
    "authentication": "Authentication behavior change.",
    "infrastructure": "Infrastructure or routing transition.",
    "identity": "Identity lifecycle or credential behavior.",
    "mixed": "More than one category is equally central.",
    "normal_variation": "Expected variation with no material anomaly.",
    "insufficient_evidence": "Evidence is too limited to choose another category.",
}
PRIORITY_CRITERIA: dict[AssessmentPriority, str] = {
    "informational": "No follow-up is normally needed.",
    "watch": "Monitor for persistence or recurrence.",
    "investigate": "Operator review is warranted.",
    "urgent": "Prompt operator response is warranted.",
}


class SemanticProvider(Protocol):
    async def assess(self, assessment_input: SemanticAssessmentInputV1) -> SemanticAssessmentV1:
        """Return a validated semantic assessment for one normalized episode."""


class SemanticProviderNotConfigured(RuntimeError):
    """Raised when an assessment is requested before a provider is configured."""


class DisabledSemanticProvider:
    """Explicit no-op provider used while semantic assessment is disabled."""

    async def assess(self, assessment_input: SemanticAssessmentInputV1) -> SemanticAssessmentV1:
        del assessment_input
        raise SemanticProviderNotConfigured("semantic provider is not configured")


class OpenRouterSemanticProvider:
    """OpenRouter Decisions API adapter for TypeSafe's typed Jev model."""

    name = "openrouter"
    endpoint = "/api/alpha/decisions"

    def __init__(self, settings_obj: Any = settings, client: httpx.AsyncClient | None = None):
        self.settings = settings_obj
        self._client = client
        self._validate_settings()

    def _validate_settings(self) -> None:
        base_url = str(getattr(self.settings, "semantic_base_url", "")).rstrip("/")
        parsed = urlparse(base_url)
        if (parsed.scheme != "https" or parsed.hostname != "openrouter.ai"
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise SemanticProviderNotConfigured("invalid OpenRouter base URL")
        model = str(getattr(self.settings, "semantic_model", ""))
        if not getattr(self.settings, "semantic_api_key", "") or not model:
            raise SemanticProviderNotConfigured("OpenRouter credentials or model are not configured")
        if model not in {"typesafe/jev-1.13", "~typesafe/jev-latest"}:
            raise SemanticProviderNotConfigured("unsupported TypeSafe Jev model")
        timeout = int(getattr(self.settings, "semantic_timeout_seconds", 30))
        if timeout < 1 or timeout > 60:
            raise SemanticProviderNotConfigured("semantic provider timeout is outside the allowed range")

    async def assess(self, assessment_input: SemanticAssessmentInputV1) -> SemanticAssessmentV1:
        request_body = {
            "model": self.settings.semantic_model,
            "state": assessment_input.model_dump(by_alias=True),
            "questions": {
                "abnormality": {
                    "type": "noul",
                    "instructions": (
                        "Is this episode's behavior materially abnormal compared with its established baseline? "
                        "Judge only the supplied evidence."
                    ),
                    "criteria": {
                        "true": "The supplied changes indicate materially unusual behavior.",
                        "false": "The evidence is consistent with expected variation or is insufficient.",
                    },
                },
                "category": {
                    "type": "choice",
                    "instructions": "Choose the primary semantic category for this episode.",
                    "criteria": CATEGORY_CRITERIA,
                },
                "priority": {
                    "type": "choice",
                    "instructions": "Choose the operator follow-up priority for this episode.",
                    "criteria": PRIORITY_CRITERIA,
                },
            },
        }
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.settings.semantic_base_url,
            verify=True,
            timeout=httpx.Timeout(float(self.settings.semantic_timeout_seconds), connect=5.0),
            follow_redirects=False,
            trust_env=False,
            headers={
                "Authorization": "Bearer " + self.settings.semantic_api_key,
                "Content-Type": "application/json",
                "X-Title": "TraceScope semantic assessment",
            },
        )
        try:
            try:
                response = await client.post(self.endpoint, json=request_body)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise SemanticProviderNotConfigured("OpenRouter Jev request failed") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                raise SemanticProviderNotConfigured("OpenRouter redirected the Jev request")
            if response.status_code in {401, 403}:
                raise SemanticProviderNotConfigured("OpenRouter rejected the API key")
            if response.status_code == 402:
                raise SemanticProviderNotConfigured("OpenRouter account cannot cover the Jev input charge")
            if response.status_code in {429, 529}:
                raise SemanticProviderNotConfigured("OpenRouter Jev rate limit or capacity limit reached")
            if response.status_code != 200 or len(response.content) > 16 * 1024:
                raise SemanticProviderNotConfigured(
                    f"OpenRouter Jev returned an invalid response (HTTP {response.status_code})"
                )
            try:
                result = JevDecisionResponseV1.model_validate_json(response.content)
            except ValidationError as exc:
                raise SemanticProviderNotConfigured("OpenRouter Jev response failed typed validation") from exc

            if not result.model.startswith("typesafe/jev-1.13"):
                raise SemanticProviderNotConfigured("OpenRouter returned an unexpected Jev model version")
            if set(result.answers) != {"abnormality", "category", "priority"}:
                raise SemanticProviderNotConfigured("OpenRouter Jev response did not match the requested questions")
            abnormality = result.answers["abnormality"]
            category = result.answers["category"]
            priority = result.answers["priority"]
            if not isinstance(abnormality, JevNoulAnswerV1):
                raise SemanticProviderNotConfigured("Jev abnormality answer had the wrong primitive type")
            if not isinstance(category, JevChoiceAnswerV1) or not isinstance(priority, JevChoiceAnswerV1):
                raise SemanticProviderNotConfigured("Jev category or priority answer had the wrong primitive type")
            if category.choice not in CATEGORY_CRITERIA or set(category.probabilities) != set(CATEGORY_CRITERIA):
                raise SemanticProviderNotConfigured("Jev category answer did not match the declared options")
            if priority.choice not in PRIORITY_CRITERIA or set(priority.probabilities) != set(PRIORITY_CRITERIA):
                raise SemanticProviderNotConfigured("Jev priority answer did not match the declared options")

            # Jev produces typed choices and probabilities, not free-form prose or evidence attribution.
            return SemanticAssessmentV1(
                status="succeeded",
                provider="jev",
                provider_model=result.model,
                provider_request_id=result.id,
                assessment_version="semantic-v1",
                episode_version=assessment_input.episode_version,
                abnormal_probability=abnormality.noul,
                category=category.choice,
                category_confidence=category.confidence,
                category_probabilities=category.probabilities,
                priority=priority.choice,
                priority_confidence=priority.confidence,
                priority_probabilities=priority.probabilities,
                summary=None,
                supporting_signal_ids=[],
                caveats=[],
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=result.usage.cost,
                evaluated_at=int(time.time() * 1000),
            )
        finally:
            if own_client:
                await client.aclose()


def create_semantic_provider(settings_obj: Any = settings) -> SemanticProvider | None:
    """Return an explicitly enabled provider; disabled mode makes no network calls."""
    if not getattr(settings_obj, "semantic_assessment_enabled", False):
        return None
    provider_name = getattr(settings_obj, "semantic_provider", "openrouter")
    if provider_name == "openrouter":
        return OpenRouterSemanticProvider(settings_obj)
    raise SemanticProviderNotConfigured("unsupported semantic provider")
