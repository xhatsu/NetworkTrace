> **Port migration:** The active hub is OTelTrace on `0.0.0.0:30102`. The former NetworkTracing hub on `:31115` is legacy and is not used.

# TraceScope Context and State Management (AGENTS.md)

## 1. Project Overview
**TraceScope** is an OpenTelemetry transaction analytics and behavioral observability platform for large service estates.
- **Core Functionality**:
  - Ingests Elasticsearch APM JSON/NDJSON, canonical OTLP JSON subsets, and NetworkTracing old-kernel capture envelopes/events with tolerant optional-field handling.
  - Sanitizes Basic authentication in-memory (passwords and tokens scrubbed before storage/logging/hashing).
  - Analytical data model: `caller_service` -> `principal_name` -> `target_service` -> `operation` -> `status + latency`.
  - Computes 1-minute (`60s`) and 5-minute (`300s`) rollups with exact p50/p95/p99 percentiles.
  - Computes rolling medians and MAD (Median Absolute Deviation) baselines across matching minute-of-week and hour-of-day.
  - Detectors 1–8: Traffic spike, traffic drop, latency shift, error rate increase, new service relationship, new principal relationship, new operation, unusual execution time.
  - Incident blast-radius analysis (upstream callers, affected principals/operations) and deterministic root-cause heuristic origin.
  - Serves fast analytics dashboards via FastAPI and an interactive React/TypeScript frontend.
- **Root Directory**: `/home/ubuntu/Viettel/OtelTrace`
- **Current Database**: ClickHouse (active database `tracescope` on `127.0.0.1:8123`, managed via `backend/clickhouse_migrations/001_initial.sql`). SQLite database `data/tracescope.db` preserved for rollback safety.
- **Active Dashboard Port**: `0.0.0.0:30102` (lifecycle-script default and current listener).
- **NetworkTracing Hub Port**: `0.0.0.0:30102` (OTLP / Ingest Hub in `~/Viettel/NetworkTracing`).

---

## 2. Architecture & Components

### Backend (`backend/`)
- **API Server & Static Mount** (`backend/main.py`):
  - Framework: FastAPI with CORS middleware.
  - Serves built React SPA from `frontend/dist` at `/` and `/assets`.
  - Endpoints:
    - `GET /api/v1/health`: Health status and demo mode indicator.
    - `GET /api/v1/overview`: System health, KPIs (current RPS, error rate, p95 latency, active services/principals, anomaly counts), comparative series, and top rankings.
    - `GET /api/v1/services`, `GET /api/v1/services/{service}`: Service inventory, detailed health metrics, operations breakdown, callers, downstream dependencies, instances.
    - `GET /api/v1/principals`, `GET /api/v1/principals/{principal}`: Identity behavior explorer, target services, operations, callers, hourly activity profile.
    - `GET /api/v1/topology`: Directed service dependency graph with edge details (traffic, p95, error rate, top principals, top operations).
    - `GET /api/v1/anomalies`, `GET /api/v1/anomalies/{id}`, `PATCH /api/v1/anomalies/{id}`: Anomaly incident lifecycle management, explainability card data, probable root cause, blast radius.
    - `GET /api/v1/traces`, `GET /api/v1/traces/{trace_id}`: Distributed trace search & multi-tier span waterfall hierarchy.
    - `GET /api/v1/blast-radius/{service}`: Upstream caller graph traversal, affected principals & operations.
    - User Intelligence & Incidents:
      - `/api/v1/users` inventory/profile subresources, `/api/v1/user-changes`, `/api/v1/user-changes/{id}/review` (operator overrides with scope and expiry), `/api/v1/user-graph`, `/api/v1/user-analytics`.
      - Bounded Security Incidents: `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}` with capped family scores, 15m windows, 30m idle close, and 24h lifetime.
    - `POST /api/v1/ingest`, compatibility alias `POST /api/v1/ingest/traces`, and old-kernel shipper alias `POST /api/ingest`: bounded OTEL/ELK or NetworkTracing `{node, events[]}` ingestion with credential sanitization, automatic `Content-Encoding: gzip` / magic-byte decompression with HTTP 400 rejection on corrupted payloads, and transaction-atomic `X-Batch-Id` deduplication (HTTP 200 `{"ok": true, "duplicate": true}` on replay, zero duplicate database insertions). Concurrent uploads enter the bounded coalescing writer; saturation returns HTTP 429 plus `Retry-After: 1`, and HTTP 200 is sent only after durable SQLite commit.
    - **Ingest Batch Deduplication** (`backend/app/repositories/ingest_batch_repository.py`): Migration `012_ingest_batch_dedup.sql` defines `ingest_batches` table with in-memory LRU cache and automatic 7-day pruning.
    - **High-TPS Ingest Writer** (`backend/app/services/ingest_writer.py`): A single persistent WAL connection serializes SQLite writes, coalesces concurrent requests for up to 5 ms / 50,000 records into one transaction, bounds admission to 256 queued requests, commits trace rows and batch IDs atomically, exposes queue/commit counters through `GET /api/v1/ingestion/status`, and shuts down cleanly with the FastAPI lifespan. Per-request rollup launches were removed; the existing `tracescope-worker` performs analytics on its 60-second cadence.
    - **Agent Stats** (`backend/app/api/agent_stats.py`): Oldkernel Agent Statistics Protocol v1 receiver.
      - `POST /api/agent/stats`: Accept a 16 KiB-bounded agent health sample. Validates `schema_version=1`, `type=agent_stats`, required fields, bounded `status` enum (`ok`/`degraded`), and bounded `reasons` enum. Idempotent: duplicate `(node, instance_id, sequence)` returns HTTP 200 `{"accepted": false}`. Spec: `~/Viettel/NetworkTracing/oldkernel/AGENT-STATS-PROTOCOL.md`.
      - `GET /api/agent/stats[?node=<name>]`: Latest health sample per node (or specific node).
      - `GET /api/agent/stats/{node}[?instance_id=<id>]`: Node latest summary status, known instance list, and runtime metadata.
      - `GET /api/agent/stats/{node}/history[?limit=N&instance_id=<id>]`: Recent history samples for a node (optionally filtered by instance_id, default 120, max 2880 ≈ 24 h at 30-second interval) with flat metrics unwrapped for instant time-series plotting.
      - `DELETE /api/agent/stats/{node}[?instance_id=<id>]` & `DELETE /api/agent/stats/{node}/{instance_id}`: Delete a specific agent instance or an entire agent node and its historical telemetry records. Returns HTTP 200 on success, HTTP 404 if not found.
    - Legacy aliases: `/api/v1/accounts`, `/api/v1/dashboard/summary`, `/api/v1/dashboard/series`, `/api/v1/events`, `/api/v1/ingestion/status`.
- **Domain Models** (`backend/app/models/`):
  - `trace.py`: `NormalizedTrace` with canonical observation fields (`principal_id`, `environment`, `identity_source`, `auth_result`, `auth_evidence`, `caller_resolution_method`, `caller_confidence`, `operation_key`, `original_client_ip_trusted`, `dedup_key`).
  - `incident.py`: `Incident`, `OperatorOverride`.
  - `aggregate.py`: `MetricBucket`.
  - `baseline.py`: `BaselineMetric`.
  - `topology.py`: `ServiceEdge`, `PrincipalServiceEdge`, `TopologyNode`, `TopologyEdge`.
  - `anomaly.py`: `AnomalyEvent` (clean model without unobtained `instance` or dummy attributes), `AnomalyReason`.
- **Repository Layer** (`backend/app/repositories/`):
  - `db_context.py`: SQLite connection context with WAL mode and 5s busy timeout.
  - `trace_repository.py`: Normalized trace batch insert, query, and search.
  - `aggregate_repository.py`: Rollup storage, time-series query, KPI summaries.
  - `topology_repository.py`: Edge materialization, topology graph generation, caller/dependency traversal.
  - `baseline_repository.py`: Baseline storage and retrieval by hour-of-day/day-of-week.
  - `anomaly_repository.py`: Anomaly event querying, lifecycle patching (open, investigating, resolved, suppressed). Pruned unobtained attributes from responses.
  - `principal_repository.py`: Principal rankings and comprehensive behavioral profiling.
  - `user_repository.py`: User inventory, fingerprint profiles, timelines, explainable changes, graph, analytics, operator review actions, and incidents query.
  - `agent_stats_repository.py`: Agent health sample storage — upserts `agent_stats_latest` (one live row per node+instance), appends to `agent_stats_history` (idempotent via UNIQUE on `(node, instance_id, sequence)`), prunes history to 2880 rows/node, and provides atomic `delete_node` purging.
- **Analytics & Detection Services** (`backend/app/services/`):
  - `behavioral_engine.py`: Canonical identity normalization, detector readiness, multi-layer baselines, bounded incident lifecycle, capped family scoring (Origin cap 35, Access cap 40, Activity cap 35, Identity mapping cap 30, Authentication cap 45), 7-question explainability cards, and new behavioral/auth detectors (`OPERATION_MIX_SHIFT`, `CALLER_PRINCIPAL_SWITCH`, `TARGET_FANOUT_SURGE`, `SOURCE_FANOUT_SURGE`, `PRINCIPAL_RATE_SURGE`, `AUTH_FAILURE_BURST`, `FAILURE_THEN_SUCCESS`, `SOURCE_IDENTITY_FANOUT`, telemetry quality gates).
  - `normalization.py`: Normalizes OTel / ELK payloads, derives trusted IP / proxies, extracts WSSE usernames with case preservation, sets canonical `operation_key` (`Service/operation`), and maps decoupled `auth_result` / `auth_evidence`.
  - `aggregation.py`: Computes 60s and 300s rollups with exact p50/p95/p99 percentiles.
  - `baseline.py`: Computes rolling median and MAD across dimensions.
  - `anomaly_detection.py`: Detectors 1–8.
  - `blast_radius.py`: Recursive caller traversal and impact calculation.
  - `root_cause.py`: Probable origin heuristic.
  - `principal_extractor.py`, `principal_relationships.py`, `principal_profile.py`, `principal_baseline.py`, `principal_change_detector.py`, `principal_graph.py`, `principal_analytics.py`: incremental credential-behavior derivation from the existing sanitized `traces` table.
- **Maintenance & Migration Scripts** (`backend/scripts/`):
  - `rebuild_aggregates.py`: Recomputes all rollups, edges, baselines, and detects anomalies.
  - `import_json.py`: Imports NDJSON, JSON arrays, and Elasticsearch hits.
- **Lifecycle Script** (`run_server.sh`):
  - `./run_server.sh {start|stop|restart|status}` managing tmux sessions `tracescope-30102` and `tracescope-worker`.

### Frontend (`frontend/`)
- **Tech Stack**: React 19, Vite, TypeScript, Tailwind CSS, TanStack Query, Recharts, HTML5 Canvas.
- **Design System & Typography**: Moderately colorful, glanceable observability monitor design system.
  - Typography: 120% base font scaling (`html { font-size: 120%; }`), 13px Recharts axis ticks, 13px/12px HTML5 Canvas labels, and proportional arbitrary pixel text scaling (`text-[9px]` -> 11px, `text-[10px]` -> 12px, `text-[11px]` -> 13.5px, etc.).
  - Canvas: Deep purple-black container (`#12101b`), elevated panels (`#161424`), crisp card containers (`#1a172a`), with subtle ambient multi-accent glow (cyan + violet + amber).
  - Borders: Crisp, high-contrast borders `rgba(255, 255, 255, 0.14)` and `rgba(255, 255, 255, 0.12)`.
  - Multi-Accent Palette:
    - User Intelligence & Identity: Cyan / Sky (`#06b6d4`, `#22d3ee`, active pill `glow-cyan`).
    - Observability & Services: Sentry Violet / Indigo (`#8b5cf6`, `#6366f1`, active pill `glow-violet`).
    - Infrastructure & Fleet: Golden Amber (`#f59e0b`, `#fbbf24`, active pill `glow-amber`).
    - Performance & Signals: Sky Blue for Throughput/RPS, Emerald for TPS/Optimal Latency, Violet for p95, Rose for 5xx/Errors.
  - Multi-Color Visualizations: Multi-percentile AreaCharts (Rose p99, Amber p95, Mint p50), distinct `Cell` fills for account volumes, gradient rank bars in `RankTable`, 4-tier latency heatmap color ramp (<100ms emerald, 100-250ms cyan, 250-500ms amber, >500ms rose), and group-coded topology nodes and edge states.
- **Built Output**: `frontend/dist` served directly by FastAPI on port 30102.
- **Navigation & Pages**:
  - `Overview` (`/`): Estate health KPIs, comparative traffic & latency series, open anomalies list, top services & principals.
  - `Topology` (`/topology`): Interactive canvas graph with Edge Inspector drawer (showing top principals and top operations per edge).
  - `Anomalies` (`/anomalies`, `/anomalies/:id`): Incident list and Anomaly Detail with "WHAT CHANGED COMPARED WITH NORMAL?" explainability card, probable root cause, blast radius, and lifecycle action controls.
  - `Services` (`/services`, `/services/:name`): Service catalog, operation percentiles, caller graphs, instances.
  - `Principals` (`/principals`, `/principals/:name`): Identity behavior explorer, target services, operations, callers, and hourly activity profiles.
  - `Traces` (`/traces`, `/traces/:id`): Trace explorer with filters and multi-tier interactive waterfall visualization.
  - `User Intelligence`: `Users` (`/users`, `/users/:principal`), `User Changes` (`/user-changes`), `User Graph` (`/user-graph`), and `User Analytics` (`/user-analytics`). Existing pages retain their service-centric workflows and expose contextual user cross-links.
  - `Infrastructure`: `Agent Fleet` (`/agent-stats`) and `Agent Drilldown` (`/agent-stats/:node`) with interactive time-series dashboards (throughput kbps & ev/s, drop rates, pinned CPU core & RSS memory, queue backpressure, flow volume, and process limits).
  - Global Search in header: Search services, principals, or jump directly to trace waterfall by ID.

---

## 3. Rules & Operational Guidelines
- **Rule xHatsu**: Always start responses with `"I HAVE FOLLOW THE RULE xHatsu DEFINED FOR ME BY DEFAULT"`.
- **POSIX Shell**: Strictly POSIX `/bin/sh` compliant. Never use bashisms (`[[ ]]`, `local`, `declare`, `array[i]`, `&>`, etc.).
- **Timers**: Set a schedule timer before executing fast commands to detect/prevent freezing.
- **Kubernetes**: NEVER execute any `kubectl` command.
- **Testing**: Always test API endpoints and scripts to confirm functionality across cases.
- **State Management**: Keep `AGENTS.md` and `STATE.md` updated with system state, access instructions, and guides.

---

## 4. Current State & Verification
- **Test Suite**: 74/74 tests passed in an isolated temporary-database harness; production data is never mutated by tests:
  - Unit & domain tests in `tests/test_analytics.py`, `tests/test_api.py`, `tests/test_ingestion.py`.
  - Ingestion batch deduplication and gzip decompression tests in `tests/test_batch_dedup_and_gzip.py`.
  - High-concurrency request coalescing, atomic concurrent deduplication, bounded-queue backpressure, and retryable HTTP 429 tests in `tests/test_ingest_writer.py`.
  - Comprehensive behavioral API tests in `tests/test_behavioral_api.py`.
  - Canonical identity normalization, realm removal, multi-layer baselines, detector readiness, capped family scoring, and bounded incident lifetime tests in `tests/test_identity_normalization_and_incidents.py`.
  - Dedicated IP anomaly and novel user on host tests in `tests/test_user_ip_anomalies.py`.
  - Reference compatibility and WSSE ingestion tests in `tests/test_reference_compat.py` and `tests/test_wsse_ingestion.py`.
- **End-to-End Curl & JS Safety Test Suite**: 42/42 tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - Tested all 17 SPA routes (including `/agent-stats` and `/agent-stats/:node`) with HTTP 200 and valid HTML shell bundle delivery.
  - Tested 25 backing APIs against frontend TypeScript contracts via `backend/scripts/validate_js_safety.py`.
  - 0 JavaScript crash risks identified (zero undefined `toFixed`, `length`, or `map` vulnerabilities).
- **Frontend Lint/Build**: Passed (`tsc --noEmit -p tsconfig.app.json` and `tsc -b && vite build`).
  - Added defensive optional chaining and fallback arrays across `Overview.tsx`, `Services.tsx`, `Principals.tsx`, `Anomalies.tsx`, and `Traces.tsx`.
  - Harmonized `backend/app/api/services.py` and `backend/app/api/principals.py` to supply full operational and hourly profiles.
- **Playwright Real Browser E2E Suite**: 15/15 pages passed (`python3 backend/scripts/test_pages_playwright.py`).
  - Headless Chromium navigated to all 15 existing and User Intelligence SPA routes.
  - Full React hydration, query resolution, and visual canvas/chart rendering verified.
  - 0 unhandled `pageerror` exceptions, 0 React render crash boundaries, and 0 console error failures.
- **Port 30102 Status**: Online and healthy, listening on all interfaces (`http://0.0.0.0:30102`).
- **High-TPS Hub Deployment (2026-09-11)**: Bounded/coalescing writer is active on `:30102`; live ingestion status reported `writer_alive=true`, queue `0/256`, successful durable commits, zero failed requests, and atomic duplicate replay. Full isolated test suite passed 74/74 and the live curl/JavaScript contract suite passed 42/42 after deployment.
- **Database Status & Ingested Sample Abnormal Dataset**: Active SQLite database in WAL mode at `data/tracescope.db` (`quick_check` passes `ok`). Ingested 50,000 traces from `/home/ubuntu/Viettel/Data/sample_abnormal_traces_50k.jsonl.gz` with ground-truth anomalies. Computed 46,307 1m buckets, 36,562 5m buckets, 33 service edges, 232 principal edges, 3,860 rolling baselines (median & MAD), 1,654 core observability anomalies (Detectors 1-8), 3,113 user behavioral change events across 7 types, and 41 bounded security incidents with family-capped scores.
- **Data Correctness**: Anomaly APIs filter and investigate by telemetry observation windows, expose measured bucket/baseline sample counts and MAD ranges, return matching trace evidence, and include metadata-associated principals. User scores count distinct evidence types once and explicitly distinguish learning from established baselines.
- **WSSE UsernameToken Attribution**: Active `/api/ingest` and `/v1/traces` ingestion safely normalize namespaced WSSE usernames and store only `principal_name` with `auth_scheme=wsse`. OASIS 2004 plus legacy 2002/07, 2002/12, and 2003/06 `secext` namespaces are supported; malformed, unnamespaced, DTD/entity, oversized, and invalid usernames remain anonymous. SOAP bodies, passwords/digests, and nonces are never persisted or logged. Verified live on `:30102` with HTTP 200 and trace/API/database evidence.
- **Java WSSE OTLP Fixture**: `/tmp/wsse-java-service` accepts bounded SOAP on
  `0.0.0.0:18080` and exports real spans to this active hub's `/v1/traces`.
  No OpenTelemetry SDK dependencies are installed, so it is explicitly a
  minimal/manual OTLP HTTP JSON exporter. It sends only sanitized
  `wsse.username` plus non-sensitive service/HTTP metadata; the hub strips the
  source identity attribute after deriving `principal_name` and
  `auth_scheme=wsse`.
- **PCAP Authentication & Username Inspection Script**: Tested and verified ([`backend/scripts/inspect_pcap_auth.py`](file:///home/ubuntu/Viettel/OtelTrace/backend/scripts/inspect_pcap_auth.py) and copied to [`~/Viettel/Data/inspect_pcap_auth.py`](file:///home/ubuntu/Viettel/Data/inspect_pcap_auth.py)).
  - Zero third-party dependencies (pure standard Python `struct`, `base64`, `re`, `gzip`).
  - Supports standard pcap, nanosecond pcap, gzip-compressed pcap, Linux cooked v1/v2, Ethernet.
  - Extracts and isolates usernames from HTTP Basic Auth (`Authorization: Basic <base64>`), WSSE SOAP XML (`<wsse:Username>...</wsse:Username>`), and WSSE HTTP Headers (`X-WSSE`).
  - Verified on real production captures: `Data/tcpdump_10.240.147.247.pcap` (218 WSSE tokens, user `product`), and `NetworkTracing/pcap/tcpdump_10.240.147.249.pcap` (149,263 packets, 12,593 auth occurrences, 80 distinct usernames including `cm2.0`, `sale`, `vtp`, `myViettel`, `pm_mini_app`, `chatbot`).
- **Redesigned Data Generator & Modular Anomaly / User Behavior Generator (`~/Viettel/Data` & `backend/scripts`)**:
  - `anomalies.py`: Modular object-oriented Anomaly & User Behavioral Change Generator defining scenarios aligned with TraceScope's 8 core detectors and User Intelligence behavioral engine (`principal_relationships.py`):
    - **Core Observability Detectors**:
      1. `traffic_spike`: 3.5x RPS surge on `order-service` (10.0h - 11.5h).
      2. `traffic_drop`: 85% drop on `notification-service` (15.5h - 16.5h).
      3. `latency_blowout`: 8.0x tail latency blowout on `payment-service` `chargeCard` (13.0h - 14.5h).
      4. `cascading_failure`: Root 5xx outage on `billing-service` propagating 502 to callers (19.0h - 20.5h).
      5. `new_service_edge`: Architectural drift with rogue dependency `customer-service` -> `payment-service` (15.0h - 24.0h).
      6. `new_operation`: Novel endpoint `AdminService/debugDump` on `admin-service` (16.0h - 24.0h).
    - **User Intelligence Behavioral Changes (`principal_relationships.py` & `README.md`)**:
      7. `user_first_seen`: New identity `guest_checkout_partner` first observed after historical 75% baseline cutoff (18.5h - 24.0h) (`USERNAME_FIRST_SEEN`, score: 10).
      8. `user_new_caller`: Caller expansion with `vtp` arriving from unexpected caller `apex-inventory-service` (18.5h - 24.0h) (`NEW_CALLER`, score: 30).
      9. `user_new_source_ip`: Source IP expansion with `sale` connecting from anomalous foreign IP `185.220.101.5` (19.0h - 24.0h) (`NEW_SOURCE_IP`, score: 20).
      10. `user_new_target`: Target expansion with `chatbot` accessing sensitive target `apex-admin-service` (18.0h - 23.5h) (`NEW_TARGET`, score: 25).
      11. `user_new_operation`: Operation expansion with `pm_mini_app` executing novel endpoint `OrderService/cancelReservation` (18.5h - 24.0h) (`NEW_OPERATION`, score: 15).
      12. `user_unusual_time`: Off-hours interactive access by human identity `sale` at 02:00-04:30 UTC (`UNUSUAL_TIME`, score: 10).
      13. `user_dormant_reactivation`: Account `cm2.0` silent for 19 hours, then bursting at 20.0h-23.5h (`DORMANT_REACTIVATED`, score: 40).
      14. `credential_abuse`: Identity `myViettel` connecting from foreign IP `185.220.101.5` via `customer-service` (21.0h - 24.0h).
  - `generate_traces.py`: High-performance generator integrating authentic production PCAP identities, 9 multi-tier enterprise services, diurnal traffic curves, W3C TraceContext causality, and strict 75/25 historical bootstrap partitioning. Supports `--days <N>` (e.g. `--days 15`), `--anomalies <all|none|list>`, `--list-anomalies`, and outputs detailed ground-truth injection summaries.
  - `send_traces.py`: High-performance streaming ingestion tool supporting HTTP batch POSTing (`--mode http`) and fast direct SQLite batch writes (`--mode direct`, auto-tuned 5,000 batch size).
- **15-Day 2,000,000 Data Point Dataset Generated**:
  - File: `/home/ubuntu/Viettel/Data/otel_elk_traces_2m.jsonl.gz` (495.27 MB).
  - Preview: `/home/ubuntu/Viettel/Data/otel_elk_sample_preview.json` (100 sample records).
  - Timespan: Exactly 15 days (360.0 hours) from `2026-08-24 07:29:10 UTC` to `2026-09-08 07:29:12 UTC` (ending today right now).
  - Injected Ground Truth: 5,366 traffic spikes, 429 traffic drops, 772 tail latency blowouts, 1,737 cascading 5xx failures, 3,369 architectural drift calls, 769 novel operation calls, and 353,049 user behavioral change transactions across all 8 User Intelligence scenarios.
- **Oldkernel Agent Package & Bootstrap Server (Port 30105)**:
  - **Canonical Source of Truth**: The real `oldkernel` code (C++ sniffer, shipper, supervisor, scripts, Makefiles) canonically resides in `~/Viettel/NetworkTracing/oldkernel`. The deployment files reside in `~/Viettel/NetworkTracing/bundle`.
  - **Bootstrap Distribution Server**: Dedicated bootstrap and bundle distribution server resides in `~/Viettel/OtelTrace/bootstrap` (port 30105).
  - **Symlink Architecture**: `~/Viettel/OtelTrace/oldkernel -> ~/Viettel/NetworkTracing/oldkernel` and `~/Viettel/OtelTrace/bundle -> ~/Viettel/NetworkTracing/bundle` ensure single-source-of-truth integrity while packaging executes cleanly from `OtelTrace/bootstrap`.
  - **Universal Fleet Package (`bundle.tar.gz`)**: Packaged with both modern eBPF and real oldkernel agent code (`oldkernel/` containing `install-firstrun-el68.sh`, `nt-sniff-cpp`, `nt-ship-cpp`, `nt-sniff.py`, `nt-ship.py`, supervisor, and resource guards).
  - **Installer Auto-Delegation (`bundle/install.sh`)**: Automatically detects kernel floor (< 5.5) or `--oldkernel` flag and delegates to the packaged oldkernel installer.
  - **Bootstrap Daemon**: Managed directly via `run_server.sh` alongside TraceScope API (`:30102`).
  - Verified 100% distribution pass via `verify-oldkernel-bootstrap.sh` and `package-oldkernel.sh` (`bundle.tar.gz`, 37,329,702 bytes, PID 14422).
- **Reference**: Refer to `STATE.md` for full endpoints, features, and run guides.

---

## 4. Kubernetes Workload Split (2026-09-11)

- **Role-aware application**: `backend.app.application.create_app()` builds the
  backwards-compatible `all` app, the traffic-only `ingest` app, or the
  `agent-stats` lifecycle/reporting app. Entrypoints are `backend.main:app`,
  `backend.ingest_main:app`, and `backend.agent_stats_main:app`.
- **Stateless edge workloads**: Kubernetes starts 3 ingestion pods (HPA 3–12)
  and 2 agent pods (HPA 2–6). They mount no data volume. Ingestion pods perform
  decompression, parsing, credential sanitization, and normalization; agent pods
  validate protocol payloads and serve latest/detail/history/deletion contracts.
- **Storage-owner service boundary**: both edge roles use
  `OTEL_STORAGE_OWNER_URL=http://tracescope-storage:8000` and an
  `OTEL_INTERNAL_API_TOKEN`. Authenticated `/internal/v1/*` operations are
  excluded from OpenAPI. Storage errors retain retryable 429/503 behavior.
- **SQLite/WAL safety**: only the single-replica `tracescope-storage` StatefulSet
  mounts the ReadWriteOnce PVC. Its API and analytics-worker sidecar share the
  same pod/filesystem lock domain. No other pod opens SQLite, and network/RWX
  filesystems are explicitly unsupported.
- **Idempotency**: trace rows and `X-Batch-Id` remain transaction-atomic in the
  storage owner's coalescing writer. Agent `(node, instance_id, sequence)`
  acceptance is now one atomic insert, avoiding check-then-write races across
  multiple edge pods.
- **Routing and operations**: one Ingress preserves all public paths and routes
  ingestion, agent, and UI/query traffic to separate ClusterIP Services. Probes,
  requests/limits, PDBs, HPA resources, ConfigMap wiring, and a Secret template
  are under `deploy/k8s/`.
- **Build and migration**: `deploy/docker/Dockerfile` provides `api`, `ingest`,
  `agent-stats`, and `worker` targets. The storage pod init container exclusively
  owns migrations; runtime containers set `OTEL_RUN_MIGRATIONS=false`.
- **Runbook and validation**: `deploy/k8s/README.md` documents backup/restore,
  rollout, rollback, storage requirements, secrets, build commands, and risks.
  `deploy/k8s/validate_manifests.py` checks the single-PVC-owner invariant without
  contacting a cluster. Never run `kubectl` from this repository automation.

---

## 5. ClickHouse Storage Migration (2026-09-11)

- **Architecture Overview**: TraceScope has migrated its primary persistence layer to ClickHouse (`http://127.0.0.1:8123`, default database `tracescope`).
- **Database Engine & Driver**:
  - Python driver: `clickhouse_connect` HTTP client with thread-local client caching and connection lifecycle management in `backend/app/repositories/db_context.py`.
  - Schema & Migrations: `backend/clickhouse_migrations/001_initial.sql` defining 35 tables with `ReplacingMergeTree` engines for mutable entity sets, microsecond monotonic default IDs (`toUnixTimestamp64Micro(now64(6))`), and tracked via `schema_migrations`.
- **Data Parity & Migration**:
  - Direct offline migration script: `python3 backend/scripts/migrate_sqlite_to_clickhouse.py --sqlite-path data/tracescope.db`.
  - 100% exact row parity confirmed across 35 tables (351,936 rows migrated in 11.27s, verified in 0.31s).
  - Rollback safety: `data/tracescope.db` remains intact and unmodified as a persistent local fallback archive.
- **ClickHouse DB-API Compatibility Adapter (`backend/app/repositories/db_context.py`)**:
  - Literal escaping & binding: `_convert_placeholders_and_bind` translates `?` to literal-formatted values using `format_query_value(val, timezone.utc)`, avoiding `%` format collisions with Python format specifiers.
  - `ClickHouseRow`: Mimics `sqlite3.Row` with dictionary mapping, tuple access, sequence slicing (`row[1:5]`), and automatic unqualified column name mapping (e.g. `p.principal_name` accessible as `principal_name`).
  - Expression translations:
    - Scalar `MAX(a, b)` / `MIN(a, b)` -> `greatest(a, b)` / `least(a, b)`.
    - SQLite `strftime('%H', ts/1000, 'unixepoch')` -> `formatDateTime(toDateTime(intDiv(ts, 1000)), '%H')`.
    - `GROUP_CONCAT(col)` -> `arrayStringConcat(groupArray(toString(col)), ',')`.
    - `UPDATE` -> `ALTER TABLE ... UPDATE ... SETTINGS mutations_sync = 1`.
    - `DELETE` -> `ALTER TABLE ... DELETE ... SETTINGS mutations_sync = 1`.
    - `PRAGMA table_info` -> `DESCRIBE TABLE`.
    - `cursor.lastrowid`: simulated via `SELECT max(id) FROM {table}` for autoincrement parity.
- **Verification Suite**:
  - Pytest Suite: 98/98 tests passed across all 13 modules in `tests/` in an isolated test database harness (`test_pytest_<id>`).
  - End-to-End Curl & Safety Suite: 42/42 checks passed (`sh backend/scripts/curl_test_all_pages.sh`), covering all 17 SPA routes and 25 backing API endpoints with 0 JavaScript crash vulnerabilities.
  - Live Ingestion & Coalescing Writer: Direct ClickHouse asynchronous batched inserts (`traces` and `ingest_batches`), bounded queue backpressure (429 + `Retry-After: 1`), and atomic replay deduplication.

- **2-Image Strategy & Helm Alignment (2026-09-11)**:
  - `scripts/build_and_push.sh` strictly outputs exactly 2 images: `xhatsu101/tracescope:app-<version>` and `xhatsu101/tracescope:ingest-<version>`. Removed legacy `api` alias tag.
  - `deploy/helm/tracescope/values.yaml` aligned: `agentStats.enabled: false` by default (merged into `storage-0`). If enabled, uses `xhatsu101/tracescope:app-0.2.0` running `backend.agent_stats_main:app`. All image tags synchronized to `0.2.0`.

---

## 6. Complete ClickHouse Cutover & Stateless UI Architecture (2026-09-11)

- **Async Batched ClickHouse Ingest Path (`backend/app/services/ingest_writer.py`)**:
  - Direct ClickHouse batch inserts via `db.client.insert("traces", ...)` and `db.client.insert("ingest_batches", ...)`.
  - Configurable coalescing window (`OTEL_INGEST_COALESCE_MS=5`) and batch size (`OTEL_INGEST_TRANSACTION_RECORDS=50000`).
  - Durable commit semantics preserved: HTTP 200 returned only after ClickHouse writes synchronous block parts to disk.
  - Bounded admission queue (`OTEL_INGEST_QUEUE_CAPACITY=256`) returning HTTP 429 with `Retry-After: 1` on saturation.
  - Replay deduplication via `ingest_batches` ClickHouse table and in-memory LRU cache: repeated `X-Batch-Id` returns HTTP 200 `{"ok": true, "duplicate": true}` with zero database writes.
  - Agent stats telemetry (`backend/app/repositories/agent_stats_repository.py`) writes directly to `agent_stats_latest` and `agent_stats_history` with sequence deduplication and `FINAL` query semantics.
- **Edge Workload Decoupling**:
  - Edge pods (`tracescope-ingest` and `tracescope-agent-stats`) communicate directly with ClickHouse (`OTEL_CLICKHOUSE_HOST` / `OTEL_CLICKHOUSE_PORT`).
  - Storage-owner HTTP proxy forwarding (`OTEL_STORAGE_OWNER_URL`) is no longer required; edge workloads scale independently without serialization bottlenecks.
- **Kubernetes Architecture (`deploy/k8s/`)**:
  - **ClickHouse StatefulSet & Service** (`25-clickhouse-statefulset.yaml`, `26-clickhouse-service.yaml`): Runs `clickhouse/clickhouse-server:24.3-alpine` (1 replica), mounts RWO PVC `clickhouse-data` (5Gi test capacity, configurable), exposes HTTP 8123 and native 9000 ports.
  - **Application & Analytics StatefulSet** (`30-storage-statefulset.yaml` -> `tracescope-app`, `31-api-service.yaml`, `37-storage-service.yaml`): Named `tracescope-app` (pod `tracescope-app-0`). Consolidates `migrate` init container, `api` container (FastAPI + built-in React UI + Agent Stats on `:30102`), and `analytics-worker` sidecar into a single StatefulSet using image `xhatsu101/tracescope:app-0.2.0`.
  - **Horizontally Scalable Ingestion Pool** (`32-ingest-deployment.yaml`, `33-ingest-service.yaml`, `42-hpa.yaml`): High-performance ingest edge pool running `xhatsu101/tracescope:ingest-0.2.0` on `:30103`, auto-scaling from 3 to 12 replicas.
  - **Unified Ingress Routing** (`40-ingress.yaml`): Routes ingest traffic (`/api/v1/ingest`, `/api/ingest`, `/v1/traces`, `/api/v1/ingestion/status`) to `tracescope-ingest`, and all other traffic (`/`, `/assets`, `/api`, `/api/agent/stats`) directly to `tracescope-api`.
  - **Manifest Validation & Topology Tests**: `python3 deploy/k8s/validate_manifests.py deploy/k8s` verifies all 16 documents and invariants cleanly with 0 errors. All 20/20 deployment topology tests in `tests/test_deployment_topology.py` pass.

---

## 7. Helm Chart Design & Topology Modes (`deploy/helm/tracescope/`) (2026-09-11)

- **Production Helm Chart**:
  - Located at `deploy/helm/tracescope/` with `Chart.yaml` (v0.2.0), comprehensive `values.yaml`, and modular templates.
  - Supports full **Distributed Mode** and **Consolidated / Merged Modes**:
    - **Default Managed Topology (3-Tier)**: `ui.enabled: false` (UI merged into API) and `agentStats.enabled: false` (agent telemetry merged into API). Reduces deployment overhead from 5 workloads (9–21 pods) down to 3 workloads (5 pods: ClickHouse, Storage API+UI+Worker, and Ingest HPA pool).
    - **Full Distributed Mode**: Enable `ui.enabled: true` and `agentStats.enabled: true` for independent scaling pools.
    - **External ClickHouse Mode**: `clickhouse.enabled: false` connects to external ClickHouse clusters via `clickhouse.host` and `clickhouse.password`.
  - **Dynamic Ingress**: Path routing automatically adjusts targets based on enabled flags (`/` and `/assets` switch between `ui` and `api`; `/api/agent/stats` switches between `agent-stats` and `api`).
  - **Verification**: Verified via `helm lint` (0 errors) and `helm template` across all topology permutation cases. Tested `backend.main:app` with `TestClient` confirming HTTP 200 for `/`, `/api/v1/overview`, and `/api/agent/stats`.

---

## 8. 2-Image Architecture & Build/Push Pipeline (2026-09-11)

- **Consolidated 2-Image Architecture**:
  - Image 1 (`Target: api`): Main App image (`xhatsu101/tracescope:app-<tag>` / `:api-<tag>`), serving FastAPI analytics queries, bundled React 19 UI (`/app/frontend/dist`), schema migration init container, and background analytics worker via container command override `command: ["python", "-m", "backend.worker"]`.
  - Image 2 (`Target: ingest`): Ingest image (`xhatsu101/tracescope:ingest-<tag>`), serving high-throughput trace batch ingestion with HPA horizontal scaling.
  - Database: Official upstream `clickhouse/clickhouse-server:24.8` (no custom build required).
- **Automated Build & Push Script (`scripts/build_and_push.sh`)**:
  - 100% POSIX `/bin/sh` compliant script (symlinked to `deploy/docker/build_and_push.sh`).
  - Robust directory discovery: searches upwards for `deploy/docker/Dockerfile` so it executes seamlessly from any working directory or symlink location.
  - Supports repository tag differentiation on single repository (e.g. `xhatsu101/tracescope <version>` -> `:app-<ver>` and `:ingest-<ver>`).
  - Also supports token replacement templates (`{image}` and `{tag}`).
  - Supports `--dry-run` (`-d`) and `--no-push` (`-n`) flags.
  - Verified across automated test cases invoked from both repo root and `deploy/docker/`.




