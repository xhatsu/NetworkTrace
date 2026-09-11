from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_test_dir = Path(tempfile.mkdtemp(prefix="tracescope-tests-"))
_test_clickhouse_db = f"test_pytest_{tempfile.gettempprefix()}_{os.getpid()}"

os.environ["OTEL_DB_PATH"] = str(_test_dir / "tracescope.db")
os.environ["OTEL_DEMO_MODE"] = "true"
os.environ["OTEL_CLICKHOUSE_DATABASE"] = _test_clickhouse_db


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_test_dir, ignore_errors=True)
    try:
        import clickhouse_connect
        client = clickhouse_connect.get_client(
            host=os.getenv("OTEL_CLICKHOUSE_HOST", "127.0.0.1"),
            port=int(os.getenv("OTEL_CLICKHOUSE_PORT", "8123")),
            username=os.getenv("OTEL_CLICKHOUSE_USER", "default"),
            password=os.getenv("OTEL_CLICKHOUSE_PASSWORD", ""),
        )
        client.command(f"DROP DATABASE IF EXISTS {_test_clickhouse_db}")
    except Exception:
        pass
