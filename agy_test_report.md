I HAVE FOLLOW THE RULE xHatsu DEFINED FOR ME BY DEFAULT

As tracked in [STATE.md](file:///home/ubuntu/Viettel/OtelTrace/STATE.md) (and documented in [AGENTS.md](file:///home/ubuntu/Viettel/OtelTrace/AGENTS.md)), here is the read-only inspection report for the target repository [OtelTrace (TraceScope)](file:///home/ubuntu/Viettel/OtelTrace).

---

# Repository Inspection Report: TraceScope (`OtelTrace`)

## 1. Top-Level Structure

The repository is organized into a modular full-stack observability architecture:

- [`backend/`](file:///home/ubuntu/Viettel/OtelTrace/backend): Core Python/FastAPI service and analytical processing pipeline.
  - [`backend/main.py`](file:///home/ubuntu/Viettel/OtelTrace/backend/main.py): Application entrypoint, FastAPI routing, and static asset serving.
  - [`backend/app/models/`](file:///home/ubuntu/Viettel/OtelTrace/backend/app/models): Pydantic domain models for traces, incident lifecycles, aggregates, baselines, and topology graphs.
  - [`backend/app/repositories/`](file:///home/ubuntu/Viettel/OtelTrace/backend/app/repositories): Data access layer providing dual-storage backends (ClickHouse and Elasticsearch), batch deduplication, and topology query resolvers.
  - [`backend/app/services/`](file:///home/ubuntu/Viettel/OtelTrace/backend/app/services): Analytical and statistical detection engine (normalization, 60s/300s rollups, MAD baseline calculation, anomaly detection, blast radius, and root-cause heuristics).
  - [`backend/clickhouse_migrations/`](file:///home/ubuntu/Viettel/OtelTrace/backend/clickhouse_migrations): Versioned ClickHouse SQL migrations (retention policies, schema definitions).
  - [`backend/cli.py`](file:///home/ubuntu/Viettel/OtelTrace/backend/cli.py): CLI commands for database migrations, synthetic demo seeding, Elasticsearch syncing, and maintenance.
- [`frontend/`](file:///home/ubuntu/Viettel/OtelTrace/frontend): Interactive web dashboard built with React 19, TypeScript, Vite, Tailwind CSS, TanStack Query, and Recharts.
  - [`frontend/src/pages/`](file:///home/ubuntu/Viettel/OtelTrace/frontend/src/pages): Views for Overview, Services, Principals, Service Topology, Anomalies, and Distributed Trace Waterfall views.
- [`deploy/`](file:///home/ubuntu/Viettel/OtelTrace/deploy): Production deployment manifests, including Kubernetes StatefulSets/Deployments ([`deploy/k8s`](file:///home/ubuntu/Viettel/OtelTrace/deploy/k8s)) and Helm chart configurations.
- [`docs/`](file:///home/ubuntu/Viettel/OtelTrace/docs): Technical specifications and documentation ([`docs/DESIGN.md`](file:///home/ubuntu/Viettel/OtelTrace/docs/DESIGN.md), [`docs/ANOMALIES.md`](file:///home/ubuntu/Viettel/OtelTrace/docs/ANOMALIES.md), [`docs/BENCHMARK.md`](file:///home/ubuntu/Viettel/OtelTrace/docs/BENCHMARK.md)).
- [`tests/`](file:///home/ubuntu/Viettel/OtelTrace/tests): Automated test suites for ingestion deduplication, normalization, anomaly detection, and interactive topology.
- [`scripts/`](file:///home/ubuntu/Viettel/OtelTrace/scripts), [`bootstrap/`](file:///home/ubuntu/Viettel/OtelTrace/bootstrap), [`data/`](file:///home/ubuntu/Viettel/OtelTrace/data): Ingestion helpers, demo data generators, and dataset fixtures.
- **Root Operations & Orchestration**:
  - [`run_server.sh`](file:///home/ubuntu/Viettel/OtelTrace/run_server.sh): Process supervisor controlling the API server and worker processes.
  - [`AGENTS.md`](file:///home/ubuntu/Viettel/OtelTrace/AGENTS.md) & [`STATE.md`](file:///home/ubuntu/Viettel/OtelTrace/STATE.md): Autonomous agent state tracking and project context records.

---

## 2. What the Project Appears to Do

**TraceScope** is an OpenTelemetry transaction analytics and behavioral observability platform engineered for large-scale distributed service architectures. Its primary functions include:

1. **Multi-Source Ingestion & Credential Sanitization**:
   - Ingests traces from Elasticsearch APM (JSON/NDJSON), standard OTLP JSON subsets, and legacy NetworkTracing capture envelopes.
   - Scrubs sensitive authorization headers, Basic credentials, and tokens in-memory prior to persistence or analytical hashing.
2. **High-Throughput Coalesced Persistence & Deduplication**:
   - Employs a bounded coalescing writer thread (`ingest_writer.py`) for batched commits into ClickHouse.
   - Enforces transaction-atomic deduplication using `X-Batch-Id` headers and an LRU-cached `ingest_batches` index.
3. **Continuous Statistical Aggregations**:
   - Computes rolling 1-minute and 5-minute metric windows capturing exact p50, p95, and p99 latency percentiles, error rates, RPS, and TPS across services, operations, and caller principals.
4. **Behavioral Anomaly Detection & User Intelligence**:
   - Profiles expected traffic patterns using rolling medians and Median Absolute Deviation (MAD) across matching minute-of-week and hour-of-day slots.
   - Detects traffic spikes/drops, latency shifts, error surges, novel dependency edges, and authentication anomalies.
   - Identifies blast radii and probable root causes for incident triage.
5. **Interactive Dependency & User Topology Graph**:
   - Visualizes directed graphs of callers, dependencies, and identities via an interactive web interface.

---

## 3. Potential Area Worth Reviewing

### Backend Dual-Storage Parity (ClickHouse vs. Elasticsearch)
In [`backend/app/repositories/interactive_topology_repository.py`](file:///home/ubuntu/Viettel/OtelTrace/backend/app/repositories/interactive_topology_repository.py#L621-L705):

- **Observation**:
  In the inverse projection methods (`principal_services` and `principal_service_apis`), the query implementation differs significantly based on the active backend:
  - When using **ClickHouse**, the repository queries `_records_with_changes("topology_principal_edges_5m", ...)`, returning full window delta comparisons (`new_nodes`, `disappeared_nodes`, baseline history status) and calculated anonymous summaries.
  - When using **Elasticsearch**, change tracking and history comparisons are hardcoded to empty stubs (`disappeared = []`, `history = False`), and `_anonymous_summary` returns `{}`.
- **Recommendation**:
  Review and align the Elasticsearch analytical search queries so that delta comparisons (identifying newly appeared or disappeared dependencies/APIs for a given principal across time windows) behave identically regardless of whether the cluster backend is ClickHouse or Elasticsearch.

---

*Note on secured edge case: Verified read-only execution constraints; no working tree files, logs, or system packages were modified or executed destructively during this inspection.*


---
agy exit code: 0
