"""TraceScope SQLite to ClickHouse data migration utility.

Transfers all historical traces, rollups, baselines, anomalies, user intelligence,
and agent health records from tracescope.db to ClickHouse in durable batches.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import clickhouse_connect
from backend.config import settings
from backend.app.repositories.clickhouse_migrator import run_clickhouse_migrations, ensure_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("tracescope-migration")

# Tables to migrate in dependency order
MIGRATION_TABLES = [
    "schema_migrations",
    "services",
    "accounts",
    "events",
    "latency_rollups",
    "topology_edges",
    "anomalies",
    "anomaly_occurrences",
    "checkpoints",
    "jobs",
    "traces",
    "metric_buckets",
    "service_edges",
    "principal_service_edges",
    "baseline_metrics",
    "anomaly_events",
    "principals",
    "principal_callers",
    "principal_sources",
    "principal_targets",
    "principal_operations",
    "principal_relationships",
    "principal_hourly_activity",
    "principal_daily_stats",
    "principal_baselines",
    "principal_change_events",
    "agent_stats_latest",
    "agent_stats_history",
    "incidents",
    "historical_registry",
    "established_baselines",
    "candidate_behaviors",
    "operator_overrides",
    "telemetry_quality_windows",
    "ingest_batches",
]


def get_sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")}


def get_sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def get_clickhouse_columns(client: clickhouse_connect.driver.Client, table: str) -> dict[str, str]:
    res = client.query(f"DESCRIBE TABLE {table}")
    return {r[0]: r[1] for r in res.result_rows}


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    ch_client: clickhouse_connect.driver.Client,
    table: str,
    batch_size: int = 10_000,
) -> tuple[int, int]:
    """Migrate one table from SQLite to ClickHouse in batches."""
    sqlite_cols = get_sqlite_columns(sqlite_conn, table)
    ch_cols_map = get_clickhouse_columns(ch_client, table)

    # Common columns
    common_cols = [c for c in sqlite_cols if c in ch_cols_map]
    if not common_cols:
        log.warning("Table %s has no matching columns between SQLite and ClickHouse", table)
        return 0, 0

    count_res = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    total_rows = count_res[0] if count_res else 0
    if total_rows == 0:
        log.info("Table %s is empty in SQLite; skipping", table)
        return 0, 0

    ch_client.command(f"TRUNCATE TABLE IF EXISTS {table}")
    log.info("Migrating %s (%d rows) using columns: %s", table, total_rows, ", ".join(common_cols))

    col_expr = ", ".join(common_cols)
    cursor = sqlite_conn.execute(f"SELECT {col_expr} FROM {table}")

    migrated = 0
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break

        processed_rows = []
        for r in rows:
            row_vals = []
            for col, val in zip(common_cols, r):
                ch_type = ch_cols_map[col]
                # Type sanitization for ClickHouse
                if val is None:
                    if "Nullable" in ch_type:
                        row_vals.append(None)
                    elif "Int" in ch_type:
                        row_vals.append(0)
                    elif "Float" in ch_type:
                        row_vals.append(0.0)
                    elif "String" in ch_type:
                        row_vals.append("")
                    else:
                        row_vals.append(None)
                else:
                    if "Int" in ch_type and not isinstance(val, int):
                        try:
                            row_vals.append(int(val))
                        except Exception:
                            row_vals.append(0)
                    elif "Float" in ch_type and not isinstance(val, (float, int)):
                        try:
                            row_vals.append(float(val))
                        except Exception:
                            row_vals.append(0.0)
                    else:
                        row_vals.append(val)
            processed_rows.append(row_vals)

        ch_client.insert(table, processed_rows, column_names=common_cols)
        migrated += len(processed_rows)
        log.info("  %s: migrated %d / %d rows", table, migrated, total_rows)

    ch_count = ch_client.query(f"SELECT count() FROM {table}").result_rows[0][0]
    return total_rows, ch_count


def migrate_database(
    sqlite_path: Path | str,
    database: Optional[str] = None,
    batch_size: int = 10_000,
    verify_only: bool = False,
) -> dict[str, dict[str, int]]:
    """Run full database migration from SQLite to ClickHouse."""
    sqlite_path = Path(sqlite_path)
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"Source SQLite database not found at {sqlite_path}")

    target_db = database or settings.clickhouse_database
    log.info("Connecting to source SQLite at %s", sqlite_path)
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = None

    log.info("Ensuring ClickHouse database and migrations for %s", target_db)
    ensure_database(target_db)
    new_migrations = run_clickhouse_migrations(target_db)
    if new_migrations:
        log.info("Applied migrations: %s", new_migrations)

    ch_client = clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=target_db,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        secure=settings.clickhouse_secure,
        connect_timeout=settings.clickhouse_connect_timeout,
        send_receive_timeout=settings.clickhouse_send_receive_timeout,
    )

    sqlite_tables = get_sqlite_tables(sqlite_conn)
    results: dict[str, dict[str, int]] = {}

    for table in MIGRATION_TABLES:
        if table not in sqlite_tables:
            continue

        if verify_only:
            sq_count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            try:
                ch_count_res = ch_client.query(f"SELECT count() FROM {table}").first_item
                ch_count = list(ch_count_res.values())[0] if isinstance(ch_count_res, dict) else ch_count_res
            except Exception:
                ch_count = 0
            results[table] = {"sqlite": sq_count, "clickhouse": ch_count}
            log.info("Verify %s: SQLite=%d, ClickHouse=%d", table, sq_count, ch_count)
            continue

        sq_rows, ch_rows = migrate_table(sqlite_conn, ch_client, table, batch_size=batch_size)
        results[table] = {"sqlite": sq_rows, "clickhouse": ch_rows}

    sqlite_conn.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="TraceScope SQLite to ClickHouse Migration Utility")
    parser.add_argument("--sqlite-path", type=str, default=str(settings.db_path), help="Path to SQLite database")
    parser.add_argument("--clickhouse-db", type=str, default=settings.clickhouse_database, help="Target ClickHouse database")
    parser.add_argument("--batch-size", type=int, default=10_000, help="Batch size for inserts")
    parser.add_argument("--verify", action="store_true", help="Verify counts only without migrating")
    args = parser.parse_args()

    started = time.monotonic()
    log.info("Starting migration: SQLite(%s) -> ClickHouse(%s)", args.sqlite_path, args.clickhouse_db)
    results = migrate_database(
        sqlite_path=args.sqlite_path,
        database=args.clickhouse_db,
        batch_size=args.batch_size,
        verify_only=args.verify,
    )

    elapsed = round(time.monotonic() - started, 2)
    log.info("Migration finished in %s seconds. Summary:", elapsed)
    total_sqlite = sum(v["sqlite"] for v in results.values())
    total_ch = sum(v["clickhouse"] for v in results.values())

    print("\n" + "=" * 60)
    print(f"{'Table':<30} | {'SQLite Rows':<12} | {'ClickHouse Rows':<12}")
    print("-" * 60)
    for tbl, counts in results.items():
        print(f"{tbl:<30} | {counts['sqlite']:<12} | {counts['clickhouse']:<12}")
    print("=" * 60)
    print(f"{'TOTAL':<30} | {total_sqlite:<12} | {total_ch:<12}")
    print(f"Elapsed: {elapsed}s\n")


if __name__ == "__main__":
    main()
