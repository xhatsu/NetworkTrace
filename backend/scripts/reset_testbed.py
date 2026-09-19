#!/usr/bin/env python3
"""Reset testbed by wiping ClickHouse analytical tables and Elasticsearch APM indices."""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import urllib.request
from backend.app.repositories.db_context import get_connection

ES_URL = "http://127.0.0.1:32073"

def wipe_clickhouse():
    print("Wiping ClickHouse analytical tables...")
    with get_connection() as db:
        tables = [
            row[0] for row in db.execute("SHOW TABLES FROM tracescope").fetchall()
            if row[0] not in ("schema_migrations", "principal_readiness_summary_mv")
        ]
        for tbl in tables:
            try:
                db.execute(f"TRUNCATE TABLE tracescope.{tbl}")
                print(f"  Truncated {tbl}")
            except Exception as e:
                print(f"  Failed to truncate {tbl}: {e}")
    print("ClickHouse tables wiped cleanly.")

def wipe_elasticsearch():
    print("Wiping Elasticsearch APM indices...")
    for pattern in ("apm-*", "traces-apm*"):
        try:
            req = urllib.request.Request(f"{ES_URL}/{pattern}", method="DELETE")
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"  Elasticsearch {pattern} indices deleted.")
        except Exception as e:
            print(f"  Note on Elasticsearch wipe ({pattern}): {e}")

from backend.app.repositories.clickhouse_migrator import truncate_system_logs

if __name__ == "__main__":
    wipe_clickhouse()
    wipe_elasticsearch()
    try:
        truncate_system_logs()
        print("ClickHouse system telemetry logs truncated.")
    except Exception as e:
        print(f"Note on system logs truncation: {e}")
    print("Testbed reset complete.")
