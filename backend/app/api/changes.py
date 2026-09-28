"""HTTP routes for deterministic Change episodes with stored L4 context."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.app.services.change_episodes import (
    _filter_episodes,
    _load_signals,
    _merge_signals,
    _window,
    attach_semantic_assessments,
    get_source_signals,
)


router = APIRouter(prefix="/api/v1", tags=["changes"])


@router.get("/changes")
async def list_changes(
    from_time: Optional[Any] = Query(None, alias="from"),
    to_time: Optional[Any] = Query(None, alias="to"),
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    subject_type: Optional[str] = Query(None, alias="subject"),
    state: Optional[str] = None,
    status: Optional[str] = None,
    service: Optional[str] = None,
    principal: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    start_ms, end_ms = _window(from_time, to_time, start, end)
    signals = _load_signals(start_ms, end_ms, min(500, max(limit * 3, 100)))
    episodes = _filter_episodes(
        _merge_signals(signals), subject_type=subject_type, state=state,
        status=status, service=service, principal=principal, search=q,
    )
    attach_semantic_assessments(episodes)
    items = episodes[:limit]
    return {
        "items": items,
        "count": len(items),
        "total": len(episodes),
        "summary": {
            "expected": sum(item["state"] == "expected" for item in episodes),
            "changed": sum(item["state"] == "changed" and item["status"] != "resolved" for item in episodes),
            "needs_attention": sum(item["state"] in {"needs_attention", "critical"} and item["status"] != "resolved" for item in episodes),
            "critical": sum(item["state"] == "critical" and item["status"] != "resolved" for item in episodes),
            "watch": sum(item["state"] == "watch" and item["status"] != "resolved" for item in episodes),
            "reviewed": sum(item["state"] == "expected" or item["status"] == "resolved" for item in episodes),
            "changed_users": sum(item["subject"]["type"] == "user" and item["status"] != "resolved" for item in episodes),
            "changed_services": sum(item["subject"]["type"] == "service" and item["status"] != "resolved" for item in episodes),
            "l4_evaluated": sum(item["semantic_assessment"]["status"] == "succeeded" for item in episodes),
            "l4_pending": sum(item["semantic_assessment"]["status"] == "pending" for item in episodes),
            "l4_high_confidence": sum(
                item["semantic_assessment"]["status"] == "succeeded"
                and (item["semantic_assessment"].get("abnormal_probability") or 0) >= 0.8
                for item in episodes
            ),
            "l4_not_evaluated": sum(item["semantic_assessment"]["status"] == "not_evaluated" for item in episodes),
        },
    }


@router.get("/changes/{episode_id}")
async def get_change_episode(
    episode_id: str,
    from_time: Optional[Any] = Query(None, alias="from"),
    to_time: Optional[Any] = Query(None, alias="to"),
    start: Optional[Any] = None,
    end: Optional[Any] = None,
) -> dict[str, Any]:
    start_ms, end_ms = _window(from_time, to_time, start, end)
    source_signals = get_source_signals(episode_id)
    if source_signals:
        related_start = min(signal["started_at"] for signal in source_signals) - 900_000
        related_end = max(signal["last_seen_at"] for signal in source_signals) + 900_001
        signals = _load_signals(related_start, related_end, 500)
        known_ids = {signal["id"] for signal in signals}
        signals.extend(signal for signal in source_signals if signal["id"] not in known_ids)
    elif episode_id.isdigit() or episode_id.startswith(("chg-", "anm-")):
        signals = []
    else:
        signals = _load_signals(start_ms, end_ms, 500)

    episodes = _merge_signals(signals)
    requested_ids = {episode_id, *(signal["id"] for signal in source_signals)}
    item = next(
        (episode for episode in episodes
         if requested_ids.intersection(episode.get("signal_ids", [])) or episode.get("id") in requested_ids),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Change episode not found")
    attach_semantic_assessments([item])
    item["timeline"] = [
        {"at": signal["detected_at"], "type": signal["type"], "source": signal["source"]}
        for signal in sorted(item.get("signals", []), key=lambda value: value["detected_at"])
    ]
    item["debug"] = {
        "signals": item.get("signals", []),
        "scores_are_secondary": True,
        "note": "Detector scores and baseline mechanics remain available in the source evidence.",
    }
    return item
