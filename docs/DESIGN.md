# TraceScope design

## Product structure

The desktop shell has an estate navigation rail, a persistent investigation filter bar, a visible freshness indicator, and primary routes: Overview (`/`), Topology (`/topology`), Anomalies (`/anomalies`), Services (`/services`), Principals (`/principals`), Traces (`/traces`), User Intelligence (`/users`, `/user-changes`, `/user-graph`, `/user-analytics`), and Agent Fleet (`/agent-stats`, `/agent-stats/:node`). Filter state is encoded in the URL. Overview presents estate health KPIs, comparative series, ranked services and principals, and recent anomalies. Service and principal routes preserve the same time window and drill into operations, callers, dependencies, instances, hourly activity cycles, and traces. Canvas topology provides interactive graphical inspection with an Edge Inspector drawer and tabular edge details.

React components are split into the shell/filter controls, reusable chart/card/table primitives, page-level data loaders, and an isolated `TopologyCanvas`. TanStack Query owns API caching/refetching; Recharts renders responsive SVG charts; the topology and user graph use HTML5 Canvas.

## Storage

ClickHouse (`http://127.0.0.1:8123`, database `tracescope`) is the sole persistence store, managed via `backend/clickhouse_migrations/001_initial.sql`:

- `traces`: sanitized transaction and span evidence with canonical observation fields (`principal_id`, `caller_service`, `target_service`, `operation_key`, `auth_result`, `auth_evidence`), monotonic microsecond row IDs, and `ReplacingMergeTree` engine.
- `ingest_batches`: batch tracking for transaction-atomic replay deduplication (`X-Batch-Id`).
- `services`, `accounts`, `principals`: entity inventory and first/last-seen metadata.
- `metric_buckets`: 1-minute (`60s`) and 5-minute (`300s`) rollups with exact p50, p95, and p99 percentiles.
- `service_edges`, `principal_service_edges`: time-bucketed confirmed or inferred directed relationships.
- `baselines`: rolling median and MAD baselines partitioned by hour-of-day and day-of-week.
- `anomalies`, `anomaly_occurrences`: detected observability incidents, explainability cards, and recurrence tracking.
- `principal_profiles`, `principal_relationships`, `principal_change_events`, `security_incidents`: User Intelligence behavioral profiles, change detection events, and bounded security incidents with family score caps.
- `agent_stats_latest`, `agent_stats_history`: Oldkernel Agent Statistics Protocol v1 health samples.
- `checkpoints`, `jobs`, `schema_migrations`: worker checkpoints, job execution history, and migration versions.

The repository layer connects via `clickhouse_connect` using a lightweight compatibility adapter in `backend/app/repositories/db_context.py` that handles parameter binding, row mapping, and dialect translation.

## API

Primary REST API endpoints served on port 30102:
- System health & readiness: `GET /api/v1/health`, `GET /livez`, `GET /readyz`
- Estate overview: `GET /api/v1/overview`
- Service inventory & details: `GET /api/v1/services`, `GET /api/v1/services/{service}`
- Principal behavioral explorer: `GET /api/v1/principals`, `GET /api/v1/principals/{principal}`
- Topology: `GET /api/v1/topology`, `GET /api/v1/topology/service/{service}`
- Anomalies & Incidents: `GET /api/v1/anomalies`, `GET /api/v1/anomalies/{id}`, `PATCH /api/v1/anomalies/{id}`, `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}`
- Traces: `GET /api/v1/traces`, `GET /api/v1/traces/{trace_id}`
- Blast radius traversal: `GET /api/v1/blast-radius/{service}`
- User Intelligence: `GET /api/v1/users`, `GET /api/v1/user-changes`, `POST /api/v1/user-changes/{id}/review`, `GET /api/v1/user-graph`, `GET /api/v1/user-analytics`
- Agent statistics: `POST /api/agent/stats`, `GET /api/agent/stats`, `GET /api/agent/stats/{node}`, `GET /api/agent/stats/{node}/history`, `DELETE /api/agent/stats/{node}`
- Ingestion: `POST /api/v1/ingest`, `POST /api/v1/ingest/traces`, `POST /api/ingest`, `POST /v1/traces`, `GET /api/v1/ingestion/status`
- Legacy dashboard compatibility: `/api/v1/dashboard/summary`, `/api/v1/dashboard/series`, `/api/v1/dashboard/rankings`, `/api/v1/dashboard/heatmap`, `/api/v1/accounts`, `/api/v1/events`

## Ingestion and jobs

The importer streams JSON arrays, Elasticsearch `hits.hits`, bulk-style NDJSON, and one-object-per-line NDJSON. Ingestion endpoints also accept OTLP JSON (`/v1/traces`) and NetworkTracing old-kernel envelopes (`{"node":"host","events":[...]}`). HTTP Basic authorization and namespaced WSSE `UsernameToken` credentials are sanitized in memory only: authenticated usernames are extracted while raw passwords, nonces, and secrets are discarded before storage, logging, or hashing. Unauthenticated transactions safely default to `unknown`. Payloads support automatic gzip decompression (`Content-Encoding: gzip` or magic bytes) and enforce transaction-atomic replay deduplication via `X-Batch-Id`.

All HTTP ingestion paths utilize a dedicated high-TPS coalescing writer (`backend/app/services/ingest_writer.py`) that coalesces incoming requests arriving within 5 ms up to 50,000 records into batched ClickHouse INSERTs, backed by a 256-request bounded queue. Saturated admission returns HTTP 429 with `Retry-After: 1`, while durable commits write directly to ClickHouse. The background worker (`backend/worker.py`) executes on a 60-second cadence, computing rollups (`metric_buckets`), service and principal edges, rolling baselines, and detector evaluations without blocking request ingestion.

## Baselines and anomaly rules

For each current entity bucket, rollups compute exact p50, p95, and p99 percentiles from raw samples in complete 60s and 300s windows. Rolling medians and Median Absolute Deviation (MAD) baselines are computed across matching minute-of-week and hour-of-day slots. Numeric traffic and latency detectors trigger when deviations exceed median plus/minus `max(3 × 1.4826 × MAD, absolute_floor)`.

Error, auth-denial, and slow rates use robust proportion comparisons. Novel identity, service relationship, and dependency edges compare first-seen timestamps against the historical baseline cutoff and require minimum sample counts. User Intelligence and behavioral engines monitor identity fanout, account switching, off-hours access, dormant reactivation, and IP-user novel associations, grouping related deviations into bounded security incidents. Recurrences share an entity/type fingerprint. See `docs/ANOMALIES.md` for detector-specific thresholds.

## Topology evidence and rendering

Confirmed edges require a child client span whose parent transaction/span resolves to a different service in the same trace, or a child server record with an explicit peer service and valid parent evidence. Shared trace IDs alone never create an edge. Inferred edges require a time-valid service/address mapping or an explicit destination service without parent linkage and are dashed. Account relationships are a separate view; usernames never identify callers. Unknown callers remain `Unknown caller`.

The API returns grouped nodes by default, with service nodes revealed by group/module expansion and neighborhood selection. The Canvas stores stable coordinates by node ID, runs layout only when graph membership changes, draws via `requestAnimationFrame` with DPR scaling, uses a grid spatial index for hit tests, and keeps selection/positions across refreshes. Traffic width uses a bounded square-root scale; color maps to selected health metric. The edge table provides the keyboard-accessible equivalent.

## Assumptions and limitations

The current event model treats transaction documents and server spans marked `span.kind=server` as server work; malformed or ambiguous span kinds are not counted as inbound RPS. Inferred topology depends on explicit destination-service fields until an authoritative mapping feed is provided. ClickHouse is the primary persistence engine, providing high-throughput columnar analytics and bounded disk retention. Exact percentiles are computed directly from raw trace samples in complete rollup windows, eliminating the quantile distortion of fixed logarithmic histograms. Browser graph performance depends on grouping; rendering all 300 nodes and all edges simultaneously is intentionally not the default.
