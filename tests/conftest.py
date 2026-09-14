from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_test_clickhouse_db = f"test_pytest_{tempfile.gettempprefix()}_{os.getpid()}"

os.environ["OTEL_DEMO_MODE"] = "true"
os.environ["OTEL_CLICKHOUSE_DATABASE"] = _test_clickhouse_db

if "OTEL_CLICKHOUSE_HOST" not in os.environ:
    import socket
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _sock.settimeout(0.2)
    try:
        _sock.connect(("127.0.0.1", int(os.getenv("OTEL_CLICKHOUSE_PORT", "8123"))))
        _sock.close()
    except Exception:
        os.environ["OTEL_CLICKHOUSE_HOST"] = "10.244.0.110"

from backend.app.repositories import clickhouse_migrator

_orig_run_migrations = clickhouse_migrator.run_clickhouse_migrations


def _test_safe_migrations(database=None):
    res = _orig_run_migrations(database)
    target_db = clickhouse_migrator.resolve_target_db(database)
    if target_db.startswith("test_"):
        try:
            client = clickhouse_migrator.get_clickhouse_client(target_db)
            client.command("ALTER TABLE traces REMOVE TTL")
            client.command("ALTER TABLE metric_buckets REMOVE TTL")
        except Exception:
            pass
    return res


clickhouse_migrator.run_clickhouse_migrations = _test_safe_migrations


def pytest_sessionfinish(session, exitstatus):
    try:
        import clickhouse_connect
        client = clickhouse_connect.get_client(
            host=os.getenv("OTEL_CLICKHOUSE_HOST", "127.0.0.1"),
            port=int(os.getenv("OTEL_CLICKHOUSE_PORT", "8123")),
            username=os.getenv("OTEL_CLICKHOUSE_USER", "default"),
            password=os.getenv("OTEL_CLICKHOUSE_PASSWORD", ""),
        )
        client.command(f"DROP DATABASE IF EXISTS {_test_clickhouse_db}")
        # tmp_path-based tests create test_<md5> databases; reclaim them all so
        # repeated runs do not accumulate orphans on the server.
        for name in client.command("SHOW DATABASES").splitlines():
            if name.startswith("test_"):
                client.command(f"DROP DATABASE IF EXISTS {name}")
    except Exception:
        pass
