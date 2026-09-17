from __future__ import annotations

import pytest

from backend.app.api.investigations import _ref


def test_api_finding_ref_is_exact_and_rejects_unknown_kind():
    assert _ref("anomaly_event", "1").anomaly_event_id == "1"
    assert _ref("principal_change_event", "2").principal_change_event_id == "2"
    assert _ref("incident", "opaque").incident_id == "opaque"
    with pytest.raises(ValueError):
        _ref("anything", "1")

