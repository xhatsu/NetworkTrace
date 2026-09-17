import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from backend.analytics import run_jobs
from backend.fixtures import synthetic_documents
from backend.histogram import Histogram
from backend.ingest import import_documents
from backend.repository import StorageRepository
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.aggregation import aggregate_traces
from backend.app.services import aggregation as aggregation_service
from backend.app.services import anomaly_detection as anomaly_detection_service
from backend.app.services.baseline import rebuild_baselines
from backend.app.repositories.baseline_repository import BaselineRepository
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.models.aggregate import MetricBucket
from backend.app.services.normalization import normalize_otel_record
from backend.app.repositories.db_context import get_connection
from backend.app.models.anomaly import AnomalyEvent
from backend.app.repositories.anomaly_repository import AnomalyRepository
from backend import worker as worker_service


def test_histograms_merge_before_percentile():
    a=Histogram.empty();b=Histogram.empty()
    for value in [10_000,20_000,30_000]: a.add(value)
    for value in [100_000,200_000]: b.add(value)
    a.merge(b)
    assert 100 <= a.percentile(.8) <= 230


def _old_python_percentile(values, quantile):
    """Reference copied from the pre-SQL aggregation implementation."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[min(index, len(ordered) - 1)]


def test_sql_exact_percentiles_match_old_python_nearest_rank(tmp_path):
    db_path = tmp_path / "sql-percentile-parity.db"
    StorageRepository(db_path).migrate()
    durations = [float(value) for value in range(1, 101)]
    traces = []
    for index, duration_ms in enumerate(durations):
        trace = normalize_otel_record({
            "ts": 1_767_225_660 + (index % 50),
            "service": "percentile-parity-service",
            "path": "/parity",
            "trace_id": f"{index + 1:032x}",
            "span_id": f"{index + 1:016x}",
            "status": 200,
            "duration_ms": duration_ms,
        })
        assert trace is not None
        traces.append(trace)
    TraceRepository(str(db_path)).insert_traces(traces)

    aggregate_traces(db_path=str(db_path))

    expected = tuple(round(_old_python_percentile(durations, q), 2) for q in (0.5, 0.95, 0.99))
    with get_connection(db_path) as db:
        rows = db.execute(
            "SELECT bucket_size,latency_p50,latency_p95,latency_p99 "
            "FROM metric_buckets FINAL WHERE target_service='percentile-parity-service' "
            "ORDER BY bucket_size"
        ).fetchall()
    assert len(rows) == 2
    assert all(tuple(row[1:]) == expected for row in rows)
    assert "quantilesExact(" in aggregation_service._BUCKET_AGGREGATION_SQL
    assert "GROUP BY" in aggregation_service._BUCKET_AGGREGATION_SQL


def test_shadow_states_merge_counts_and_percentiles_without_averaging(tmp_path):
    db_path = tmp_path / "shadow-state-parity.db"
    StorageRepository(db_path).migrate()
    durations = [float(value) for value in range(1, 101)]
    traces = []
    for index, duration_ms in enumerate(durations):
        trace = normalize_otel_record({
            "ts": 1_767_225_660 + (index % 100),
            "service": "shadow-parity-service",
            "path": "/shadow",
            "trace_id": f"{index + 1000:032x}",
            "span_id": f"{index + 1000:016x}",
            "status": 500 if index % 10 == 0 else 200,
            "duration_ms": duration_ms,
        })
        assert trace is not None
        traces.append(trace)
    TraceRepository(str(db_path)).insert_traces(traces)
    aggregate_traces(db_path=str(db_path))

    with get_connection(db_path) as db:
        row = db.execute("""
            SELECT sumMerge(request_count_state),countIfMerge(error_count_state),
                   sumMerge(latency_sum_state),
                   quantilesTDigestMerge(0.5,0.95,0.99)(latency_quantiles_state)
            FROM metric_buckets_agg
            WHERE bucket_size=300 AND target_service='shadow-parity-service'
        """).fetchone()
    assert tuple(row[:3]) == (100, 10, 5050.0)
    p50, p95, p99 = row[3]
    assert p50 < p95 < p99
    assert p95 > 90


def test_shadow_backfill_has_independent_checkpoint_and_is_replay_safe(tmp_path):
    db_path = tmp_path / "shadow-backfill.db"
    StorageRepository(db_path).migrate()
    TraceRepository(str(db_path)).insert_traces([
        _trace_at("2026-01-01T00:01:00Z", "shadow-backfill")
    ])
    first = aggregation_service.backfill_shadow_aggregates(str(db_path))
    second = aggregation_service.backfill_shadow_aggregates(str(db_path))
    assert first == {"shadow_slices": 1}
    assert second == {"shadow_slices": 0}
    with get_connection(db_path) as db:
        sources = {row[0] for row in db.execute(
            "SELECT source FROM checkpoints FINAL"
        ).fetchall()}
        count = db.execute(
            "SELECT sumMerge(request_count_state) FROM metric_buckets_agg WHERE bucket_size=300"
        ).fetchone()[0]
    assert sources == {"aggregation_shadow_cursor"}
    assert count == 1


def test_anomaly_retry_uses_same_deterministic_id_and_logical_row(tmp_path):
    db_path = tmp_path / "deterministic-anomaly.db"
    StorageRepository(db_path).migrate()
    repo = AnomalyRepository(str(db_path))
    first = AnomalyEvent(
        detected_at=1000, anomaly_type="latency", severity="high", score=70,
        caller_service="caller", target_service="target", principal_name="user",
        operation="GET /stable", first_seen=10_000, last_seen=20_000,
    )
    retry = first.model_copy(update={"detected_at": 2000, "score": 80})
    repo.save_anomalies([first])
    repo.save_anomalies([retry])
    assert first.id == retry.id
    with get_connection(db_path) as db:
        logical = db.execute(
            "SELECT count(),uniqExact(id),max(score) FROM anomaly_events FINAL"
        ).fetchone()
    assert tuple(logical) == (1, 1, 80)
    listed = repo.list_anomalies()
    assert len(listed) == 1
    assert listed[0]["id"] == first.id


def test_contiguous_anomalies_are_coalesced_into_single_incident(tmp_path):
    db_path = tmp_path / "coalesce-anomaly.db"
    StorageRepository(db_path).migrate()
    repo = AnomalyRepository(str(db_path))

    first = AnomalyEvent(
        detected_at=100_000, anomaly_type="unusual_time", severity="medium", score=50,
        caller_service="checkout-service", target_service="payment-service", principal_name="alice",
        operation="POST /charge", first_seen=100_000, last_seen=400_000,
        current_value=12.0, baseline_value=0.1, delta_percentage=100.0,
    )
    repo.save_anomalies([first])

    # 5 minutes later, contiguous anomaly arrives for the exact same signature
    second = AnomalyEvent(
        detected_at=400_000, anomaly_type="unusual_time", severity="medium", score=50,
        caller_service="checkout-service", target_service="payment-service", principal_name="alice",
        operation="POST /charge", first_seen=400_000, last_seen=700_000,
        current_value=15.0, baseline_value=0.1, delta_percentage=100.0,
    )
    repo.save_anomalies([second])

    listed = repo.list_anomalies()
    assert len(listed) == 1, f"Expected 1 coalesced incident episode, got {len(listed)}"
    rec = listed[0]
    assert rec["id"] == first.id
    assert rec["first_seen"] == 100_000
    assert rec["last_seen"] == 700_000
    assert rec["metadata"]["occurrences"] == 2
    assert rec["metadata"]["duration_mins"] == 10.0


def test_worker_stage_checkpoints_cadence_and_revision_budget(tmp_path):
    db_path = tmp_path / "worker-stage-checkpoints.db"
    StorageRepository(db_path).migrate()
    TraceRepository(str(db_path)).insert_traces([
        _trace_at("2026-01-01T00:01:00Z", "worker-checkpoint")
    ])
    aggregate_traces(db_path=str(db_path))

    assert worker_service._run_changed_baselines(str(db_path)) > 0
    assert worker_service._run_changed_baselines(str(db_path)) == 0
    assert worker_service._run_revised_anomalies(str(db_path)) == []
    with get_connection(db_path) as db:
        sources = {row[0] for row in db.execute(
            "SELECT source FROM checkpoints FINAL"
        ).fetchall()}
        remaining = db.execute(
            "SELECT count() FROM dirty_buckets FINAL WHERE reason='aggregation-revised'"
        ).fetchone()[0]
    assert {"aggregation_cursor", "worker_baselines", "worker_anomalies"} <= sources
    assert remaining == 0


def test_service_baseline_uses_one_aggregate_sample_per_window(tmp_path):
    db_path = tmp_path / "service-grain.db"
    base = 1_700_000_000
    buckets = []
    for window in (base, base + 7 * 86400):
        for caller in ("caller-a", "caller-b"):
            buckets.append(MetricBucket(
                bucket_start=window, bucket_size=300, caller_service=caller,
                target_service="grain-service", principal_name="p", operation=caller,
                request_count=30, error_count=3, latency_sum=300, latency_avg=10,
                latency_min=10, latency_max=10, latency_p50=10, latency_p95=20, latency_p99=20,
            ))
    AggregateRepository(db_path).save_buckets(buckets)
    rebuild_baselines(db_path)
    instant = datetime.fromtimestamp(base, tz=timezone.utc)
    baseline = BaselineRepository(db_path).get_baseline(
        "service", "grain-service", instant.hour, instant.weekday(),
    )
    assert baseline is not None
    assert baseline["sample_count"] == 2
    assert baseline["rps_median"] == 0.2


def test_worker_builds_real_rollups_edges_and_explanation(tmp_path):
    r=StorageRepository(tmp_path/"analytics.db");r.migrate();anchor=datetime(2026,1,8,12,0,tzinfo=timezone.utc)
    result=import_documents(r,synthetic_documents(24_000,12,anchor),"fixture")
    assert result.inserted>24_000
    jobs=run_jobs(r)
    assert jobs["rollups"]>0 and jobs["edges"]>0 and jobs["anomalies"]>0
    summary=r.dashboard_summary(int((anchor-timedelta(hours=3)).timestamp()*1000),int((anchor+timedelta(minutes=1)).timestamp()*1000),{})
    assert summary["total_requests"]==24_420
    assert summary["tps_equals_rps"] is True
    findings=r.anomalies(0,int(anchor.timestamp()*1000)+120_000)
    assert any("based on" in a["explanation"] and a["current_samples"]>=30 for a in findings)
    topology=r.topology(0,int(anchor.timestamp()*1000)+120_000)
    assert {edge["evidence"] for edge in topology["edges"]}=={"confirmed","inferred"}


def test_five_minute_percentiles_use_raw_samples(tmp_path):
    db_path = tmp_path / "exact-percentiles.db"
    StorageRepository(db_path).migrate()
    docs = []
    durations = [1_000_000] + [1_000] * 99
    for index, duration_us in enumerate(durations):
        minute = "00" if index == 0 else "01"
        docs.append({"_source": {
            "@timestamp": f"2026-01-01T00:{minute}:00Z",
            "trace": {"id": f"trace-{index}"},
            "transaction": {"id": f"span-{index}", "name": "GET /exact", "duration": {"us": duration_us}},
            "service": {"name": "exact-service"},
            "span": {"kind": "server"},
        }})
    traces = [trace for doc in docs if (trace := normalize_otel_record(doc))]
    TraceRepository(str(db_path)).insert_traces(traces)
    aggregate_traces(db_path=str(db_path))
    with get_connection(db_path) as db:
        row = db.execute(
            "SELECT latency_p50,latency_p95,latency_p99 FROM metric_buckets "
            "WHERE bucket_size=300 AND target_service='exact-service'"
        ).fetchone()
    assert tuple(row) == (1.0, 1.0, 1.0)


def _trace_at(timestamp: str, suffix: str):
    return normalize_otel_record({"_source": {
        "@timestamp": timestamp,
        "trace": {"id": f"trace-{suffix}"},
        "transaction": {
            "id": f"span-{suffix}",
            "name": "GET /incremental",
            "duration": {"us": 10_000},
        },
        "service": {"name": "incremental-service"},
        "span": {"kind": "server"},
    }})


def test_aggregation_cursor_recomputes_late_arriving_complete_bucket(tmp_path):
    db_path = tmp_path / "incremental-aggregation.db"
    StorageRepository(db_path).migrate()
    repository = TraceRepository(str(db_path))
    repository.insert_traces([_trace_at("2026-01-01T00:01:00Z", "first")])

    first = aggregate_traces(db_path=str(db_path))
    assert first["1m_buckets"] == 1
    with get_connection(db_path) as db:
        checkpoint = json.loads(db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source='aggregation_cursor'"
        ).fetchone()[0])
    assert checkpoint["mode"] == "incremental"
    assert checkpoint["ingest_order"] > 0
    assert checkpoint["row_uid"] != aggregation_service.ZERO_UUID

    repository.insert_traces([_trace_at("2026-01-01T00:01:30Z", "late")])
    second = aggregate_traces(db_path=str(db_path))
    assert second["1m_buckets"] == 1
    with get_connection(db_path) as db:
        row = db.execute(
            "SELECT request_count FROM metric_buckets FINAL "
            "WHERE bucket_size=60 AND target_service='incremental-service'"
        ).fetchone()
        shadow_count = db.execute(
            "SELECT sumMerge(request_count_state) FROM metric_buckets_agg "
            "WHERE bucket_size=60 AND target_service='incremental-service'"
        ).fetchone()[0]
    assert row[0] == 2
    assert shadow_count == 2
    assert aggregation_service.settings.aggregation_cutover is False
    assert aggregate_traces(db_path=str(db_path)) == {
        "1m_buckets": 0, "5m_buckets": 0, "service_edges": 0, "principal_edges": 0,
    }


def test_late_row_advances_ingestion_cursor_and_triggers_revision_evaluation(tmp_path, monkeypatch):
    db_path = tmp_path / "late-revision-trigger.db"
    StorageRepository(db_path).migrate()
    repository = TraceRepository(str(db_path))
    repository.insert_traces([_trace_at("2026-01-01T00:06:00Z", "on-time")])
    aggregate_traces(db_path=str(db_path))
    with get_connection(db_path) as db:
        first_cursor = json.loads(db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source='aggregation_cursor'"
        ).fetchone()[0])
        db.execute("DELETE FROM dirty_buckets WHERE reason='aggregation-revised'")

    repository.insert_traces([_trace_at("2026-01-01T00:01:00Z", "late-visible")])
    aggregate_traces(db_path=str(db_path))
    with get_connection(db_path) as db:
        second_cursor = json.loads(db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source='aggregation_cursor'"
        ).fetchone()[0])
        revised = db.execute(
            "SELECT bucket_ms FROM dirty_buckets FINAL WHERE reason='aggregation-revised' ORDER BY bucket_ms"
        ).fetchall()
    assert (second_cursor["ingest_order"], second_cursor["row_uid"]) > (
        first_cursor["ingest_order"], first_cursor["row_uid"]
    )
    assert second_cursor["last_ts"] >= first_cursor["last_ts"]
    assert [row[0] for row in revised] == [1_767_225_600_000]

    evaluated = []

    def capture(start_sec, end_sec, selected_db_path):
        evaluated.append((start_sec, end_sec, selected_db_path))
        return []

    monkeypatch.setattr(anomaly_detection_service, "detect_anomalies", capture)
    assert anomaly_detection_service.detect_revised_anomalies(str(db_path)) == []
    assert evaluated == [(1_767_225_600, 1_767_225_900, str(db_path))]
    with get_connection(db_path) as db:
        assert db.execute(
            "SELECT count() FROM dirty_buckets FINAL WHERE reason='aggregation-revised'"
        ).fetchone()[0] == 0


def test_bootstrap_checkpoint_advances_only_after_successful_slice(tmp_path, monkeypatch):
    db_path = tmp_path / "aggregation-resume.db"
    StorageRepository(db_path).migrate()
    repository = TraceRepository(str(db_path))
    repository.insert_traces([
        _trace_at("2026-01-01T00:01:00Z", "slice-one"),
        _trace_at("2026-01-01T00:06:00Z", "slice-two"),
    ])
    monkeypatch.setattr(aggregation_service, "AGGREGATION_SLICE_MS", 300_000)
    original = aggregation_service._aggregate_slice
    calls = []

    def fail_second_slice(start_ms, end_ms, selected_db_path):
        calls.append((start_ms, end_ms))
        if len(calls) == 2:
            raise RuntimeError("injected slice failure")
        return original(start_ms, end_ms, selected_db_path)

    monkeypatch.setattr(aggregation_service, "_aggregate_slice", fail_second_slice)
    with pytest.raises(RuntimeError, match="injected slice failure"):
        aggregate_traces(db_path=str(db_path))
    with get_connection(db_path) as db:
        checkpoint = json.loads(db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source='aggregation_cursor'"
        ).fetchone()[0])
    assert checkpoint["mode"] == "bootstrap"
    assert checkpoint["next_slice_start_ms"] == calls[0][1]

    monkeypatch.setattr(aggregation_service, "_aggregate_slice", original)
    resumed = aggregate_traces(db_path=str(db_path))
    assert resumed["1m_buckets"] == 1
    with get_connection(db_path) as db:
        counts = db.execute(
            "SELECT bucket_start, request_count FROM metric_buckets FINAL "
            "WHERE bucket_size=60 AND target_service='incremental-service' ORDER BY bucket_start"
        ).fetchall()
    assert [row[1] for row in counts] == [1, 1]
