from __future__ import annotations

import argparse
import json
import time
import traceback

from .repository import SQLiteRepository
from .config import settings
from .app.services.aggregation import aggregate_traces
from .app.services.anomaly_detection import detect_anomalies
from .app.services.baseline import rebuild_baselines
from .app.services.principal_relationships import process_principal_intelligence
from .app.repositories.db_context import db_transaction


def _run_stage(name: str, operation):
    started = time.monotonic()
    print(json.dumps({"event": "worker_stage_start", "stage": name}), flush=True)
    result = operation()
    print(json.dumps({
        "event": "worker_stage_complete",
        "stage": name,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }), flush=True)
    return result


def run_jobs() -> dict[str, int]:
    started = int(time.time() * 1000)
    with db_transaction() as db:
        db.execute(
            "INSERT INTO jobs(name,status,started_at_ms,detail,processed_count) VALUES(?,?,?,?,0) "
            "ON CONFLICT(name) DO UPDATE SET status=excluded.status,started_at_ms=excluded.started_at_ms,finished_at_ms=NULL,detail=''",
            ("behavioral-observability", "running", started, ""),
        )
    try:
        aggregates = _run_stage("aggregate_traces", aggregate_traces)
        baselines = _run_stage("rebuild_baselines", rebuild_baselines)
        anomalies = _run_stage("detect_anomalies", detect_anomalies)
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
    parser=argparse.ArgumentParser(description="TraceScope analytical worker")
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval",type=int,default=60)
    args=parser.parse_args()
    if settings.run_migrations:
        SQLiteRepository().migrate()
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
