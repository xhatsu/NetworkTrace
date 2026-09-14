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


def run_jobs() -> dict[str, int]:
    started = int(time.time() * 1000)
    with db_transaction() as db:
        db.execute("DELETE FROM jobs WHERE name=?", ("behavioral-observability",))
        db.execute("INSERT INTO jobs(name,status,started_at_ms,detail,processed_count) VALUES(?,?,?,?,0)",
                   ("behavioral-observability", "running", started, ""))
    try:
        aggregates = _run_stage("aggregate_traces", aggregate_traces)
        baselines = _run_stage("rebuild_baselines", _run_changed_baselines)
        anomalies = _run_stage("detect_anomalies", _run_revised_anomalies)
        principals = _run_stage("process_principal_intelligence", process_principal_intelligence)
        result = {**aggregates, "baselines": baselines, "anomalies": len(anomalies),
                  "principal_records": principals["processed"], "principal_changes": principals["changes"]}
    except Exception as exc:
        with db_transaction() as db:
            db.execute(
                "UPDATE jobs SET status='failed',finished_at_ms=?,detail=? WHERE name=?",
                (int(time.time() * 1000), str(exc)[:500], "behavioral-observability"),
            )
        raise
    with db_transaction() as db:
        db.execute(
            "UPDATE jobs SET status='success',finished_at_ms=?,detail=?,processed_count=? WHERE name=?",
            (int(time.time() * 1000), json.dumps(result, separators=(",", ":")), aggregates["1m_buckets"], "behavioral-observability"),
        )
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser=argparse.ArgumentParser(description="TraceScope analytical worker")
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval",type=int,default=60)
    args=parser.parse_args()
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
