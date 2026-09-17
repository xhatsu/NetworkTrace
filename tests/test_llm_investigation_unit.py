from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.models.investigation import (
    AnomalyEventRef, AssessmentV1, IncidentRef, PrincipalChangeEventRef,
    bounded_json,
)
from backend.app.services.investigation_evidence import (
    build_snapshot, canonical_json, safe_fraction, safe_rate,
)


def anomaly_row(**overrides):
    row = {"id": 9, "detected_at": 1_700_000_000_000, "anomaly_type": "traffic_spike", "severity": "high", "score": 41,
           "confidence": .8, "target_service": "orders", "first_seen": 1_700_000_000_000, "last_seen": 1_700_000_060_000,
           "status": "open", "reason_json": '[{"type":"traffic","contribution":41,"baseline":1,"current":2,"text":"ok"}]',
           "metadata_json": '{"environment":"staging","ignored":"drop"}'}
    row.update(overrides)
    return row


@pytest.mark.parametrize("ref", [
    AnomalyEventRef(kind="anomaly_event", anomaly_event_id="1"),
    PrincipalChangeEventRef(kind="principal_change_event", principal_change_event_id="1"),
    IncidentRef(kind="incident", incident_id="opaque-id"),
])
def test_three_source_refs_are_strict(ref):
    assert ref.model_dump()["kind"]
    with pytest.raises(ValidationError):
        type(ref)(**{**ref.model_dump(), "extra": 1})


def test_uint64_boundaries_and_rejections():
    assert AnomalyEventRef(kind="anomaly_event", anomaly_event_id="18446744073709551615")
    for value in ("0", "01", "18446744073709551616", "1.0", "true"):
        with pytest.raises(ValidationError):
            AnomalyEventRef(kind="anomaly_event", anomaly_event_id=value)


def test_snapshot_version_is_stable_and_protected_facts_change_it():
    ref = AnomalyEventRef(kind="anomaly_event", anomaly_event_id="9")
    first, _, _ = build_snapshot(ref, anomaly_row(), 1_700_000_100_000)
    second, _, _ = build_snapshot(ref, anomaly_row(), 1_700_000_200_000)
    changed, _, _ = build_snapshot(ref, anomaly_row(score=42), 1_700_000_100_000)
    assert first.source_version == second.source_version
    assert first.source_version != changed.source_version
    assert first.source_facts["score"] == 41


def test_change_window_and_incident_clip():
    change = {"id": 1, "fingerprint": "fp", "principal_name": "sale", "change_type": "NEW_TARGET", "severity": "high", "score": 20,
              "detected_at": 1_700_000_123_000, "target_service": "admin", "first_observed": 1_700_000_123_000,
              "status": "new", "updated_at": 1_700_000_123_000, "reason_json": "{}", "environment": "staging"}
    snapshot, _, _ = build_snapshot(PrincipalChangeEventRef(kind="principal_change_event", principal_change_event_id="1"), change, 1_700_000_124_000)
    assert snapshot.observation_window.basis == "inferred_15m_bucket"
    incident = {"incident_id": "i-1", "principal_id": "sale", "environment": "staging", "category": "behavioral", "scope": "bounded",
                "started_at": 1_700_000_000_000, "last_seen_at": 1_700_004_000_000, "status": "open", "score": 30, "priority": "high",
                "confidence": .5, "family_scores_json": "{}", "contributing_event_ids_json": "[]", "suppressed_contributions_json": "[]",
                "updated_at": 1_700_004_000_000}
    snapshot, _, _ = build_snapshot(IncidentRef(kind="incident", incident_id="i-1"), incident, 1_700_004_001_000)
    assert snapshot.observation_window.end_ms - snapshot.observation_window.start_ms == 60 * 60_000


def test_json_safety_and_math():
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert safe_rate(5, 0) is None
    assert safe_fraction(1, 0) is None
    with pytest.raises(ValueError):
        bounded_json({"nested": {"x": {"y": {"z": {"q": {"r": {"s": 1}}}}}}}, 1000)
    with pytest.raises(ValueError):
        bounded_json({"x": float("nan")}, 1000)


def test_prompt_marks_telemetry_untrusted_and_has_no_provider_secret():
    prompt = Path("backend/app/prompts/investigation_v1.txt").read_text(encoding="utf-8")
    assert "UNTRUSTED_TELEMETRY_DATA" in prompt
    assert "not a detector" in prompt
    assert "Authorization" not in prompt


def test_parse_object_resilience():
    from backend.app.services.investigation_provider import ProviderFailure, _parse_object

    assert _parse_object('{"a": 1}') == {"a": 1}
    assert _parse_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_object('```\n{"a": 1}\n```') == {"a": 1}
    assert _parse_object('<think>some reasoning</think>\n{"a": 1}') == {"a": 1}
    assert _parse_object('Result: {"a": 1} done') == {"a": 1}

    with pytest.raises(ProviderFailure):
        _parse_object('{"a": 1, "a": 2}')

    with pytest.raises(ProviderFailure):
        _parse_object('not json')

    with pytest.raises(ProviderFailure):
        _parse_object('[1, 2, 3]')

    with pytest.raises(ProviderFailure):
        _parse_object('{"a": NaN}')


def test_investigation_create_coerces_uuid_string():
    from uuid import UUID
    from backend.app.models.investigation import InvestigationCreate

    payload = {
        "finding": {"kind": "anomaly_event", "anomaly_event_id": "123"},
        "source_version": "a" * 64,
        "retry_of": "38b0b0e5-9980-5371-b11e-453f086c6485"
    }
    req = InvestigationCreate.model_validate(payload)
    assert isinstance(req.retry_of, UUID)
    assert str(req.retry_of) == "38b0b0e5-9980-5371-b11e-453f086c6485"


