"""Opt-in background worker for L4 assessment; it is not called by Changes GETs."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from typing import Any

from backend.app.models.semantic_assessment import SemanticAssessmentInputV1, SemanticAssessmentV1
from backend.app.repositories.semantic_assessment_repository import SemanticAssessmentRepository
from backend.app.services.semantic_provider import SemanticProvider


log = logging.getLogger("tracescope-hub")


def _assessment_input(episode: dict[str, Any]) -> SemanticAssessmentInputV1:
    # Only bounded, structured facts leave the worker. Never send raw reasons,
    # entity names, payloads, addresses, or provider-selected evidence IDs.
    signals = (episode.get("signals") or [])[:100]
    types = sorted({str(signal.get("type") or "unknown").upper()[:64] for signal in signals})
    metrics = []
    for highlight in (episode.get("highlights") or [])[:8]:
        label = str(highlight.get("label") or "").lower()
        if label not in {"tps", "latency", "error"}:
            continue
        metric = {"label": label}
        for key in ("before", "after", "delta"):
            value = highlight.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                metric[key] = value
        metrics.append(metric)
    abnormality = episode.get("abnormality") or {}
    gates = [{key: gate.get(key) for key in ("type", "baseline_ready", "persistent", "material_impact", "level")}
             for gate in (abnormality.get("gates") or [])[:100]]
    return SemanticAssessmentInputV1(
        episode_version=str(episode.get("episode_version") or ""),
        episode={
            "subject_type": str((episode.get("subject") or {}).get("type") or "service"),
            "window_minutes": 15,
            "deterministic_state": str(episode.get("state") or "changed"),
            "signal_count": int(episode.get("signal_count") or len(signals)),
            "signals": types,
            "signal_ids": sorted({str(signal["id"]) for signal in signals})[:100],
            "signals_truncated": len(episode.get("signals") or []) > 100,
        },
        behavior={"metrics": metrics, "impact_gates": gates},
        context={"infrastructure_only": bool(abnormality.get("infrastructure_only")),
                 "baseline_confidence": abnormality.get("confidence", "limited")},
    )


class SemanticAssessmentWorker:
    """Worker primitive for an external scheduler; no provider is enabled by default."""

    def __init__(self, repository: SemanticAssessmentRepository | None = None,
                 provider: SemanticProvider | None = None, provider_model: str = "",
                 batch_size: int = 2, retry_seconds: int = 900):
        self.repository = repository or SemanticAssessmentRepository()
        self.provider = provider
        self.provider_model = provider_model
        self.batch_size = max(1, min(20, batch_size))
        self.retry_ms = max(60, retry_seconds) * 1000

    async def run_once(self, episodes: list[dict[str, Any]]) -> dict[str, int]:
        if self.provider is None:
            return {"eligible": 0, "assessed": 0, "failed": 0}
        candidates = [episode for episode in episodes
                      if episode.get("state") in {"changed", "watch", "needs_attention", "critical"}
                      and episode.get("status") != "resolved"
                      and not (episode.get("abnormality") or {}).get("infrastructure_only")]
        priority = {"critical": 0, "needs_attention": 1, "watch": 2, "changed": 3}
        candidates.sort(key=lambda episode: priority[episode["state"]])
        counts = {"eligible": len(candidates), "assessed": 0, "failed": 0}
        try:
            existing_rows = self.repository.get_latest_many(
                [str(episode.get("episode_key") or "") for episode in candidates]
            ) if candidates else []
        except Exception:
            log.warning("Could not load current semantic assessment versions", exc_info=True)
            return {"eligible": len(candidates), "assessed": 0, "failed": len(candidates)}
        existing = set()
        now_ms = int(time.time() * 1000)
        for row in existing_rows:
            value = row.get("episode_version") or ""
            version = value.rstrip(b"\x00").decode("utf-8") if isinstance(value, bytes) else str(value).rstrip("\x00")
            if ((row.get("status") == "succeeded" and row.get("recommendation"))
                    or now_ms - int(row.get("updated_at_ms") or 0) < self.retry_ms):
                existing.add((str(row.get("episode_key") or ""), version))
        attempts = 0
        for episode in candidates:
            if attempts >= self.batch_size:
                break
            version = str(episode.get("episode_version") or "")
            key = str(episode.get("episode_key") or "")
            if not key or len(version) != 64:
                counts["failed"] += 1
                continue
            if (key, version) in existing:
                continue
            attempts += 1
            existing.add((key, version))
            input_digest = hashlib.sha256(b"invalid-input").hexdigest()
            try:
                assessment_input = _assessment_input(episode)
                canonical = json.dumps(assessment_input.model_dump(by_alias=True), ensure_ascii=False,
                                       sort_keys=True, separators=(",", ":"), allow_nan=False)
                input_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                self.repository.mark_pending(key, version, input_digest=input_digest,
                                             provider_model=self.provider_model)
                result = await self.provider.assess(assessment_input)
                if result.status != "succeeded" or result.episode_version != version:
                    raise ValueError("provider returned an incomplete or stale assessment")
                result = SemanticAssessmentV1.model_validate(result.model_dump())
                if not result.recommendation or result.input_signal_ids != assessment_input.episode["signal_ids"]:
                    raise ValueError("provider returned invalid recommendation provenance")
                response_json = json.dumps(result.model_dump(), ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False)
                response_digest = hashlib.sha256(response_json.encode("utf-8")).hexdigest()
                self.repository.save(key, result, provider_model=self.provider_model,
                                     input_digest=input_digest, response_digest=response_digest)
                counts["assessed"] += 1
            except Exception:
                counts["failed"] += 1
                log.warning("Semantic assessment failed; deterministic episode is unchanged")
                try:
                    self.repository.mark_failed(key, version, input_digest=input_digest,
                                                provider_model=self.provider_model)
                except Exception:
                    log.warning("Could not persist semantic assessment failure")
        return counts
