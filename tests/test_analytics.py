from datetime import datetime, timedelta, timezone

from backend.analytics import run_jobs
from backend.fixtures import synthetic_documents
from backend.histogram import Histogram
from backend.ingest import import_documents
from backend.repository import SQLiteRepository
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.normalization import normalize_otel_record
from backend.app.repositories.db_context import get_connection


def test_histograms_merge_before_percentile():
    a=Histogram.empty();b=Histogram.empty()
    for value in [10_000,20_000,30_000]: a.add(value)
    for value in [100_000,200_000]: b.add(value)
    a.merge(b)
    assert 100 <= a.percentile(.8) <= 230


def test_worker_builds_real_rollups_edges_and_explanation(tmp_path):
    r=SQLiteRepository(tmp_path/"analytics.db");r.migrate();anchor=datetime(2026,1,8,12,0,tzinfo=timezone.utc)
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
    SQLiteRepository(db_path).migrate()
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
