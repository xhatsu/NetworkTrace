import os
import pytest
from backend.app.repositories.clickhouse_migrator import (
    configure_system_telemetry_retention,
    truncate_system_logs,
    SYSTEM_LOG_TABLES,
    SYSTEM_ERROR_TABLES,
)


def test_configure_system_telemetry_retention():
    results = configure_system_telemetry_retention(log_retention_days=3, error_retention_days=7)
    assert isinstance(results, dict)
    for tbl in SYSTEM_LOG_TABLES:
        assert tbl in results
        assert results[tbl] is True
    for tbl in SYSTEM_ERROR_TABLES:
        assert tbl in results
        assert results[tbl] is True


def test_truncate_system_logs():
    results = truncate_system_logs()
    assert isinstance(results, dict)
    for tbl in SYSTEM_LOG_TABLES + SYSTEM_ERROR_TABLES:
        assert tbl in results
        assert results[tbl] is True
