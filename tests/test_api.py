from datetime import datetime, timedelta, timezone

from backend.models import AnomalyPatch, QueryFilters
import pytest


def test_query_range_is_bounded():
    with pytest.raises(ValueError):
        QueryFilters(start=datetime.now(timezone.utc)-timedelta(days=32),end=datetime.now(timezone.utc))


def test_suppression_requires_expiry():
    with pytest.raises(ValueError): AnomalyPatch(status="suppressed")


def test_trace_list_time_filters_alter_results(tmp_path):
    from backend.repository import StorageRepository
    from backend.app.repositories.trace_repository import TraceRepository
    from backend.app.models.trace import NormalizedTrace

    db_path = str(tmp_path / "time_filter_test.db")
    StorageRepository(db_path).migrate()
    repo = TraceRepository(db_path)

    t1 = NormalizedTrace(
        event_uid="t-1",
        timestamp="1000",
        timestamp_ms=1000,
        trace_id="tr-1",
        span_id="sp-1",
        service_name="srv",
        target_service="srv",
        operation="op",
        attributes_json="{}",
        duration_ms=5.0,
        duration_us=5000,
        created_at=1000,
    )
    t2 = NormalizedTrace(
        event_uid="t-2",
        timestamp="5000",
        timestamp_ms=5000,
        trace_id="tr-2",
        span_id="sp-2",
        service_name="srv",
        target_service="srv",
        operation="op",
        attributes_json="{}",
        duration_ms=5.0,
        duration_us=5000,
        created_at=5000,
    )
    repo.insert_traces([t1, t2])

    all_rows = repo.list_traces()
    assert len(all_rows) == 2

    early_rows = repo.list_traces(start_ms=0, end_ms=3000)
    assert len(early_rows) == 1
    assert early_rows[0]["trace_id"] == "tr-1"

    late_rows = repo.list_traces(start_ms=3000, end_ms=10000)
    assert len(late_rows) == 1
    assert late_rows[0]["trace_id"] == "tr-2"


