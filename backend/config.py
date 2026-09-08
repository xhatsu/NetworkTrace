from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path(os.getenv("OTEL_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "tracescope.db")))
    demo_mode: bool = os.getenv("OTEL_DEMO_MODE", "true").lower() == "true"
    cors_origins: tuple[str, ...] = tuple(
        item.strip() for item in os.getenv(
            "OTEL_CORS_ORIGINS",
            "http://127.0.0.1:30102,http://localhost:30102,http://localhost:5173",
        ).split(",") if item.strip()
    )
    api_key: str = os.getenv("OTEL_API_KEY", "")
    max_ingest_bytes: int = int(os.getenv("OTEL_MAX_INGEST_BYTES", str(10 * 1024 * 1024)))
    max_ingest_records: int = int(os.getenv("OTEL_MAX_INGEST_RECORDS", "10000"))
    principal_bootstrap_ratio: float = min(0.95, max(0.5, float(os.getenv("OTEL_PRINCIPAL_BOOTSTRAP_RATIO", "0.75"))))
    principal_learning_days: int = int(os.getenv("OTEL_PRINCIPAL_LEARNING_DAYS", "7"))
    principal_dormant_days: int = int(os.getenv("OTEL_PRINCIPAL_DORMANT_DAYS", "30"))
    principal_active_minutes: int = int(os.getenv("OTEL_PRINCIPAL_ACTIVE_MINUTES", "15"))
    max_range_days: int = 31
    slow_threshold_us: int = 1_000_000
    retention_days: int = int(os.getenv("OTEL_RETENTION_DAYS", "0"))


settings = Settings()
