from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_test_clickhouse_db = f"test_pytest_{tempfile.gettempprefix()}_{os.getpid()}"

os.environ["OTEL_DEMO_MODE"] = "true"
os.environ["OTEL_CLICKHOUSE_DATABASE"] = _test_clickhouse_db
os.environ["OTEL_CLICKHOUSE_ONLY_AGENT_TRACES"] = "false"

if "OTEL_CLICKHOUSE_HOST" not in os.environ:
    import glob
    import socket
    port = int(os.getenv("OTEL_CLICKHOUSE_PORT", "8123"))
    candidates = ["127.0.0.1", "10.244.0.118", "10.244.0.110"]
    try:
        for p in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                with open(p, "rb") as f:
                    if b"clickhouse-server" in f.read():
                        pid = p.split("/")[2]
                        tcp6 = f"/proc/{pid}/net/tcp6"
                        if os.path.exists(tcp6):
                            with open(tcp6) as tf:
                                for line in tf:
                                    parts = line.strip().split()
                                    if len(parts) >= 4 and parts[3] in ("0A", "01"):
                                        hex_addr, hp = parts[1].split(":")
                                        if int(hp, 16) == port and hex_addr.startswith("0000000000000000FFFF0000"):
                                            h = hex_addr[24:]
                                            ip = ".".join(str(int(h[i:i+2], 16)) for i in (6, 4, 2, 0))
                                            candidates.insert(0, ip)
            except Exception:
                pass
    except Exception:
        pass
    for host in candidates:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                os.environ["OTEL_CLICKHOUSE_HOST"] = host
                break
        except Exception:
            continue

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
