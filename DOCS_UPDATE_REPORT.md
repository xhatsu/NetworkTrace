# Documentation Update Report (`DOCS_UPDATE_REPORT.md`)

This report documents the factual updates made to the 9 project Markdown files in accordance with `TASK_DOCS_UPDATE.md`. Every change was derived from actual codebase inspection across backend API routers, models, services, repositories, ClickHouse migrations, Kubernetes manifests, Helm values, and frontend configurations.

---

## 1. Per-File Changes & Source Evidence

### 1. `deploy/helm/tracescope/README.md`
- **What was stale:**
  - Described "Full Distributed Mode" as the default deployment mode, when `values.yaml` defaults to the 3-Tier Consolidated Mode (`ui.enabled: false`, `agentStats.enabled: false`).
  - Stated `clickhouse.persistence.size: 50Gi`, whereas `values.yaml` sets `5Gi`.
  - Stated `ingress.host: tracescope.local`, whereas `values.yaml` specifies `trace.n2d.id.vn`.
  - Lacked references to the active hub port `:30102` and ingest port `:30103`.
- **What was changed:**
  - Clarified that the default deployment mode is the Consolidated 3-Tier Mode (merging UI and Agent Stats into the Storage/App API pod).
  - Synchronized the configuration reference table to reflect `5Gi` persistence size, `false` defaults for `agentStats.enabled` and `ui.enabled`, and `trace.n2d.id.vn` for Ingress.
  - Added port references (:30102 for API/UI, :30103 for Ingestion).
- **Source Evidence:**
  - `deploy/helm/tracescope/values.yaml:28`: `size: 5Gi`
  - `deploy/helm/tracescope/values.yaml:103`: `agentStats: enabled: false`
  - `deploy/helm/tracescope/values.yaml:129`: `ui: enabled: false`
  - `deploy/helm/tracescope/values.yaml:173`: `host: "trace.n2d.id.vn"`

---

### 2. `deploy/k8s/README.md`
- **What was stale:**
  - Listed ClickHouse image as `clickhouse/clickhouse-server:24.3-alpine`, whereas the manifest uses `clickhouse/clickhouse-server:24.8`.
  - Listed app StatefulSet workload as `tracescope-storage`, whereas the manifest defines `tracescope-app` (pod `tracescope-app-0`).
  - Listed `37-storage-service.yaml` as for "storage pods", whereas it defines headless discovery for `tracescope-app`.
- **What was changed:**
  - Updated workload table to specify `clickhouse/clickhouse-server:24.8` and `tracescope-app`.
  - Added explicit container and service ports (`:30102` for API/UI, `:30103` for Ingest).
  - Clarified manifest descriptions for `25-clickhouse-statefulset.yaml`, `30-storage-statefulset.yaml`, and `37-storage-service.yaml`.
- **Source Evidence:**
  - `deploy/k8s/25-clickhouse-statefulset.yaml:40`: `image: clickhouse/clickhouse-server:24.8`
  - `deploy/k8s/30-storage-statefulset.yaml:6`: `name: tracescope-app`
  - `deploy/k8s/31-api-service.yaml:19`: `port: 30102`
  - `deploy/k8s/33-ingest-service.yaml:19`: `port: 30103`
  - `deploy/k8s/37-storage-service.yaml:5`: `name: tracescope-app`

---

### 3. `docs/ANOMALIES.md`
- **What was stale:**
  - Stated latency regression was evaluated via "Merged-histogram p95 vs robust baseline", whereas TraceScope rollups compute exact p50/p95/p99 percentiles from raw trace samples in complete windows.
  - Omitted several active detectors implemented in `anomaly_detection.py` and `behavioral_engine.py` (e.g. user novel source IP `user_new_source_ip`, novel user on IP `ip_new_user`, and behavioral change scoring).
  - Listed lifecycle states as "open, acknowledged, resolved, or suppressed" without documenting the 7-question explainability cards or bounded security incident constraints.
- **What was changed:**
  - Updated the detector table to show exact p95 latency evaluation and current guardrails.
  - Added user + IP behavioral detectors (`user_new_source_ip`, `ip_new_user`) and behavioral shifts.
  - Documented bounded security incidents (15m window, 30m idle close, 24h lifetime, family score caps) and explainability cards.
- **Source Evidence:**
  - `backend/app/services/aggregation.py:107-133`: exact `quantiles(durations, n=100)` computation for p50, p95, p99
  - `backend/app/services/anomaly_detection.py:77-180`: Detectors 1-4 guardrails (`traffic_spike`, `traffic_drop`, `latency`, `error_rate`)
  - `backend/app/services/anomaly_detection.py:195-260`: Detectors 5, 6, 8 (`new_service_edge`, `new_principal_edge`, `unusual_time`)
  - `backend/app/services/anomaly_detection.py:311-360`: User + IP detectors (`user_new_source_ip`, `ip_new_user`)
  - `backend/app/services/behavioral_engine.py:27-33`: Family caps (origin 35, access 40, activity 35, identity mapping 30, auth 45)

---

### 4. `docs/BENCHMARK.md`
- **What was stale:**
  - Command invoked `--db data/benchmark-2m.db`, which was a legacy SQLite file purged during ClickHouse cutover.
  - Stated disk footprint was measured as "SQLite size is the main database file immediately after analysis".
  - Stated "SQLite permits one writer" and described WAL mode with busy timeout.
  - Claimed 48-bucket logarithmic histogram traded exact tail quantiles.
- **What was changed:**
  - Updated command to `python -m backend.benchmark --events 2000000 --services 320`.
  - Documented that disk footprint is queried from ClickHouse `system.tables` (`clickhouse_bytes_on_disk`).
  - Documented ClickHouse persistence with asynchronous batched inserts via `backend/app/services/ingest_writer.py`.
  - Noted that exact percentiles are computed directly from raw trace samples in complete rollup windows.
- **Source Evidence:**
  - `backend/benchmark.py:25`: `parser.add_argument("--db",type=Path,default=Path("data/benchmark-2m.db"))`
  - `backend/benchmark.py:32`: `"clickhouse_bytes_on_disk":int(repo.connect().execute("SELECT sum(bytes_on_disk) FROM system.tables WHERE database=currentDatabase()").fetchone()[0])`
  - `backend/app/services/aggregation.py:112-133`: exact percentile derivation

---

### 5. `docs/DESIGN.md`
- **What was stale:**
  - Stated UI had "four routes: Overview, Services, Accounts, Topology, and Anomalies" (omitting Traces, Principals, User Intelligence, and Agent Fleet).
  - Described persistence as SQLite in WAL mode with `BEGIN IMMEDIATE` and `SQLiteRepository`.
  - Described fixed logarithmic latency histograms.
  - Stated "SQLite is appropriate for this single-node evaluation...".
- **What was changed:**
  - Updated Product Structure to list all current routes: Overview (`/`), Topology (`/topology`), Anomalies (`/anomalies`), Services (`/services`), Principals (`/principals`), Traces (`/traces`), User Intelligence (`/users`, `/user-changes`, `/user-graph`, `/user-analytics`), and Agent Fleet (`/agent-stats`, `/agent-stats/:node`).
  - Rewrote Storage section to document ClickHouse (`127.0.0.1:8123`, `tracescope`), `ReplacingMergeTree` schema, tables (`traces`, `metric_buckets`, etc.), and DB-API adapter in `backend/app/repositories/db_context.py`.
  - Updated API section with current REST surface on `:30102`.
  - Updated Ingestion section to document high-TPS coalescing writer (`ingest_writer.py`), gzip decompression, WSSE/Basic auth sanitization, and 60-second worker loop.
  - Updated Assumptions to document ClickHouse as primary store and exact percentiles.
- **Source Evidence:**
  - `frontend/src/App.tsx:32-39`: all mounted routes
  - `backend/clickhouse_migrations/001_initial.sql:1-663`: ClickHouse schema
  - `backend/app/repositories/db_context.py:15-180`: ClickHouse connection and DB-API adapter
  - `backend/app/services/ingest_writer.py:1-240`: High-TPS coalescing writer

---

### 6. `bootstrap/README.md`
- **What was stale:**
  - Contained generic port references without explicitly confirming the legacy port `:31115` status.
- **What was changed:**
  - Explicitly stated active hub port `:30102` for telemetry ingestion and dashboard.
  - Confirmed legacy port `:31115` is obsolete and unused.
- **Source Evidence:**
  - `bootstrap/nt-bootstrap.py:35`: `HUB_PORT = int(os.environ.get("HUB_PORT", "30102"))`
  - `run_server.sh:17-18`: binds dashboard to `:30102`

---

### 7. `README.md`
- **What was stale:**
  - Kubernetes deployment section stated: "A single storage-owner StatefulSet is the only pod that mounts SQLite; edge pods use an authenticated internal API instead of sharing WAL files across nodes."
  - Production rollout gaps listed: "PostgreSQL/ClickHouse-class repository implementation...".
  - Omitted explicit legacy notice for port `:31115`.
- **What was changed:**
  - Updated Kubernetes deployment summary to describe `tracescope-clickhouse`, `tracescope-app` (FastAPI + UI + worker), and `tracescope-ingest` (HPA 3–12).
  - Updated rollout gaps to remove the completed ClickHouse migration and focus on multi-node clustering/backups.
  - Explicitly documented that port `:31115` is obsolete and unused.
- **Source Evidence:**
  - `backend/config.py:17-24`: ClickHouse configuration knobs
  - `deploy/k8s/25-clickhouse-statefulset.yaml`: ClickHouse StatefulSet
  - `deploy/k8s/30-storage-statefulset.yaml`: App StatefulSet
  - `deploy/k8s/32-ingest-deployment.yaml`: Ingest Deployment

---

### 8. `STATE.md`
- **What was stale:**
  - Contained duplicated sections (Sections 3-5 repeated as 6-8).
  - Cited manifest validation as "passed with 24 documents", whereas actual manifest validation output is 16 documents.
  - Referenced `clickhouse/clickhouse-server:24.3-alpine`, whereas `24.8` is used.
  - Did not explicitly characterize the active worktree state where SQLite migrations were removed and ClickHouse refactoring is in flight.
- **What was changed:**
  - Deduplicated sections into a clean 5-section layout.
  - Described the exact in-flight worktree state (removal of SQLite migrations, ClickHouse as sole persistence layer, role isolation via `application.py`).
  - Corrected manifest count to 16 documents and ClickHouse image to `24.8`.
- **Source Evidence:**
  - `deploy/k8s/validate_manifests.py:28-34`: 16 documents verified
  - `deploy/k8s/25-clickhouse-statefulset.yaml:40`: `clickhouse/clickhouse-server:24.8`
  - `backend/app/application.py:63-66`: role-aware app factory (`ROLE_ALL`, `ROLE_INGEST`, `ROLE_AGENT_STATS`)

---

### 9. `AGENTS.md`
- **What was stale:**
  - Contained duplicate sections (Sections 5-8 repeated).
  - Line 41 referenced "sent only after durable SQLite commit".
  - Referenced `012_ingest_batch_dedup.sql` as a separate migration file, whereas migrations are consolidated in `backend/clickhouse_migrations/001_initial.sql`.
  - Manifest validation mentioned 24 documents in one section.
- **What was changed:**
  - Corrected SQLite commit reference to ClickHouse commit.
  - Clarified that `ingest_batches` is defined in `backend/clickhouse_migrations/001_initial.sql`.
  - Cleaned up duplicated sections and synchronized manifest document count to 16.
- **Source Evidence:**
  - `backend/app/services/ingest_writer.py:133-145`: direct ClickHouse batch commits
  - `backend/clickhouse_migrations/001_initial.sql:63-71`: `ingest_batches` table definition

---

## 2. Verification Gate Outputs

### Gate 1: Fresh `ls -la` of All 9 Files
```text
-rw-r--r-- 1 ubuntu ubuntu 32179 Sep 12 07:13 AGENTS.md
-rw-r--r-- 1 ubuntu ubuntu  5195 Sep 12 07:13 README.md
-rw-r--r-- 1 ubuntu ubuntu 34347 Sep 12 07:13 STATE.md
-rw-rw-r-- 1 ubuntu ubuntu  3041 Sep 12 07:13 bootstrap/README.md
-rw-rw-r-- 1 ubuntu ubuntu  3404 Sep 12 07:12 deploy/helm/tracescope/README.md
-rw-rw-r-- 1 ubuntu ubuntu  4590 Sep 12 07:12 deploy/k8s/README.md
-rw-r--r-- 1 ubuntu ubuntu  2497 Sep 12 07:12 docs/ANOMALIES.md
-rw-r--r-- 1 ubuntu ubuntu  2278 Sep 12 07:12 docs/BENCHMARK.md
-rw-r--r-- 1 ubuntu ubuntu  8316 Sep 12 07:12 docs/DESIGN.md
```

### Gate 2: Grep Verification for Port `31115`
Command executed:
```sh
grep -rn "31115" AGENTS.md README.md STATE.md docs/ deploy/ bootstrap/
```
Output:
```text
AGENTS.md:1:> **Port migration:** The active hub is OTelTrace on `0.0.0.0:30102`. The former NetworkTracing hub on `:31115` is legacy and is not used.
README.md:74:The lifecycle script binds to `0.0.0.0:30102` and automatically uses `.venv/bin/python` when present. Override `OTEL_HOST` when a narrower bind is required. Set `OTEL_API_KEY` to require `X-API-Key` on ingestion and lifecycle mutations. The legacy port `:31115` is obsolete and unused.
STATE.md:1:> **Port migration:** The active hub is OTelTrace on `0.0.0.0:30102`. The former NetworkTracing hub on `:31115` is legacy and is not used.
bootstrap/README.md:9:- **Dynamic Endpoint Target**: The bootstrap script automatically downloads from port 30105 and targets the active hub at port 30102 (the legacy port `:31115` is obsolete and unused).
```
*Result:* All 4 occurrences explicitly designate port `31115` as legacy, obsolete, and unused.

### Gate 3: Three Spot-Check Facts with Source Evidence
1. **ClickHouse Disk Footprint Measurement in Benchmark**:
   - Corrected fact: Benchmark reads ClickHouse disk usage via `system.tables` (`clickhouse_bytes_on_disk`).
   - Source: `backend/benchmark.py:32`
     ```python
     "clickhouse_bytes_on_disk":int(repo.connect().execute("SELECT sum(bytes_on_disk) FROM system.tables WHERE database=currentDatabase()").fetchone()[0])
     ```
2. **ClickHouse Server Container Tag**:
   - Corrected fact: StatefulSet and Helm chart use upstream `clickhouse/clickhouse-server:24.8`.
   - Source: `deploy/k8s/25-clickhouse-statefulset.yaml:40`
     ```yaml
     image: clickhouse/clickhouse-server:24.8
     ```
   - Source: `deploy/helm/tracescope/values.yaml:23`
     ```yaml
     tag: "24.8"
     ```
3. **Helm Default Consolidated 3-Tier Topology**:
   - Corrected fact: Default values disable standalone UI and agent-stats Deployments, consolidating them into the API pod with 5Gi ClickHouse storage.
   - Source: `deploy/helm/tracescope/values.yaml:28,103,129,173`
     ```yaml
     clickhouse.persistence.size: 5Gi
     agentStats.enabled: false
     ui.enabled: false
     ingress.host: "trace.n2d.id.vn"
     ```

### Gate 4: `git status --porcelain | head -60`
Verbatim output:
```text
 M AGENTS.md
 M Dockerfile
 M README.md
 M STATE.md
 M backend/agent_stats_main.py
 M backend/analytics.py
 M backend/app/api/__init__.py
 M backend/app/api/agent_stats.py
 M backend/app/api/anomalies.py
 M backend/app/api/blast_radius.py
 M backend/app/api/ingest.py
 M backend/app/api/internal_storage.py
 M backend/app/api/overview.py
 M backend/app/api/principals.py
 M backend/app/api/reference_compat.py
 M backend/app/api/services.py
 M backend/app/api/topology.py
 M backend/app/api/traces.py
 M backend/app/api/users.py
 M backend/app/application.py
 M backend/app/models/__init__.py
 M backend/app/models/aggregate.py
 M backend/app/models/anomaly.py
 M backend/app/models/baseline.py
 M backend/app/models/incident.py
 M backend/app/models/topology.py
 M backend/app/models/trace.py
 M backend/app/repositories/__init__.py
 M backend/app/repositories/agent_stats_repository.py
 M backend/app/repositories/aggregate_repository.py
 M backend/app/repositories/anomaly_repository.py
 M backend/app/repositories/baseline_repository.py
 M backend/app/repositories/clickhouse_migrator.py
 M backend/app/repositories/db_context.py
 M backend/app/repositories/ingest_batch_repository.py
 M backend/app/repositories/principal_repository.py
 M backend/app/repositories/topology_repository.py
 M backend/app/repositories/trace_repository.py
 M backend/app/repositories/user_repository.py
 M backend/app/services/__init__.py
 M backend/app/services/aggregation.py
 M backend/app/services/anomaly_detection.py
 M backend/app/services/apm_parser.py
 M backend/app/services/baseline.py
 M backend/app/services/behavioral_engine.py
 M backend/app/services/blast_radius.py
 M backend/app/services/ingest_writer.py
 M backend/app/services/normalization.py
 M backend/app/services/otlp_parser.py
 M backend/app/services/principal_analytics.py
 M backend/app/services/principal_baseline.py
 M backend/app/services/principal_change_detector.py
 M backend/app/services/principal_extractor.py
 M backend/app/services/principal_graph.py
 M backend/app/services/principal_profile.py
 M backend/app/services/principal_relationships.py
 M backend/app/services/root_cause.py
 M backend/app/services/storage_owner_client.py
 M backend/app/services/wsse.py
 M backend/benchmark.py
```
