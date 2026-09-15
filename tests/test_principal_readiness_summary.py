from pathlib import Path

from backend.app.services import principal_relationships as service
from backend.app.services.behavioral_engine import evaluate_readiness_from_stats


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeDb:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return _Result([
            ("production:alice", 1000, 9000, 4, 120),
        ])


def test_readiness_summary_is_bounded_and_cached_across_pages():
    db = _FakeDb()
    cache = {}

    service._load_readiness_stats(db, ["production:alice", "production:missing"], cache)
    service._load_readiness_stats(db, ["production:alice", "production:missing"], cache)

    assert len(db.calls) == 1
    sql, params = db.calls[0]
    assert "FROM principal_readiness_summary" in sql
    assert "FROM traces" not in sql
    assert sql.count("?") == 2
    assert params == ["production:alice", "production:missing"]
    assert cache["production:alice"] == (1000, 9000, 4, 120)
    assert cache["production:missing"] is None


def test_summary_tuple_preserves_detector_readiness_inputs():
    stats = (1_600_000_000_000, 1_601_209_600_000, 15, 250)
    now = 1_601_209_600_000

    assert evaluate_readiness_from_stats(stats, "NEW_CALLER", now) == (True, "ready")
    assert evaluate_readiness_from_stats(stats, "OPERATION_MIX_SHIFT", now) == (True, "ready")
    assert evaluate_readiness_from_stats(None, "NEW_CALLER", now) == (False, "insufficient_history")


def test_readiness_migration_populates_idempotently_before_runtime_writers():
    root = Path(__file__).resolve().parents[1]
    migration = (root / "backend/clickhouse_migrations/006_principal_readiness_summary.sql").read_text()

    assert "TO principal_readiness_summary AS" in migration
    assert "INSERT INTO principal_readiness_summary" not in migration
    assert "AggregateFunction(uniqExact, Int64)" in migration
    assert "ifNull(principal_id" in migration
    assert "WHERE principal_name NOT IN ('', 'unknown')" in migration


def test_principal_cursor_remains_narrow_and_checkpoint_follows_flush():
    source = Path(service.__file__).read_text()
    process = source[source.index("def process_principal_intelligence"):]

    assert "SELECT * FROM traces" not in process
    assert "ORDER BY ingest_order,row_uid LIMIT ?" in process
    assert process.index("batch.flush()") < process.index("INSERT INTO checkpoints")
