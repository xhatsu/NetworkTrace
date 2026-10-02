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
from backend.app.services.principal_activity import materialize_principal_activity
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


def _insert(db_path: str, traces: list[NormalizedTrace]) -> None:
    """Store raw traces and rebuild their whole rollup buckets, as the worker's aggregation does."""
    TraceRepository(db_path).insert_traces(traces)
    stamps = [trace.timestamp_ms for trace in traces]
    materialize_principal_activity(min(stamps), max(stamps) + 1, db_path)


def _checkpoint(db_path: str) -> dict:
    with get_connection(db_path) as db:
        row = db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source='principal_intelligence'"
        ).fetchone()
    return json.loads(row[0])


def test_mid_batch_crash_resumes_without_duplicate_downstream_state(principal_db, monkeypatch):
    base = 1_700_000_000_000
    _insert(principal_db, [_trace(0, base)])
    service.process_principal_intelligence(principal_db)
    before_cursor = _checkpoint(principal_db)
    # The same five-minute bucket is rewritten with 3 requests; only 2 are new.
    _insert(principal_db, [_trace(1, base + 1), _trace(2, base + 2)])

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
    _insert(principal_db, [_trace(i, base + i * 86_400_000, principal="ready-user") for i in range(12)])
    with get_connection(principal_db) as db:
        rows = service._fetch_page(db, (0, 0, 0), 0)
        service._apply_ledger(db, rows)
        batch = service._BatchState(db, rows[:1])
        for detector in ("NEW_CALLER", "UNUSUAL_TIME", "DORMANT_REACTIVATED", "OPERATION_MIX_SHIFT"):
            assert batch.ready("production:ready-user", detector, base + 12 * 86_400_000) == evaluate_readiness(
                db, "production:ready-user", detector, base + 12 * 86_400_000
            )


def test_batched_derived_writes_preserve_final_counts(principal_db):
    base = 1_700_100_000_000
    _insert(principal_db, [_trace(0, base)])
    service.process_principal_intelligence(principal_db)
    _insert(principal_db, [_trace(i, base + i) for i in range(1, 5)])
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
    _insert(principal_db, [_trace(0, base)])
    service.process_principal_intelligence(principal_db)
    # One rollup row per five-minute bucket, so the page size of 2 splits them.
    _insert(principal_db, [_trace(i, base + i * 300_000) for i in range(1, 6)])
    monkeypatch.setattr(service, "PRINCIPAL_BATCH_SIZE", 2)
    # Without the rescan overlap the pages are exactly the five new buckets.
    monkeypatch.setattr(service, "CURSOR_OVERLAP_MS", 0)
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


def test_trace_cursor_checkpoint_upgrade_does_not_recount(principal_db):
    base = 1_700_300_000_000
    _insert(principal_db, [_trace(i, base + i) for i in range(3)])
    legacy = {"ingest_order": 99, "row_uid": "00000000-0000-0000-0000-000000000000",
              "bootstrap_cutoff_ms": 1234, "ratio": 0.8}
    with get_connection(principal_db) as db:
        db.execute("INSERT INTO checkpoints(source,cursor_json,updated_at_ms) VALUES(?,?,?)",
                   ("principal_intelligence", json.dumps(legacy), int(time.time() * 1000)))
    # Rows already in the rollup were counted from traces under the old cursor.
    assert service.process_principal_intelligence(principal_db)["processed"] == 0
    _insert(principal_db, [_trace(i, base + i) for i in range(3, 5)])
    assert service.process_principal_intelligence(principal_db)["processed"] == 2


def test_shrinking_bucket_is_not_subtracted(principal_db):
    base = 1_700_400_000_000
    _insert(principal_db, [_trace(i, base + i) for i in range(3)])
    service.process_principal_intelligence(principal_db)
    with get_connection(principal_db) as db:
        db.execute("DELETE FROM traces WHERE timestamp_ms = ?", (base + 2,))
    materialize_principal_activity(base, base + 1, principal_db)
    assert service.process_principal_intelligence(principal_db)["processed"] == 0
    _insert(principal_db, [_trace(i, base + i) for i in (2, 3)])
    # The ledger keeps the larger count (3), so only the fourth request is new.
    assert service.process_principal_intelligence(principal_db)["processed"] == 1
    with get_connection(principal_db) as db:
        assert db.execute("SELECT total_requests FROM principals FINAL WHERE principal_name='batch-user'").fetchone()[0] == 4
