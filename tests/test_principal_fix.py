from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.db_context import get_connection
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.behavioral_engine import evaluate_readiness
from backend.app.services import principal_relationships as service
from backend.repository import StorageRepository


def _trace(index: int, timestamp_ms: int, *, principal: str = "batch-user") -> NormalizedTrace:
    return NormalizedTrace(
        event_uid=f"batch-event-{index}-{timestamp_ms}", timestamp=str(timestamp_ms),
        timestamp_ms=timestamp_ms, trace_id=f"batch-trace-{index}-{timestamp_ms}",
        span_id=f"batch-span-{index}-{timestamp_ms}", parent_span_id=None,
        service_name="target", service_instance="target-1", service_environment="production",
        caller_service="caller", caller_instance="caller-1", caller_ip="10.1.2.3",
        target_service="target", target_instance="target-1", target_ip="10.2.3.4",
        target_port=8080, principal_name=principal, principal_id=f"production:{principal}",
        operation="read", operation_key="target/read", http_method="GET", http_route="/read",
        http_status=200, status_class="2xx", duration_ms=2.0, duration_us=2000,
        outcome="success", protocol="http", span_kind="server", attributes_json="{}",
        created_at=timestamp_ms,
    )


@pytest.fixture
def principal_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "principal-fix.db")
    StorageRepository(db_path).migrate()
    return db_path


def _checkpoint(db_path: str) -> dict:
    with get_connection(db_path) as db:
        row = db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source='principal_intelligence'"
        ).fetchone()
    return json.loads(row[0])


def test_mid_batch_crash_resumes_without_duplicate_downstream_state(principal_db, monkeypatch):
    base = 1_700_000_000_000
    repo = TraceRepository(principal_db)
    repo.insert_traces([_trace(0, base)])
    service.process_principal_intelligence(principal_db)
    before_cursor = _checkpoint(principal_db)
    repo.insert_traces([_trace(1, base + 1), _trace(2, base + 2)])

    original_flush = service._BatchState.flush
    monkeypatch.setattr(service._BatchState, "flush", lambda self: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError, match="crash"):
        service.process_principal_intelligence(principal_db)
    assert _checkpoint(principal_db) == before_cursor

    monkeypatch.setattr(service._BatchState, "flush", original_flush)
    assert service.process_principal_intelligence(principal_db)["processed"] == 2
    assert service.process_principal_intelligence(principal_db)["processed"] == 0
    with get_connection(principal_db) as db:
        principal = db.execute(
            "SELECT total_requests FROM principals FINAL WHERE principal_name='batch-user'"
        ).fetchone()
        relationship = db.execute(
            "SELECT observation_count FROM principal_relationships FINAL WHERE principal_name='batch-user'"
        ).fetchone()
    assert principal[0] == 3
    assert relationship[0] == 3


def test_grouped_readiness_matches_legacy_full_scan(principal_db):
    base = 1_600_000_000_000
    TraceRepository(principal_db).insert_traces([
        _trace(i, base + i * 86_400_000, principal="ready-user") for i in range(12)
    ])
    with get_connection(principal_db) as db:
        row = db.execute(
            "SELECT ingest_order,row_uid,timestamp_ms,principal_name,service_environment,principal_id,operation_key,"
            "source_group,caller_service,caller_ip,target_service,operation,auth_result,http_status,outcome,"
            "caller_instance,target_instance,target_ip,target_port,http_method FROM traces LIMIT 1"
        ).fetchone()
        batch = service._BatchState(db, [row])
        for detector in ("NEW_CALLER", "UNUSUAL_TIME", "DORMANT_REACTIVATED", "OPERATION_MIX_SHIFT"):
            assert batch.ready("production:ready-user", detector, base + 12 * 86_400_000) == evaluate_readiness(
                db, "production:ready-user", detector, base + 12 * 86_400_000
            )


def test_batched_derived_writes_preserve_final_counts(principal_db):
    base = 1_700_100_000_000
    repo = TraceRepository(principal_db)
    repo.insert_traces([_trace(0, base)])
    service.process_principal_intelligence(principal_db)
    repo.insert_traces([_trace(i, base + i) for i in range(1, 5)])
    assert service.process_principal_intelligence(principal_db)["processed"] == 4
    with get_connection(principal_db) as db:
        assert db.execute("SELECT total_requests FROM principals FINAL WHERE principal_name='batch-user'").fetchone()[0] == 5
        assert db.execute("SELECT observation_count FROM principal_callers FINAL WHERE principal_name='batch-user'").fetchone()[0] == 5
        assert db.execute("SELECT observation_count FROM principal_targets FINAL WHERE principal_name='batch-user'").fetchone()[0] == 5
        assert db.execute("SELECT observation_count FROM historical_registry FINAL WHERE principal_id='production:batch-user' AND dimension_type='caller'").fetchone()[0] == 4


def test_incident_worker_paths_are_mutation_free():
    root = Path(__file__).resolve().parents[1]
    behavioral = (root / "backend/app/services/behavioral_engine.py").read_text()
    repository = (root / "backend/app/repositories/user_repository.py").read_text()
    assert "UPDATE incidents" not in behavioral
    assert "UPDATE incidents" not in repository
    assert "FROM incidents FINAL" in behavioral
    assert "FROM incidents FINAL" in repository


def test_budget_yields_after_durable_batch(principal_db, monkeypatch):
    base = 1_700_200_000_000
    repo = TraceRepository(principal_db)
    repo.insert_traces([_trace(0, base)])
    service.process_principal_intelligence(principal_db)
    repo.insert_traces([_trace(i, base + i) for i in range(1, 6)])
    monkeypatch.setattr(service, "PRINCIPAL_BATCH_SIZE", 2)
    monkeypatch.setattr(service, "settings", SimpleNamespace(
        principal_bootstrap_ratio=0.75, principal_dormant_days=30,
        analytics_stage_budget_seconds=0,
    ))
    first = service.process_principal_intelligence(principal_db)
    assert first["processed"] == 2
    assert service.process_principal_intelligence(principal_db)["processed"] == 2
    assert service.process_principal_intelligence(principal_db)["processed"] == 1
    assert service.process_principal_intelligence(principal_db)["processed"] == 0


def test_legacy_checkpoint_fields_are_preserved(principal_db):
    legacy = {"ingest_order": 0, "row_uid": service.ZERO_UUID if hasattr(service, "ZERO_UUID") else "00000000-0000-0000-0000-000000000000",
              "bootstrap_cutoff_ms": 1234, "ratio": 0.8, "legacy_marker": "keep"}
    with get_connection(principal_db) as db:
        db.execute("INSERT INTO checkpoints(source,cursor_json,updated_at_ms) VALUES(?,?,?)",
                   ("principal_intelligence", json.dumps(legacy), int(time.time() * 1000)))
    service.process_principal_intelligence(principal_db)
    saved = _checkpoint(principal_db)
    assert saved["bootstrap_cutoff_ms"] == 1234
    assert saved["ratio"] == 0.8
    assert saved["legacy_marker"] == "keep"
