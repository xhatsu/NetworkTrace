"""Run periodic derivations outside request-serving processes.

ClickHouse keeps ingestion durable and horizontally scalable; this worker turns
raw events into rollups, baselines, and behavioral evidence on a predictable cadence.
"""
from __future__ import annotations

import argparse
import json
import logging
import resource
import time
import traceback

from .repository import StorageRepository
from .config import settings
from .app.services.aggregation import aggregate_traces
from .app.services.anomaly_detection import detect_revised_anomalies
from .app.services.baseline import rebuild_baselines
from .app.services.principal_relationships import process_principal_intelligence
from .app.repositories.db_context import db_transaction
from .app.repositories.db_context import get_connection


def _memory_snapshot() -> dict[str, int | None]:
    snapshot: dict[str, int | None] = {
        "python_max_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "clickhouse_memory_tracking_bytes": None,
    }
    try:
        with get_connection() as db:
            row = db.execute(
                "SELECT value FROM system.metrics WHERE metric='MemoryTracking'"
            ).fetchone()
        if row is not None:
            snapshot["clickhouse_memory_tracking_bytes"] = int(row[0])
    except Exception:
        # Telemetry must never turn a successful analytics stage into a failed one.
        pass
    return snapshot


def _run_stage(name: str, operation):
    started = time.monotonic()
    memory_before = _memory_snapshot()
    print(json.dumps({
        "event": "worker_stage_start", "stage": name, "memory_before": memory_before,
    }), flush=True)
    result = operation()
    memory_after = _memory_snapshot()
    print(json.dumps({
        "event": "worker_stage_complete",
        "stage": name,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "memory_before": memory_before,
        "memory_after": memory_after,
        "python_max_rss_delta_kb": (
            memory_after["python_max_rss_kb"] - memory_before["python_max_rss_kb"]
        ),
        "clickhouse_memory_tracking_delta_bytes": (
            memory_after["clickhouse_memory_tracking_bytes"]
            - memory_before["clickhouse_memory_tracking_bytes"]
            if memory_after["clickhouse_memory_tracking_bytes"] is not None
            and memory_before["clickhouse_memory_tracking_bytes"] is not None
            else None
        ),
        "budget_seconds": settings.analytics_stage_budget_seconds,
        "budget_exceeded": (
            time.monotonic() - started > settings.analytics_stage_budget_seconds
        ),
    }), flush=True)
    return result


def _checkpoint(source: str, db_path=None) -> dict:
    with get_connection(db_path) as db:
        row = db.execute(
            "SELECT cursor_json FROM checkpoints FINAL WHERE source=?", (source,)
        ).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _save_stage_checkpoint(source: str, value: dict, db_path=None) -> None:
    with db_transaction(db_path) as db:
        db.execute(
            "INSERT INTO checkpoints(source,cursor_json,updated_at_ms) VALUES(?,?,?)",
            (source, json.dumps(value, separators=(",", ":")), int(time.time() * 1000)),
        )


def _run_changed_baselines(db_path=None) -> int:
    """On a slower cadence, rebuild only series touched since this stage's cursor."""
    source = "worker_baselines"
    state = _checkpoint(source, db_path)
    now_ms = int(time.time() * 1000)
    if now_ms - int(state.get("last_run_ms", 0)) < settings.baseline_cadence_seconds * 1000:
        return 0
    cursor_version = int(state.get("bucket_version", 0))
    cursor_target = str(state.get("target_service", ""))
    with get_connection(db_path) as db:
        rows = db.execute(
            "SELECT target_service,max(created_at) AS bucket_version "
            "FROM metric_buckets WHERE bucket_size=300 GROUP BY target_service "
            "HAVING (bucket_version,target_service)>(?,?) "
            "ORDER BY bucket_version,target_service LIMIT ?",
            (cursor_version, cursor_target, settings.baseline_series_budget),
        ).fetchall()
    targets = [str(row[0]) for row in rows]
    count = rebuild_baselines(db_path=db_path, target_services=targets)
    if rows:
        state["bucket_version"] = int(rows[-1][1])
        state["target_service"] = str(rows[-1][0])
    state.update({"last_run_ms": now_ms, "processed_series": len(targets)})
    _save_stage_checkpoint(source, state, db_path)
    return count


def _run_revised_anomalies(db_path=None):
    anomalies = detect_revised_anomalies(
        db_path=db_path, max_windows=settings.anomaly_window_budget
    )
    _save_stage_checkpoint("worker_anomalies", {
        "last_run_ms": int(time.time() * 1000),
        "last_result_count": len(anomalies),
        "window_budget": settings.anomaly_window_budget,
    }, db_path)
    return anomalies


def _run_elasticsearch_sync(db_path=None) -> dict:
    from .elasticsearch import ElasticsearchReader
    reader = ElasticsearchReader()
    if not reader.url:
        return {"status": "skipped", "message": "OTEL_ES_URL not configured"}
    # One Elasticsearch stage owns the window and checkpoint. In agent-only
    # deployments no application document is read into ClickHouse.
    sync_result = (reader.sync(db_path=db_path) if not settings.clickhouse_only_agent_traces
                   else {"status": "aggregate_only", "read": 0, "inserted": 0})
    metrics = (_run_elasticsearch_metrics(db_path) if settings.clickhouse_only_agent_traces
               else {"status": "clickhouse_trace_aggregation"})
    bandwidth = _run_elasticsearch_bandwidth(db_path)
    retention = reader.prune_expired_documents()
    state = _checkpoint("worker_elasticsearch_sync", db_path)
    _save_stage_checkpoint("worker_elasticsearch_sync", {**state,
        "last_run_ms": int(time.time() * 1000),
        "read": sync_result.get("read", 0),
        "inserted": sync_result.get("inserted", 0),
        "retention": retention,
    }, db_path)
    return {**sync_result, "metrics": metrics, "bandwidth": bandwidth, "retention": retention}


def _run_elasticsearch_metrics(db_path=None) -> dict:
    """Backfill and refresh transaction buckets without copying application traces."""
    from .app.repositories.elasticsearch_metric_repository import ElasticsearchMetricRepository

    source = "worker_elasticsearch_sync"
    stage_state = _checkpoint(source, db_path)
    state = stage_state.get("metrics") or {}
    bucket_ms = 300_000
    complete_end = (int(time.time() * 1000) // bucket_ms) * bucket_ms
    historical_start = max(complete_end - 7 * 86400 * 1000, int(settings.worker_start_time_ms or 0))
    repository = ElasticsearchMetricRepository(db_path)

    # Keep fresh minutes visible while the historical cursor moves backward.
    live_pending = state.get("live_pending") or {}
    live_start = int(live_pending.get("start_ms") or max(historical_start, complete_end - 2 * bucket_ms))
    live_end = int(live_pending.get("end_ms") or complete_end)
    for grain in (300, 60):
        if live_pending and int(live_pending.get("grain", 300)) != grain:
            continue
        result = repository.materialize_window(
            live_start, live_end, grain,
            live_pending.get("after_key") if live_pending else None,
        )
        if not result["complete"]:
            state["live_pending"] = {
                "start_ms": live_start, "end_ms": live_end,
                "grain": grain, "after_key": result["after_key"],
            }
            _save_stage_checkpoint(source, {**stage_state, "metrics": state}, db_path)
            return {**result, "status": "continuing_recent_window", "grain": grain}
        live_pending = {}
        state.pop("live_pending", None)

    if state.get("mode") == "live":
        state["last_run_ms"] = int(time.time() * 1000)
        _save_stage_checkpoint(source, {**stage_state, "metrics": state}, db_path)
        return {"status": "live", "complete": True}

    end_ms = min(int(state.get("cursor_ms") or complete_end), complete_end)
    start_ms = max(historical_start, end_ms - 6 * 3600 * 1000)
    if start_ms >= end_ms:
        state = {"mode": "live", "last_run_ms": int(time.time() * 1000)}
        _save_stage_checkpoint(source, {**stage_state, "metrics": state}, db_path)
        return {"status": "live", "complete": True}
    grain = int(state.get("grain") or 300)
    result = repository.materialize_window(start_ms, end_ms, grain, state.get("after_key"))
    next_state = {"mode": "backfill", "cursor_ms": end_ms, "grain": grain}
    if result["complete"]:
        if grain == 300:
            next_state["grain"] = 60
        else:
            next_state["grain"] = 300
            next_state["cursor_ms"] = start_ms
            if start_ms <= historical_start:
                next_state = {"mode": "live"}
    else:
        next_state["after_key"] = result["after_key"]
    next_state["last_run_ms"] = int(time.time() * 1000)
    _save_stage_checkpoint(source, {**stage_state, "metrics": next_state}, db_path)
    return {**result, "status": "complete" if result["complete"] else "continuing",
            "grain": grain, "window_start_ms": start_ms, "window_end_ms": end_ms}


def _run_elasticsearch_bandwidth(db_path=None) -> dict:
    """Advance one bounded ELK bandwidth window, newest history first."""
    from .app.repositories.elasticsearch_bandwidth_repository import (
        BUCKET_MS, ElasticsearchBandwidthRepository,
    )

    source = "worker_elasticsearch_sync"
    stage_state = _checkpoint(source, db_path)
    state = stage_state.get("bandwidth") or {}
    complete_end = (int(time.time() * 1000) // BUCKET_MS) * BUCKET_MS
    historical_start = max(
        complete_end - 30 * 86400 * 1000,
        int(settings.worker_start_time_ms or 0),
    )
    pending = state.get("pending") or {}
    mode = str(state.get("mode") or "backfill")
    repository = ElasticsearchBandwidthRepository()
    # Backfill can take many cycles; keep the most recent complete buckets
    # fresh in the same stage while its historical cursor moves backward.
    if mode == "backfill":
        live_pending = state.get("live_pending") or {}
        live_start = int(live_pending.get("start_ms") or max(historical_start, complete_end - 2 * BUCKET_MS))
        live_end = int(live_pending.get("end_ms") or complete_end)
        live_result = repository.materialize_window(live_start, live_end, live_pending.get("after_key"))
        if not live_result["complete"]:
            _save_stage_checkpoint(source, {**stage_state, "bandwidth": {**state,
                "live_pending": {"start_ms": live_start, "end_ms": live_end,
                                 "after_key": live_result["after_key"]}}}, db_path)
            return {**live_result, "status": "continuing_recent_window",
                    "window_start_ms": live_start, "window_end_ms": live_end}
        state = {key: value for key, value in state.items() if key != "live_pending"}
    if pending:
        start_ms = int(pending["start_ms"])
        end_ms = int(pending["end_ms"])
        after_key = pending.get("after_key")
    elif mode == "backfill":
        end_ms = min(int(state.get("cursor_ms") or complete_end), complete_end)
        start_ms = max(historical_start, end_ms - 6 * 3600 * 1000)
        after_key = None
    else:
        cursor_ms = int(state.get("cursor_ms") or complete_end)
        start_ms = max(historical_start, cursor_ms - 2 * BUCKET_MS)
        end_ms = min(complete_end, start_ms + 6 * 3600 * 1000)
        after_key = None

    if start_ms >= end_ms:
        if mode == "backfill":
            _save_stage_checkpoint(source, {**stage_state,
                "bandwidth": {"mode": "live", "cursor_ms": complete_end - 2 * BUCKET_MS}}, db_path)
        return {"status": "up_to_date", "documents": 0, "pages": 0}

    result = repository.materialize_window(start_ms, end_ms, after_key)
    next_state: dict = {"mode": mode}
    if result["complete"]:
        if mode == "backfill":
            next_state["cursor_ms"] = start_ms
            if start_ms <= historical_start:
                next_state = {"mode": "live", "cursor_ms": complete_end - 2 * BUCKET_MS}
        else:
            next_state["cursor_ms"] = end_ms
    else:
        next_state["cursor_ms"] = int(state.get("cursor_ms") or complete_end)
        next_state["pending"] = {
            "start_ms": start_ms, "end_ms": end_ms, "after_key": result["after_key"],
        }
    next_state["last_run_ms"] = int(time.time() * 1000)
    _save_stage_checkpoint(source, {**stage_state, "bandwidth": next_state}, db_path)
    return {**result, "status": "complete" if result["complete"] else "continuing",
            "window_start_ms": start_ms, "window_end_ms": end_ms}


def run_jobs(db_path=None) -> dict[str, Any]:
    started = int(time.time() * 1000)
    started_mono = time.monotonic()
    with db_transaction(db_path) as db:
        db.execute("DELETE FROM jobs WHERE name=?", ("behavioral-observability",))
        db.execute("INSERT INTO jobs(name,status,started_at_ms,detail,processed_count) VALUES(?,?,?,?,0)",
                   ("behavioral-observability", "running", started, ""))
    try:
        from .elasticsearch import ElasticsearchReader
        reader = ElasticsearchReader()
        es_sync = None
        if reader.url:
            try:
                es_sync = _run_stage("process_elasticsearch", lambda: _run_elasticsearch_sync(db_path))
            except Exception as exc:
                logging.warning("ELK processing failed: %s", str(exc)[:300])
                es_sync = {"status": "error", "message": str(exc)[:300]}
        aggregates = _run_stage("aggregate_traces", lambda: aggregate_traces(db_path=db_path))
        baselines = _run_stage("rebuild_baselines", lambda: _run_changed_baselines(db_path))
        anomalies = _run_stage("detect_anomalies", lambda: _run_revised_anomalies(db_path))
        principals = _run_stage("process_principal_intelligence", lambda: process_principal_intelligence(db_path=db_path))

        from backend.app.services.prometheus_metrics import update_worker_prometheus_metrics
        prom_snap = _run_stage(
            "update_prometheus_metrics",
            lambda: update_worker_prometheus_metrics(db_path=db_path, duration_sec=round(time.monotonic() - started_mono, 3)),
        )

        result = {**aggregates, "baselines": baselines, "anomalies": len(anomalies),
                  "principal_records": principals["processed"], "principal_changes": principals["changes"],
                  "prometheus_metrics_updated": True}
        if es_sync is not None:
            result["elasticsearch_read"] = es_sync.get("read", 0)
            result["elasticsearch_inserted"] = es_sync.get("inserted", 0)
            result["elasticsearch_metrics"] = es_sync.get("metrics", {"status": es_sync.get("status")})
            result["elasticsearch_bandwidth"] = es_sync.get("bandwidth", {"status": es_sync.get("status")})
    except Exception as exc:
        with db_transaction(db_path) as db:
            db.execute(
                "UPDATE jobs SET status='failed',finished_at_ms=?,detail=? WHERE name=?",
                (int(time.time() * 1000), str(exc)[:500], "behavioral-observability"),
            )
        raise
    with db_transaction(db_path) as db:
        db.execute(
            "UPDATE jobs SET status='success',finished_at_ms=?,detail=?,processed_count=? WHERE name=?",
            (int(time.time() * 1000), json.dumps(result, separators=(",", ":")), aggregates["1m_buckets"], "behavioral-observability"),
        )
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser=argparse.ArgumentParser(description="TraceScope analytical worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--start-time", type=str, default="", help="Ignore traces before this timestamp (ISO-8601, unix ms, or 'now'/'deploy_time')")
    parser.add_argument("--ignore-past-data", action="store_true", help="Ignore past data before worker start time")
    args = parser.parse_args()
    if args.start_time:
        object.__setattr__(settings, "worker_start_time", args.start_time)
    if args.ignore_past_data:
        object.__setattr__(settings, "worker_ignore_past_data", True)
    if settings.worker_start_time_ms:
        logging.info(f"Worker initialized with start time cutoff: {settings.worker_start_time_ms} ms (ignoring past data)")
    if settings.run_migrations:
        StorageRepository().migrate()
    while True:
        try:
            print(json.dumps({"event": "worker_cycle_complete", **run_jobs()}), flush=True)
        except Exception as exc:
            print(json.dumps({
                "event": "worker_cycle_failed",
                "error": str(exc)[:500],
                "traceback": traceback.format_exc(limit=8),
            }), flush=True)
            if args.once:
                raise
        if args.once:
            break
        time.sleep(max(10, args.interval))


if __name__ == "__main__": main()
