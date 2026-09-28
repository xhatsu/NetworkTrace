"""Exercise the configured semantic provider with synthetic, non-telemetry input."""
from __future__ import annotations

import asyncio
import json

from backend.app.models.semantic_assessment import SemanticAssessmentInputV1
from backend.app.services.semantic_provider import OpenRouterSemanticProvider
from backend.config import settings


async def main() -> None:
    provider = OpenRouterSemanticProvider(settings)
    assessment_input = SemanticAssessmentInputV1(
        episode_version="a" * 64,
        episode={
            "subject_type": "user",
            "window_minutes": 15,
            "deterministic_state": "needs_attention",
            "domains": ["access", "traffic"],
            "signal_count": 2,
            "signals": ["NEW_TARGET", "PRINCIPAL_RATE_SURGE"],
            "signal_ids": ["chg-synthetic-1", "chg-synthetic-2"],
        },
        behavior={"metric_deltas_pct": {"tps": 120.0}},
        context={"new_target": True, "new_source_ip": False, "source_ip_role": "unknown"},
        detector_reasons=["Two correlated synthetic changes were observed."],
    )
    assessment = await provider.assess(assessment_input)
    if assessment.status != "succeeded" or assessment.episode_version != assessment_input.episode_version:
        raise RuntimeError("provider did not return a matching semantic assessment")
    print(json.dumps({
        "ok": True,
        "provider": assessment.provider,
        "model": assessment.provider_model or settings.semantic_model,
        "provider_request_id": assessment.provider_request_id,
        "abnormal_probability": assessment.abnormal_probability,
        "category": assessment.category,
        "category_confidence": assessment.category_confidence,
        "category_probabilities": assessment.category_probabilities,
        "priority": assessment.priority,
        "priority_confidence": assessment.priority_confidence,
        "priority_probabilities": assessment.priority_probabilities,
        "input_tokens": assessment.input_tokens,
        "output_tokens": assessment.output_tokens,
        "cost_usd": assessment.cost_usd,
        "evaluated_at": assessment.evaluated_at,
    }, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
