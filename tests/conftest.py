from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_test_dir = Path(tempfile.mkdtemp(prefix="tracescope-tests-"))
os.environ["OTEL_DB_PATH"] = str(_test_dir / "tracescope.db")
os.environ["OTEL_DEMO_MODE"] = "true"


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_test_dir, ignore_errors=True)
