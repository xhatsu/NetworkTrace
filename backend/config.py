"""Centralize deployment knobs so every role shares one ClickHouse contract.

Keeping storage, batching, and role settings here prevents independently scaled
edge pods from silently adopting incompatible durability or backpressure rules.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
import re
import time
from datetime import datetime


def _detect_clickhouse_host() -> str:
    env_host = os.getenv("OTEL_CLICKHOUSE_HOST")
    if env_host:
        return env_host
    import socket
    for candidate in ("127.0.0.1", "10.105.101.253", "10.244.0.118"):
        try:
            with socket.create_connection((candidate, 8123), timeout=0.2):
                return candidate
        except (OSError, socket.timeout):
            pass
    return "127.0.0.1"


def _parse_timestamp_setting(val: str | None) -> int | None:
    if not val:
        return None
    val = val.strip()
    if not val:
        return None
    if val.lower() in ("now", "deploy_time", "current_time"):
        return int(time.time() * 1000)
    if val.isdigit():
        ts = int(val)
        return ts * 1000 if ts < 10_000_000_000 else ts
    try:
        text = val.replace("Z", "+00:00")
        text = re.sub(r"(\.\d{6})\d+", r"\1", text)
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except Exception:
        return None


@dataclass(frozen=True)
class Settings:
    # Namespace for side files (policy.json); durable telemetry lives in ClickHouse.
    data_dir: Path = Path(os.getenv("OTEL_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
    clickhouse_host: str = _detect_clickhouse_host()
    clickhouse_port: int = int(os.getenv("OTEL_CLICKHOUSE_PORT", "8123"))
    clickhouse_database: str = os.getenv("OTEL_CLICKHOUSE_DATABASE", "tracescope")
    clickhouse_user: str = os.getenv("OTEL_CLICKHOUSE_USER", "default")
    clickhouse_password: str = os.getenv("OTEL_CLICKHOUSE_PASSWORD", "")
    clickhouse_secure: bool = os.getenv("OTEL_CLICKHOUSE_SECURE", "false").lower() == "true"
    clickhouse_connect_timeout: float = float(os.getenv("OTEL_CLICKHOUSE_CONNECT_TIMEOUT", "10.0"))
    clickhouse_send_receive_timeout: float = float(os.getenv("OTEL_CLICKHOUSE_TIMEOUT", "30.0"))
    clickhouse_system_log_retention_days: int = max(
        1, int(os.getenv("OTEL_CLICKHOUSE_SYSTEM_LOG_RETENTION_DAYS", "1"))
    )
    clickhouse_system_error_log_retention_days: int = max(
        1, int(os.getenv("OTEL_CLICKHOUSE_SYSTEM_ERROR_LOG_RETENTION_DAYS", "1"))
    )
    # Storage isolation: OTel trace data is retained in Elasticsearch; ClickHouse only stores agent trace data.
    clickhouse_only_agent_traces: bool = (
        os.getenv("OTEL_CLICKHOUSE_ONLY_AGENT_TRACES", "true").lower() == "true"
    )
    # Storage Backend: 'clickhouse' (default for local testbed) or 'elasticsearch' / 'elk'
    storage_backend: str = os.getenv("OTEL_STORAGE_BACKEND", "clickhouse").lower()
    elasticsearch_url: str = os.getenv("OTEL_ES_URL", os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:32073")).rstrip("/")
    elasticsearch_index: str = os.getenv("OTEL_ES_INDEX", "apm-*,traces-apm*")
    elasticsearch_api_key: str = os.getenv("OTEL_ES_API_KEY", "")
    elasticsearch_user: str = os.getenv("OTEL_ES_USER", "")
    elasticsearch_password: str = os.getenv("OTEL_ES_PASSWORD", "")
    elasticsearch_verify_tls: bool = os.getenv("OTEL_ES_VERIFY_TLS", "false").lower() == "true"
    elasticsearch_timeout: float = float(os.getenv("OTEL_ES_TIMEOUT", "15.0"))
    elasticsearch_retention_days: int = max(1, int(os.getenv("OTEL_ES_RETENTION_DAYS", "7")))
    demo_mode: bool = os.getenv("OTEL_DEMO_MODE", "true").lower() == "true"
    cors_origins: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv(
            "OTEL_CORS_ORIGINS",
            "http://127.0.0.1:30102,http://localhost:30102,http://localhost:5173",
        ).split(",") if item.strip()
    )
    # Known infrastructure IP categories
    known_f5: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv(
            "OTEL_KNOWN_F5",
            "10.240.147.247,10.240.147.249,10.10.1.20,10.20.14.78,10.20.1.15",
        ).split(",") if item.strip()
    )
    known_lb: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv("OTEL_KNOWN_LB", "").split(",") if item.strip()
    )
    known_reverse_proxy: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv("OTEL_KNOWN_REVERSE_PROXY", "").split(",") if item.strip()
    )
    known_nat: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv("OTEL_KNOWN_NAT", "").split(",") if item.strip()
    )
    # Known Load Balancer / Ingress IPs treated as supporting attribution context (confidence: low)
    known_load_balancers: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv(
            "OTEL_KNOWN_LOAD_BALANCERS",
            "10.240.147.247,10.240.147.249,10.10.1.20,10.20.14.78,10.20.1.15",
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
    # Worker cutoff parameters: ignore past data and start work after a specific time (e.g. deploy time)
    worker_start_time: str = os.getenv("OTEL_WORKER_START_TIME", os.getenv("OTEL_AGGREGATION_START_TIME", ""))
    worker_ignore_past_data: bool = os.getenv("OTEL_WORKER_IGNORE_PAST_DATA", os.getenv("OTEL_IGNORE_PAST_DATA", "false")).lower() in ("true", "1", "yes")

    # Explicit, single-owner investigation worker.  Budgets are policy-v1
    # constants in the implementation; these settings only select ownership
    # and the operator-supplied relay destination.
    llm_investigation_enabled: bool = os.getenv("OTEL_LLM_INVESTIGATION_ENABLED", "false").lower() in ("true", "1", "yes")
    llm_single_owner_ack: bool = os.getenv("OTEL_LLM_SINGLE_OWNER_ACK", "false").lower() in ("true", "1", "yes")
    llm_base_url: str = os.getenv("OTEL_LLM_BASE_URL", "").rstrip("/")
    llm_api_key: str = field(default=os.getenv("OTEL_LLM_API_KEY", ""), repr=False)
    llm_model: str = os.getenv("OTEL_LLM_MODEL", "")
    llm_response_mode: str = os.getenv("OTEL_LLM_RESPONSE_MODE", "json_object")
    llm_allow_loopback_http: bool = os.getenv("OTEL_LLM_ALLOW_LOOPBACK_HTTP", "false").lower() in ("true", "1", "yes")
    llm_context_tokens: int = int(os.getenv("OTEL_LLM_CONTEXT_TOKENS", "32768"))

    @property
    def worker_start_time_ms(self) -> int | None:
        ts = _parse_timestamp_setting(self.worker_start_time)
        if ts is not None:
            return ts
        if self.worker_ignore_past_data:
            return int(time.time() * 1000)
        return None


settings = Settings()
