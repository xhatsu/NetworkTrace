"""Centralize deployment knobs so every role shares one ClickHouse contract.

Keeping storage, batching, and role settings here prevents independently scaled
edge pods from silently adopting incompatible durability or backpressure rules.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # Namespace for side files (policy.json); durable telemetry lives in ClickHouse.
    data_dir: Path = Path(os.getenv("OTEL_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
    clickhouse_host: str = os.getenv("OTEL_CLICKHOUSE_HOST", "127.0.0.1")
    clickhouse_port: int = int(os.getenv("OTEL_CLICKHOUSE_PORT", "8123"))
    clickhouse_database: str = os.getenv("OTEL_CLICKHOUSE_DATABASE", "tracescope")
    clickhouse_user: str = os.getenv("OTEL_CLICKHOUSE_USER", "default")
    clickhouse_password: str = os.getenv("OTEL_CLICKHOUSE_PASSWORD", "")
    clickhouse_secure: bool = os.getenv("OTEL_CLICKHOUSE_SECURE", "false").lower() == "true"
    clickhouse_connect_timeout: float = float(os.getenv("OTEL_CLICKHOUSE_CONNECT_TIMEOUT", "10.0"))
    clickhouse_send_receive_timeout: float = float(os.getenv("OTEL_CLICKHOUSE_TIMEOUT", "30.0"))
    demo_mode: bool = os.getenv("OTEL_DEMO_MODE", "true").lower() == "true"
    cors_origins: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv(
            "OTEL_CORS_ORIGINS",
            "http://127.0.0.1:30102,http://localhost:30102,http://localhost:5173",
        ).split(",") if item.strip()
    )
    api_key: str = os.getenv("OTEL_API_KEY", "")
    storage_owner_url: str = os.getenv("OTEL_STORAGE_OWNER_URL", "").rstrip("/")
    internal_api_token: str = os.getenv("OTEL_INTERNAL_API_TOKEN", "")
    internal_request_timeout_seconds: float = max(
        1.0, float(os.getenv("OTEL_INTERNAL_REQUEST_TIMEOUT_SECONDS", "70"))
    )
    max_ingest_bytes: int = int(os.getenv("OTEL_MAX_INGEST_BYTES", str(10 * 1024 * 1024)))
    max_ingest_records: int = int(os.getenv("OTEL_MAX_INGEST_RECORDS", "10000"))
    ingest_queue_capacity: int = max(1, int(os.getenv("OTEL_INGEST_QUEUE_CAPACITY", "256")))
    ingest_coalesce_ms: int = max(0, int(os.getenv("OTEL_INGEST_COALESCE_MS", "5")))
    ingest_transaction_records: int = max(1, int(os.getenv("OTEL_INGEST_TRANSACTION_RECORDS", "50000")))
    ingest_max_batch_bytes: int = max(
        1, int(os.getenv("OTEL_INGEST_MAX_BATCH_BYTES", str(32 * 1024 * 1024)))
    )
    ingest_commit_timeout_seconds: float = max(1.0, float(os.getenv("OTEL_INGEST_COMMIT_TIMEOUT_SECONDS", "65")))
    aggregation_max_memory_usage: int = max(
        1, int(os.getenv("OTEL_AGGREGATION_MAX_MEMORY_USAGE", str(1024 * 1024 * 1024)))
    )
    aggregation_external_group_by_bytes: int = max(
        1,
        int(os.getenv(
            "OTEL_AGGREGATION_EXTERNAL_GROUP_BY_BYTES", str(256 * 1024 * 1024)
        )),
    )
    # Shadow states are enabled by default for development comparison only.
    # Serving stays on exact metric_buckets unless an operator explicitly cuts over.
    aggregation_shadow_enabled: bool = os.getenv(
        "OTEL_AGGREGATION_SHADOW_ENABLED", "true"
    ).lower() == "true"
    aggregation_cutover: bool = os.getenv(
        "OTEL_AGGREGATION_CUTOVER", "false"
    ).lower() == "true"
    baseline_cadence_seconds: int = max(
        60, int(os.getenv("OTEL_BASELINE_CADENCE_SECONDS", "300"))
    )
    baseline_series_budget: int = max(
        1, int(os.getenv("OTEL_BASELINE_SERIES_BUDGET", "100"))
    )
    anomaly_window_budget: int = max(
        1, int(os.getenv("OTEL_ANOMALY_WINDOW_BUDGET", "100"))
    )
    analytics_stage_budget_seconds: float = max(
        1.0, float(os.getenv("OTEL_ANALYTICS_STAGE_BUDGET_SECONDS", "55"))
    )
    principal_bootstrap_ratio: float = min(0.95, max(0.5, float(os.getenv("OTEL_PRINCIPAL_BOOTSTRAP_RATIO", "0.75"))))
    principal_learning_days: int = int(os.getenv("OTEL_PRINCIPAL_LEARNING_DAYS", "7"))
    principal_dormant_days: int = int(os.getenv("OTEL_PRINCIPAL_DORMANT_DAYS", "30"))
    principal_active_minutes: int = int(os.getenv("OTEL_PRINCIPAL_ACTIVE_MINUTES", "15"))
    max_range_days: int = 31
    slow_threshold_us: int = 1_000_000
    retention_days: int = int(os.getenv("OTEL_RETENTION_DAYS", "0"))
    # Schema ownership. Exactly one pod in a fleet should run migrations
    # (default "true" preserves the historical single-process behaviour).
    run_migrations: bool = os.getenv("OTEL_RUN_MIGRATIONS", "true").lower() == "true"


settings = Settings()
