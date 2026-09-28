from backend.app.models.semantic_assessment import SemanticAssessmentV1
from backend.app.services.change_episodes import (
    _change_signal,
    _merge_signals,
    attach_semantic_assessments,
)


def _change(change_id: int, change_type: str = "NEW_TARGET", **values):
    row = {
        "id": change_id,
        "principal_name": "payment_bot",
        "target_service": "billing-api",
        "operation": "createPayment",
        "change_type": change_type,
        "severity": "medium",
        "status": "new",
        "detected_at": 1_790_259_000_000 + change_id,
        "first_observed": 1_790_259_000_000 + change_id,
        "incident_id": "incident-1",
        "reason": {"summary": "new relationship"},
    }
    row.update(values)
    return _change_signal(row)


def _succeeded_row(episode):
    return {
        "episode_key": episode["episode_key"],
        "episode_version": episode["episode_version"],
        "assessment_version": "semantic-v1",
        "provider": "jev",
        "status": "succeeded",
        "abnormal_probability": 0.93,
        "category": "access_behavior",
        "priority": "investigate",
        "summary": "A new access relationship appeared with correlated traffic changes.",
        "supporting_signal_ids": episode["signal_ids"],
        "caveats": ["Source attribution is not independently verified."],
        "evaluated_at_ms": 1_790_259_000_000,
        "updated_at_ms": 1_790_259_000_000,
    }


def test_episode_identity_is_stable_and_new_evidence_changes_version():
    original = _merge_signals([_change(1)])[0]
    same = _merge_signals([_change(1)])[0]
    extended = _merge_signals([_change(1), _change(2, "NEW_OPERATION")])[0]

    assert original["episode_key"] == same["episode_key"] == extended["episode_key"]
    assert original["episode_version"] == same["episode_version"]
    assert original["episode_version"] != extended["episode_version"]


def test_l4_attachment_is_bulk_and_does_not_change_l3_state():
    episode = _merge_signals([_change(1), _change(2, "NEW_OPERATION")])[0]
    original_state = episode["state"]
    original_l3 = dict(episode["abnormality"])

    class Repository:
        calls = 0

        def get_latest_many(self, episode_keys):
            self.calls += 1
            assert episode_keys == [episode["episode_key"]]
            return [_succeeded_row(episode)]

    repository = Repository()
    attach_semantic_assessments([episode], repository)

    assert repository.calls == 1
    assert episode["state"] == original_state
    assert episode["abnormality"] == original_l3
    assert episode["semantic_assessment"]["status"] == "succeeded"
    assert episode["semantic_assessment"]["abnormal_probability"] == 0.93


def test_prior_episode_version_is_attached_as_stale():
    episode = _merge_signals([_change(1), _change(2, "NEW_OPERATION")])[0]
    previous = dict(episode)
    previous["episode_version"] = "a" * 64

    class Repository:
        def get_latest_many(self, episode_keys):
            row = _succeeded_row(previous)
            row["episode_version"] = previous["episode_version"]
            return [row]

    attach_semantic_assessments([episode], Repository())

    assert episode["semantic_assessment"]["status"] == "stale"
    assert episode["semantic_assessment"]["episode_version"] == "a" * 64
    assert episode["state"] == "changed"


def test_semantic_store_failure_leaves_episode_available():
    episode = _merge_signals([_change(1)])[0]

    class Repository:
        def get_latest_many(self, episode_keys):
            raise RuntimeError("storage unavailable")

    attach_semantic_assessments([episode], Repository())

    assert episode["state"] == "changed"
    assert episode["semantic_assessment"] == SemanticAssessmentV1(
        episode_version=episode["episode_version"]
    ).model_dump()
