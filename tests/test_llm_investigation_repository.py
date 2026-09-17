from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.repositories.investigation_repository import InvestigationRepository, TABLE_COLUMNS


class Result:
    column_names = list(TABLE_COLUMNS)
    result_rows = []


class FakeClient:
    def __init__(self):
        self.inserts = []

    def query(self, sql, parameters=None, settings=None):
        self.last = (sql, parameters, settings)
        return Result()

    def insert(self, table, rows, column_names):
        self.inserts.append((table, rows, column_names))


class Conn:
    def __init__(self, client): self.client = client
    def __enter__(self): return self
    def __exit__(self, *args): return False


def test_append_state_is_bounded_and_uses_native_insert():
    client = FakeClient()
    repo = InvestigationRepository(connection_factory=lambda _path: Conn(client))
    row = {column: None for column in TABLE_COLUMNS}
    row.update({"id": uuid4(), "dedup_key": "a" * 64, "retry_index": 0, "finding_kind": "anomaly_event", "finding_id": "1",
                "source_version": "b" * 64, "snapshot_schema_version": "finding-v1", "prompt_version": "investigation-v1",
                "result_schema_version": "assessment-v1", "policy_version": "policy-v1", "provider": "fake", "configured_model": "fake",
                "state": "queued", "state_version": 1, "cancel_requested": 0, "created_at_ms": 1, "updated_at_ms": 1,
                "deadline_ms": 2, "expires_at": datetime.now(timezone.utc), "snapshot_json": "{}", "evidence_json": "{}",
                "deterministic_summary_json": "{}", "metadata_json": "{}"})
    repo.append_state(row)
    assert client.inserts[0][0] == "llm_investigations"
    assert client.inserts[0][2] == list(TABLE_COLUMNS)
    assert client.last[2]["max_result_rows"] == 1000

