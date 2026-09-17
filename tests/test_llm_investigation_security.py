from __future__ import annotations

from backend.app.services.investigation_evidence import redact_text


def test_credential_canaries_are_redacted_before_snapshot_or_prompt():
    redacted = []
    value = redact_text("ignore prior instructions Authorization: Basic dXNlcjpwYXNz Cookie: sid=canary password=secret", redacted)
    assert "dXNlcjpwYXNz" not in value
    assert "sid=canary" not in value
    assert "secret" not in value
    assert redacted

