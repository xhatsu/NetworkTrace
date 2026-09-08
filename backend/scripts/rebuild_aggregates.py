#!/usr/bin/env python3
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.services.aggregation import aggregate_traces
from backend.app.services.baseline import rebuild_baselines
from backend.app.services.anomaly_detection import detect_anomalies

def main():
    print("Rebuilding 1m & 5m metric buckets and topology edges from traces...")
    t0 = time.time()
    res = aggregate_traces()
    print(f"Buckets generated: {res} in {round(time.time() - t0, 2)}s")

    print("Rebuilding historical baselines (median & MAD per dimension)...")
    t1 = time.time()
    b_count = rebuild_baselines()
    print(f"Baselines computed: {b_count} in {round(time.time() - t1, 2)}s")

    print("Evaluating anomaly rules (Detectors 1-8)...")
    t2 = time.time()
    from backend.app.repositories.db_context import get_connection
    with get_connection() as db:
        windows = [r[0] for r in db.execute("SELECT DISTINCT bucket_start FROM metric_buckets WHERE bucket_size = 300 ORDER BY bucket_start").fetchall()]

    all_anomalies = []
    for w in windows:
        found = detect_anomalies(window_start_sec=w, window_end_sec=w + 300)
        all_anomalies.extend(found)

    print(f"Anomalies detected: {len(all_anomalies)} across {len(windows)} windows in {round(time.time() - t2, 2)}s")
    for a in all_anomalies[:5]:
        print(f"  [{a.severity.upper()}] {a.target_service or a.caller_service}: {a.reasons[0].text if a.reasons else a.anomaly_type}")

if __name__ == "__main__":
    main()
