"""ClickHouse schema migrator — manages versioned migrations for ClickHouse."""
from __future__ import annotations

import logging
import time
import hashlib
import re
from pathlib import Path
from typing import Optional

import clickhouse_connect
from backend.config import settings

log = logging.getLogger("tracescope-hub")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "clickhouse_migrations"


def resolve_target_db(database: Optional[str] = None) -> str:
    """Derive target ClickHouse database name, converting file paths to test database names."""
    if not database:
        return settings.clickhouse_database
    str_path = str(database)
    if re.match(r"^[a-zA-Z0-9_]+$", str_path) and not str_path.endswith(".db"):
        return str_path
    h = hashlib.md5(str_path.encode()).hexdigest()[:12]
    return f"test_{h}"


def get_clickhouse_client(database: Optional[str] = None) -> clickhouse_connect.driver.Client:
    """Create a client connected to ClickHouse."""
    db_name = resolve_target_db(database)
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=db_name,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        secure=settings.clickhouse_secure,
        connect_timeout=settings.clickhouse_connect_timeout,
        send_receive_timeout=settings.clickhouse_send_receive_timeout,
    )


def ensure_database(database: Optional[str] = None) -> None:
    """Ensure target database exists in ClickHouse."""
    target_db = resolve_target_db(database)
    # Connect without specifying database to create it
    sys_client = clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        secure=settings.clickhouse_secure,
        connect_timeout=settings.clickhouse_connect_timeout,
        send_receive_timeout=settings.clickhouse_send_receive_timeout,
    )
    sys_client.command(f"CREATE DATABASE IF NOT EXISTS {target_db}")


def run_clickhouse_migrations(database: Optional[str] = None) -> list[str]:
    """Apply all pending migrations in sorted order and return applied versions."""
    target_db = resolve_target_db(database)
    ensure_database(target_db)
    client = get_clickhouse_client(target_db)

    # Ensure schema_migrations table exists
    client.command("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version String,
            applied_at_ms UInt64
        ) ENGINE = ReplacingMergeTree(applied_at_ms)
        ORDER BY (version)
    """)

    applied_rows = client.query("SELECT version FROM schema_migrations FINAL").result_rows
    applied = {row[0] for row in applied_rows}

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    newly_applied = []

    for path in migration_files:
        version = path.name
        if version in applied:
            continue

        log.info("Applying ClickHouse migration: %s", version)
        content = path.read_text(encoding="utf-8")
        # Split on semicolon, taking care of comments
        statements = []
        for raw_stmt in content.split(";"):
            stmt = raw_stmt.strip()
            # Filter out empty statements or purely comment lines
            lines = [line for line in stmt.splitlines() if line.strip() and not line.strip().startswith("--")]
            clean_stmt = "\n".join(lines).strip()
            if clean_stmt:
                statements.append(clean_stmt)

        for stmt in statements:
            client.command(stmt)

        now_ms = int(time.time() * 1000)
        client.command(
            "INSERT INTO schema_migrations (version, applied_at_ms) VALUES ({v:String}, {t:UInt64})",
            parameters={"v": version, "t": now_ms}
        )
        newly_applied.append(version)

    return newly_applied
