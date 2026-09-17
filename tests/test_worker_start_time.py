import json
import time
from datetime import datetime, timezone
import pytest

from backend.config import Settings, _parse_timestamp_setting, settings
from backend.repository import StorageRepository
from backend.app.services.aggregation import aggregate_traces
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.normalization import normalize_otel_record
from backend.app.repositories.db_context import get_connection
from backend.elasticsearch import ElasticsearchReader


def test_parse_timestamp_setting():
    # ISO-8601 with Z
    iso_z = "2026-09-16T12:00:00Z"
    expected_ms = int(datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert _parse_timestamp_setting(iso_z) == expected_ms

    # ISO-8601 with offset
    iso_offset = "2026-09-16T19:00:00+07:00"
    assert _parse_timestamp_setting(iso_offset) == expected_ms

    # Unix epoch ms
    assert _parse_timestamp_setting("1789560000000") == 1789560000000

    # Unix epoch seconds
    assert _parse_timestamp_setting("1789560000") == 1789560000000

    # Relative tokens: 'now' and 'deploy_time'
    before = int(time.time() * 1000)
    now_parsed = _parse_timestamp_setting("now")
    deploy_parsed = _parse_timestamp_setting("deploy_time")
    after = int(time.time() * 1000)
    assert before <= now_parsed <= after
    assert before <= deploy_parsed <= after

    # Empty and invalid
    assert _parse_timestamp_setting("") is None
    assert _parse_timestamp_setting("   ") is None
    assert _parse_timestamp_setting("invalid-timestamp") is None


def test_settings_worker_start_time_ms(monkeypatch):
    test_settings = Settings()

    # Default is None
    object.__setattr__(test_settings, "worker_start_time", "")
    object.__setattr__(test_settings, "worker_ignore_past_data", False)
    assert test_settings.worker_start_time_ms is None

    # Setting worker_start_time
    object.__setattr__(test_settings, "worker_start_time", "2026-09-16T00:00:00Z")
    assert test_settings.worker_start_time_ms is not None

    # Setting worker_ignore_past_data
    object.__setattr__(test_settings, "worker_start_time", "")
    object.__setattr__(test_settings, "worker_ignore_past_data", True)
    now_ms = int(time.time() * 1000)
    assert abs(test_settings.worker_start_time_ms - now_ms) < 5000


def test_aggregation_skips_past_data_when_cutoff_configured(tmp_path, monkeypatch):
    db_path = tmp_path / "worker_cutoff_test.db"
    StorageRepository(db_path).migrate()

    # Insert 5 historical traces at ts = 1_700_000_000 sec
    trace_repo = TraceRepository(db_path)
    historical_traces = [
        normalize_otel_record({
            "ts": 1_700_000_000 + i,
            "service": "test-order-service",
            "path": "/order/checkout",
            "trace_id": f"hist{i:028x}",
            "span_id": f"span{i:012x}",
            "status": 200,
            "duration_ms": 50.0,
        })
        for i in range(5)
    ]
    trace_repo.insert_traces(historical_traces)

    # Configure worker to ignore data before ts = 1_700_050_000_000 ms
    cutoff_ms = 1_700_050_000_000
    orig_time = settings.worker_start_time
    orig_ignore = settings.worker_ignore_past_data
    object.__setattr__(settings, "worker_start_time", str(cutoff_ms))
    object.__setattr__(settings, "worker_ignore_past_data", False)
    try:
        # Run aggregation when no new traces exist yet
        result = aggregate_traces(db_path=db_path)
        assert result["1m_buckets"] == 0
        assert result["5m_buckets"] == 0

        # Verify that checkpoints table recorded last_ts = cutoff_ms
        with get_connection(db_path) as db:
            row = db.execute("SELECT cursor_json FROM checkpoints FINAL WHERE source='aggregation_cursor'").fetchone()
            assert row is not None
            cp = json.loads(row[0])
            assert cp["mode"] == "incremental"
            assert cp["last_ts"] == cutoff_ms
            assert cp["ingest_order"] > 0

        # Insert 3 new traces at ts = 1_700_100_000 sec (after cutoff)
        new_traces = [
            normalize_otel_record({
                "ts": 1_700_100_000 + i,
                "service": "test-order-service",
                "path": "/order/checkout",
                "trace_id": f"new{i:029x}",
                "span_id": f"nspan{i:011x}",
                "status": 200,
                "duration_ms": 60.0,
            })
            for i in range(3)
        ]
        trace_repo.insert_traces(new_traces)

        # Run aggregation again: only the 3 new traces should be aggregated
        result = aggregate_traces(db_path=db_path)
        assert result["1m_buckets"] > 0

        # Verify bucket request_count reflects only the 3 new traces, not 8
        agg_repo = AggregateRepository(db_path)
        series = agg_repo.query_series(1_700_000_000, 1_700_200_000, bucket_size=60, service="test-order-service")
        assert len(series) == 1
        assert series[0]["requests"] == 3

        with get_connection(db_path) as db:
            total_requests = db.execute("SELECT sum(request_count) FROM metric_buckets WHERE target_service='test-order-service' AND bucket_size=60").fetchone()[0]
            assert int(total_requests) == 3
    finally:
        object.__setattr__(settings, "worker_start_time", orig_time)
        object.__setattr__(settings, "worker_ignore_past_data", orig_ignore)


def test_elasticsearch_reader_initial_filter(monkeypatch):
    cutoff_ms = 1789560000000
    monkeypatch.setenv("OTEL_ES_URL", "http://mock-es:9200")
    monkeypatch.setenv("OTEL_ES_INDEX", "apm-*")
    orig_time = settings.worker_start_time
    object.__setattr__(settings, "worker_start_time", str(cutoff_ms))

    captured_requests = []

    class DummyResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"hits": {"hits": []}}

    import httpx
    def mock_post(client_self, url, **kwargs):
        captured_requests.append((url, kwargs.get("json")))
        return DummyResponse()

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    try:
        reader = ElasticsearchReader()
        pages = list(reader.pages())
        assert len(captured_requests) == 1
        url, body = captured_requests[0]
        assert url == "/apm-*/_search"
        filter_clauses = body["query"]["bool"]["filter"]
        range_filter = next(f for f in filter_clauses if "range" in f)
        assert range_filter["range"]["@timestamp"]["gte"] == cutoff_ms
    finally:
        object.__setattr__(settings, "worker_start_time", orig_time)


def test_principal_intelligence_skips_past_data_when_cutoff_configured(tmp_path):
    from backend.app.services.principal_relationships import process_principal_intelligence

    db_path = tmp_path / "principal_cutoff_test.db"
    StorageRepository(db_path).migrate()

    trace_repo = TraceRepository(db_path)
    historical_traces = [
        normalize_otel_record({
            "ts": 1_700_000_000 + i,
            "service": "test-order-service",
            "path": "/order/checkout",
            "trace_id": f"histp{i:027x}",
            "span_id": f"spanp{i:011x}",
            "status": 200,
            "user": "historical_user",
            "duration_ms": 50.0,
        })
        for i in range(5)
    ]
    trace_repo.insert_traces(historical_traces)

    cutoff_ms = 1_700_050_000_000
    orig_time = settings.worker_start_time
    orig_ignore = settings.worker_ignore_past_data
    object.__setattr__(settings, "worker_start_time", str(cutoff_ms))
    object.__setattr__(settings, "worker_ignore_past_data", False)

    try:
        # Run principal intelligence: should initialize cursor at cutoff and skip past data
        res1 = process_principal_intelligence(db_path=db_path)
        assert res1["processed"] == 0

        with get_connection(db_path) as db:
            row = db.execute("SELECT cursor_json FROM checkpoints FINAL WHERE source='principal_intelligence'").fetchone()
            assert row is not None
            cp = json.loads(row[0])
            assert cp["bootstrap_cutoff_ms"] == cutoff_ms
            assert cp["ingest_order"] > 0

        # Now insert 3 traces after cutoff
        new_traces = [
            normalize_otel_record({
                "ts": 1_700_100_000 + i,
                "service": "test-order-service",
                "path": "/order/checkout",
                "trace_id": f"newp{i:028x}",
                "span_id": f"nspanp{i:010x}",
                "status": 200,
                "user": "active_user",
                "duration_ms": 50.0,
            })
            for i in range(3)
        ]
        trace_repo.insert_traces(new_traces)

        res2 = process_principal_intelligence(db_path=db_path)
        assert res2["processed"] == 3
    finally:
        object.__setattr__(settings, "worker_start_time", orig_time)
        object.__setattr__(settings, "worker_ignore_past_data", orig_ignore)



