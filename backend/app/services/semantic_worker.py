"""Opt-in background worker for L4 assessment; it is not called by Changes GETs."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from backend.app.models.semantic_assessment import SemanticAssessmentInputV1, SemanticAssessmentV1
from backend.app.repositories.semantic_assessment_repository import SemanticAssessmentRepository
from backend.app.services.semantic_provider import SemanticProvider


log = logging.getLogger("tracescope-hub")


def _assessment_input(episode: dict[str, Any]) -> SemanticAssessmentInputV1:
    signals = episode.get("signals") or []
    types = sorted({str(signal.get("type") or "unknown").upper() for signal in signals})
    safe_metrics: dict[str, float] = {}
    for highlight in episode.get("highlights") or []:
        label = str(highlight.get("label") or "").lower()
        if label in {"tps", "latency", "error"} and isinstance(highlight.get("delta"), (int, float)):
            safe_metrics[label] = float(highlight["delta"])
    abnormality = episode.get("abnormality") or {}
    source_types = set(types)
    return SemanticAssessmentInputV1(
        episode_version=str(episode.get("episode_version") or ""),
        episode={
            "subject_type": str((episode.get("subject") or {}).get("type") or "service"),
            "window_minutes": 15,
            "deterministic_state": str(episode.get("state") or "changed"),
            "domains": sorted(str(value) for value in abnormality.get("domains") or []),
            "signal_count": int(episode.get("signal_count") or len(signals)),
            "signals": types,
            "signal_ids": sorted(str(value) for value in episode.get("signal_ids") or []),
        },
        behavior={"metric_deltas_pct": safe_metrics},
        context={
            "new_target": bool(source_types & {"NEW_TARGET", "NEW_RELATIONSHIP", "NEW_SERVICE_EDGE"}),
            "new_operation": "NEW_OPERATION" in source_types,
            "new_source_ip": bool(source_types & {"NEW_SOURCE_IP", "IP_NEW_USER", "USER_NEW_SOURCE_IP"}),
            "source_ip_role": "known_infrastructure" if abnormality.get("infrastructure_only") else "unknown",
            "known_load_balancer": None if abnormality.get("infrastructure_only") else False,
        },
        detector_reasons=[str(reason) for reason in abnormality.get("reasons") or []][:30],
    )


class SemanticAssessmentWorker:
    """Worker primitive for an external scheduler; no provider is enabled by default."""

    def __init__(self, repository: SemanticAssessmentRepository | None = None,
                 provider: SemanticProvider | None = None, provider_model: str = ""):
        self.repository = repository or SemanticAssessmentRepository()
        self.provider = provider
        self.provider_model = provider_model

    async def run_once(self, episodes: list[dict[str, Any]]) -> dict[str, int]:
        if self.provider is None:
            return {"eligible": 0, "assessed": 0, "failed": 0}
        candidates = [episode for episode in episodes
                      if episode.get("state") in {"needs_attention", "critical"}
                      and not (episode.get("abnormality") or {}).get("infrastructure_only")]
        counts = {"eligible": len(candidates), "assessed": 0, "failed": 0}
        try:
            existing_rows = self.repository.get_latest_many(
                [str(episode.get("episode_key") or "") for episode in candidates]
            ) if candidates else []
        except Exception:
            log.warning("Could not load current semantic assessment versions", exc_info=True)
            return {"eligible": len(candidates), "assessed": 0, "failed": len(candidates)}
        existing = set()
        for row in existing_rows:
            value = row.get("episode_version") or ""
            version = value.rstrip(b"\x00").decode("utf-8") if isinstance(value, bytes) else str(value).rstrip("\x00")
            existing.add((str(row.get("episode_key") or ""), version))
        for episode in candidates:
            version = str(episode.get("episode_version") or "")
            key = str(episode.get("episode_key") or "")
            if not key or len(version) != 64:
                counts["failed"] += 1
                continue
            if (key, version) in existing:
                continue
            assessment_input = _assessment_input(episode)
            canonical = json.dumps(assessment_input.model_dump(by_alias=True), ensure_ascii=False,
                                   sort_keys=True, separators=(",", ":"), allow_nan=False)
            input_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            try:
                self.repository.mark_pending(key, version, input_digest=input_digest,
                                             provider_model=self.provider_model)
                result = await self.provider.assess(assessment_input)
                if result.status != "succeeded" or result.episode_version != version:
                    raise ValueError("provider returned an incomplete or stale assessment")
                result = result.model_copy(update={"provider": "jev", "assessment_version": "semantic-v1"})
                response_json = json.dumps(result.model_dump(), ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False)
                response_digest = hashlib.sha256(response_json.encode("utf-8")).hexdigest()
                self.repository.save(key, result, provider_model=self.provider_model,
                                     input_digest=input_digest, response_digest=response_digest)
                counts["assessed"] += 1
            except Exception:
                counts["failed"] += 1
                log.warning("Semantic assessment failed for episode key %s", key, exc_info=True)
                try:
                    self.repository.mark_failed(key, version, input_digest=input_digest,
                                                provider_model=self.provider_model)
                except Exception:
                    log.warning("Could not persist semantic assessment failure for episode key %s", key,
                                exc_info=True)
        return counts
