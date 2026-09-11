"""Traffic-log ingestion entrypoint (role ``ingest``).

Exposes only the HTTP trace receivers and ingestion status:

  POST /api/v1/ingest, POST /api/v1/ingest/traces   (canonical)
  POST /api/ingest, POST /api/ingest/apm            (old-kernel shipper compat)
  POST /v1/traces, /v1/metrics, /v1/logs            (OTLP/HTTP)
  GET  /api/v1/health, GET /api/v1/ingestion/status

Run with::

    uvicorn backend.ingest_main:app --host 0.0.0.0 --port 30103

With ``OTEL_STORAGE_OWNER_URL`` configured (the Kubernetes default), this
process forwards normalized records to the single storage owner and never
opens SQLite. Without it, local standalone mode retains the in-process writer.
"""
from __future__ import annotations

from backend.app.application import ROLE_INGEST, create_app

app = create_app(ROLE_INGEST)
