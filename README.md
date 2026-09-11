# TraceScope

TraceScope is an OpenTelemetry transaction analytics application for large service estates. It imports Elasticsearch APM JSON/NDJSON, a canonical OTLP JSON subset, and NetworkTracing old-kernel capture events, sanitizes Basic authentication credentials before storage, builds exact minute rollups and dependency evidence in a separate worker, and serves investigation dashboards through FastAPI and React.

## Quick start

```sh
cp .env.example .env
docker compose up --build
```

Open <http://localhost:5173>. The container entrypoint migrates the unified behavioral-observability schema, loads the deterministic demo dataset when `traces` is empty, performs analytical jobs, and starts the API and worker. The interface is visibly marked **Demo data**.

For local development:

```sh
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
python -m backend.cli migrate
python -m backend.cli demo --events 24000
python -m backend.cli analyze
uvicorn backend.main:app --reload --port 8000
```

In another terminal:

```sh
cd frontend
npm install
npm run dev
```

Import a file and update analytics:

```sh
python -m backend.cli import-file path/to/export.ndjson
python -m backend.cli analyze
```

The HTTP ingestion endpoints also accept the old-kernel NetworkTracing shipper envelope (`{"node":"host","events":[...]}`). The shipper's exact `/api/ingest` path is supported alongside `/api/v1/ingest` and `/api/v1/ingest/traces`. Compact events may contain `ts`, `service`, `method`, `path`, `user`, `caller`, `dst_ip`, `dst_port`, `status`, `duration_ms`, and W3C `traceparent`; every field is optional and unavailable values use safe canonical defaults. File import unwraps this envelope as well.

The optional Elasticsearch connector is configured with `OTEL_ES_URL`, `OTEL_ES_INDEX`, `OTEL_ES_API_KEY`, and `OTEL_ES_VERIFY_TLS`. It is read-only, uses `search_after`, and persists its checkpoint. Secrets are never written to the database or returned through the API.

```sh
python -m backend.cli sync-elasticsearch
python -m backend.cli analyze
```

## Measurement definitions

- **Observed RPS** is distinct inbound HTTP server requests divided by elapsed seconds. Client spans are excluded, and event identity prevents duplicate imports.
- **Observed TPS** is server transactions divided by elapsed seconds. When all server transactions are HTTP requests, RPS and TPS are mathematically equivalent; the UI says so. Neither measure claims business throughput.
- One-minute and five-minute p50/p95/p99 values are computed from the raw samples in each complete window. Incremental ingestion recomputes each affected five-minute window so partial input cannot replace an existing rollup.
- Rates and percentiles are based on observed records. Sampling coverage is shown as unknown unless the input supplies a reliable population denominator.

See [docs/DESIGN.md](docs/DESIGN.md), [docs/ANOMALIES.md](docs/ANOMALIES.md), and [docs/BENCHMARK.md](docs/BENCHMARK.md).

## Kubernetes deployment

The production manifests split traffic ingestion and agent lifecycle/reporting
into stateless, horizontally scalable Deployments. A single storage-owner
StatefulSet is the only pod that mounts SQLite; edge pods use an authenticated
internal API instead of sharing WAL files across nodes. See the complete
[Kubernetes architecture and migration runbook](deploy/k8s/README.md).

## Tests

```sh
pytest -q
cd frontend && npm run build
```

The lifecycle script binds to `0.0.0.0:30102` and automatically uses `.venv/bin/python` when present. Override `OTEL_HOST` when a narrower bind is required. Set `OTEL_API_KEY` to require `X-API-Key` on ingestion and lifecycle mutations.

## User Intelligence

The additive User Intelligence module derives credential behavior from the existing sanitized trace store—no second raw trace pipeline is used. Its pages are `/users`, `/users/:principal`, `/user-changes`, `/user-graph`, and `/user-analytics`. A configurable historical bootstrap (`OTEL_PRINCIPAL_BOOTSTRAP_RATIO`, default `0.75`) learns expected callers, source IPs, targets, operations, relationships, and activity times before evaluating newer observations.

## Production rollout gaps

- SSO/RBAC, tenant isolation, encrypted secrets management, and a formal security review.
- PostgreSQL/ClickHouse-class repository implementation, HA workers, distributed job leasing, and backups.
- Empirical capacity testing on the target hardware and retention policy approval.
- Sampling/agent coverage metadata, authoritative address-to-service mappings, and clock-skew monitoring.
- TLS termination, audit export, alert routing, SLOs, observability for TraceScope itself, and disaster recovery drills.
