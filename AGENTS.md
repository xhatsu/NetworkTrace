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
- **Storage Invariant**: OTel trace data from application services is retained in Elasticsearch. ClickHouse persistence is reserved strictly for **host/probe agent trace data** (`OTEL_CLICKHOUSE_ONLY_AGENT_TRACES=true`), preventing duplicate storage expansion. Ingest endpoints acknowledge OTel payloads without writing them to ClickHouse.
- **Root Directory**: `/home/ubuntu/Viettel/OtelTrace`
- **Current Database**: ClickHouse (`127.0.0.1:8123`) for self-hosted local testbed with transparent **Elasticsearch / ELK database query migration** (`OTEL_STORAGE_BACKEND=elasticsearch` or `OTEL_ES_URL`). In target environments where trace data is stored in Elasticsearch, TraceScope queries ELK directly via `ElasticsearchTraceRepository`, while gracefully falling back to ClickHouse for local offline testing.
- **Active Dashboard Port**: `0.0.0.0:30102` (lifecycle-script default and current listener).
- **NetworkTracing Hub Port**: `0.0.0.0:30102` (OTLP / Ingest Hub in `~/Viettel/NetworkTracing`).
- **Ingest NodePort**: `http://<node-ip>:30103/api/ingest` (Plain HTTP / non-SSL NodePort entrypoint for legacy C++ shippers such as `nt-ship-cpp` / `nt-sniff-cpp`; verified on public node `129.150.59.233:30103`).
- **Ingress HTTP NodePort**: `http://<node-ip>:31561` (Cluster Ingress-Nginx plain HTTP NodePort routing `/api/ingest`, `/api/agent/stats`, `/api`, and `/` without TLS; verified on public node `129.150.59.233:31561`).
- **Cluster APM & Elasticsearch Services**:
  - `tmp-elk-svc` (NodePort `9200:32073/TCP`, ClusterIP `10.97.180.119:9200`): Elasticsearch 7.17.24 holding APM indices (`apm-*-transaction-*`, `apm-*-metric-*`, `apm-*-span-*`, `apm-*-error-*`). Wired directly to `tracescope-worker` and dashboard on `http://127.0.0.1:32073`.
  - `apm-server` (NodePort `10.99.87.70:8200` -> NodePort `32765`): Ingestion gateway daemon streaming APM data into Elasticsearch.


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
    - `POST /api/v1/ingest`, compatibility alias `POST /api/v1/ingest/traces`, and old-kernel shipper alias `POST /api/ingest`: bounded OTEL/ELK or NetworkTracing `{node, events[]}` ingestion with credential sanitization, automatic `Content-Encoding: gzip` / magic-byte decompression with HTTP 400 rejection on corrupted payloads, and transaction-atomic `X-Batch-Id` deduplication (HTTP 200 `{"ok": true, "duplicate": true}` on replay, zero duplicate database insertions). Concurrent uploads enter the bounded coalescing writer; saturation returns HTTP 429 plus `Retry-After: 1`, and HTTP 200 is sent only after durable ClickHouse commit.
    - **Ingest Batch Deduplication** (`backend/app/repositories/ingest_batch_repository.py`): Defined in `backend/clickhouse_migrations/001_initial.sql` as the `ingest_batches` table with in-memory LRU cache and automatic 7-day pruning.
    - **High-TPS Ingest Writer** (`backend/app/services/ingest_writer.py`): A background writer thread coalesces concurrent requests for up to 5 ms / 50,000 records into batched ClickHouse INSERTs, bounds admission to 256 queued requests, writes trace rows and batch IDs durably, exposes queue/commit counters through `GET /api/v1/ingestion/status`, and shuts down cleanly with the FastAPI lifespan. Per-request rollup launches were removed; the existing `tracescope-worker` performs analytics on its 60-second cadence.
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
  - `db_context.py`: ClickHouse connection context with a narrow SQLite-compatibility DB-API adapter (dialect translation confined here).
  - `trace_repository.py`: Normalized trace batch insert, query, and search.
  - `aggregate_repository.py`: Rollup storage, time-series query, KPI summaries.
  - `topology_repository.py`: Edge materialization, topology graph generation, caller/dependency traversal.
  - `baseline_repository.py`: Baseline storage and retrieval by hour-of-day/day-of-week.
  - `anomaly_repository.py`: Anomaly event querying, lifecycle patching (open, investigating, resolved, suppressed). Coalesces contiguous open anomaly occurrences for identical dimensional signatures within 15 minutes, preserving root incident ID, extending `last_seen`, tracking `occurrences` count, and calculating `duration_mins` in metadata via ClickHouse `ReplacingMergeTree ORDER BY id`.
  - `principal_repository.py`: Principal rankings and comprehensive behavioral profiling.
  - `user_repository.py`: User inventory, fingerprint profiles, timelines, explainable changes, graph, analytics, operator review actions, and incidents query.
  - `agent_stats_repository.py`: Agent health sample storage — upserts `agent_stats_latest` (one live row per node+instance), appends to `agent_stats_history` (idempotent via UNIQUE on `(node, instance_id, sequence)`), prunes history to 2880 rows/node, and provides atomic `delete_node` purging.
  - `clickhouse_migrator.py`: Versioned migration orchestrator (`001` through `005_system_telemetry_retention.sql`) and system retention manager (`configure_system_telemetry_retention`, `truncate_system_logs`). Enforces bounded 3-day TTL on system logs (`text_log`, `query_log`, `processors_profile_log`, etc.) and 7-day TTL on `error_log` to prevent disk exhaustion.
- **Analytics & Detection Services** (`backend/app/services/`):
  - `behavioral_engine.py`: Canonical identity normalization, detector readiness, multi-layer baselines, bounded incident lifecycle, capped family scoring (Origin cap 35, Access cap 40, Activity cap 35, Identity mapping cap 30, Authentication cap 45), 7-question explainability cards, and new behavioral/auth detectors (`OPERATION_MIX_SHIFT`, `CALLER_PRINCIPAL_SWITCH`, `TARGET_FANOUT_SURGE`, `SOURCE_FANOUT_SURGE`, `PRINCIPAL_RATE_SURGE`, `AUTH_FAILURE_BURST`, `FAILURE_THEN_SUCCESS`, `SOURCE_IDENTITY_FANOUT`, telemetry quality gates).
  - `normalization.py`: Normalizes OTel / ELK payloads, derives trusted IP / proxies, extracts WSSE usernames with case preservation, sets canonical `operation_key` (`Service/operation`), and maps decoupled `auth_result` / `auth_evidence`.
  - `aggregation.py`: Computes 60s and 300s rollups with exact p50/p95/p99 percentiles.
  - `baseline.py`: Computes rolling median and MAD across dimensions.
  - `anomaly_detection.py`: Detectors 1–8. Detector 8 (`unusual_time`) enforces an established baseline maturity gate (`sample_count >= 10`) for human principals, suppressing cold-start false positives for `-anonymous-` and periodic polling endpoints.
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
- **Design System & Typography**: Clean, matte, non-glossy glanceable observability monitor design system.
  - Typography: 100% standard font scaling, 12px Recharts axis ticks, crisp typography hierarchy.
  - Surfaces: Clean matte dark canvas (`#0c0d14`), elevated panels (`#141622`), side navigation (`#0c0e17`).
  - Zero Glossy Effects: Eliminated all `radial-gradient` ambient sheens, `backdrop-blur` frosted glass filters, and glowing `shadow-[0_0_...` neon halos.
  - Borders: Crisp, flat borders `#262838`.
  - Multi-Accent Palette:
    - User Intelligence & Identity: Crisp Cyan (`#00f0ff`).
    - Observability & Services: Sentry Violet / Indigo (`#8b5cf6`, `#6366f1`).
    - Infrastructure & Fleet: Golden Amber (`#f59e0b`, `#fbbf24`).
    - Performance & Signals: Sky Blue for Throughput/RPS, Emerald for TPS/Optimal Latency, Violet for p95, Rose for 5xx/Errors.
  - Multi-Color Visualizations: Multi-percentile AreaCharts (Rose p99, Amber p95, Mint p50), distinct `Cell` fills for account volumes, 4-tier latency heatmap color ramp (<100ms emerald, 100-250ms cyan, 250-500ms amber, >500ms rose), and group-coded topology nodes and edge states without specular sheen.
- **Built Output**: `frontend/dist` served directly by FastAPI on port 30102.
- **Navigation & Pages**:
  - `Overview` (`/`): User Behavioral Observability Dashboard focusing strictly on identity behavior: 8 User KPIs, traffic velocity vs error dynamics, risk cohort distribution, prioritized anomalous accounts with 1-click workspace inspector, shared credentials, and live change/incident triage.
  - `Topology` (Legacy `/topology`): Redundant generic service topology removed from primary navigation; redirects cleanly to `/users`. User access topology is served within the user workspace at `/users/:principal/topology`.
  - `Anomalies` (`/anomalies`, `/anomalies/:id`): Dual-mode Incident Episode list (`Group Incidents` vs `Raw Findings`) collapsing repetitive 5-minute alerts into aggregated continuous episodes with recurrence badges (`Nx recurrent`), time spans, duration, peak/latest values, and expandable slice accordions. Anomaly Detail with "WHAT CHANGED COMPARED WITH NORMAL?" explainability card, probable root cause, blast radius, and lifecycle action controls.
  - `Services` (`/services`, `/services/:name`): Service catalog, operation percentiles, caller graphs, instances.
  - `Principals` (`/principals`, `/principals/:name`): Identity behavior explorer, target services, operations, callers, and hourly activity profiles.
  - `Traces` (`/traces`, `/traces/:id`): Trace explorer with filters and multi-tier interactive waterfall visualization.
  - `User Intelligence`:
    - `User Directory` (`/users`): Searchable principal inventory with live stats, risk level badges, sort controls, and launcher into user workspace.
    - `User Workspace & Layout` (`/users/:principal`): Sticky entity header with user avatar, type indicator, behavior score pill, current 5m RPS, active targets, quick account switcher dropdown, and 6 dedicated operational tabs:
      1. `User Overview` (`/users/:principal/overview`): Current 5m vs baseline deltas across 8 KPIs, 4 high-contrast line charts in a 2x2 grid (two lines, each line two cards: RPS vs base, error rate, p95 latency, Abnormality Score Spike scaled with high RPS deviation), mini change timeline, and relationship expansion summary.
      2. `Activity & Performance` (`/users/:principal/activity`): Throughput RPS, req/min volume, 100% stacked status distribution (2xx/4xx/5xx/timeout), multi-percentile latency area chart (p50/p95/p99), and interactive pinned time-slice inspector.
      3. `Access & Topology` (`/users/:principal/topology`): Dedicated `User → Caller → Target` canvas topology graph, collapsible target operations breakdown, edge metrics inspector drawer.
      4. `Behavior Changes` (`/users/:principal/changes`): Deviation-only behavioral shifts, before vs now category distribution bars, and 7-questions explainability timeline.
      5. `Usage Patterns` (`/users/:principal/patterns`): 24h × 7d activity heatmap, target services distribution bars, operations distribution bars, and behavioral scope time series.
      6. `Anomalies & Investigations` (`/users/:principal/investigations`): Triage queue, trigger hypotheses, BEFORE vs NOW metrics comparison table, causal relationship chain, and operator review controls.
    - Global Feeds & Analytics: `/user-changes`, `/user-graph`, `/user-analytics`, `/incidents`.
  - `Infrastructure`: `Agent Fleet` (`/agent-stats`) and `Agent Drilldown` (`/agent-stats/:node`) with interactive time-series dashboards.
  - Global Search in header: Search services, principals, or jump directly to trace waterfall by ID.
  - **Localization (i18n)**: Full, authentic Vietnamese localization across all 17 pages, charts, tables, cards, and modals with persistent language switcher (`🇻🇳 VI` / `🇬🇧 EN`) defaulting to Vietnamese.

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
- **Test Suite**: 167/167 tests passed in an isolated temporary-database harness (`.venv/bin/python -m pytest tests/ -q`); production data is never mutated by tests:
  - Unified Helm global image tag resolution and component overrides (`tests/test_deployment_topology.py`).
  - LLM diagnostic investigation subsystem unit, integration, and security tests (`tests/test_llm_investigation_*.py`) including `_parse_object` resilience across markdown code fences, `<think>` tags, and reasoning token limits.
  - Unit & domain tests in `tests/test_analytics.py`, `tests/test_api.py`, `tests/test_ingestion.py`.
  - Ingestion batch deduplication and gzip decompression tests in `tests/test_batch_dedup_and_gzip.py`.
  - High-concurrency request coalescing, atomic concurrent deduplication, bounded-queue backpressure, and retryable HTTP 429 tests in `tests/test_ingest_writer.py`.
  - Comprehensive behavioral API tests in `tests/test_behavioral_api.py`.
  - Canonical identity normalization, realm removal, multi-layer baselines, detector readiness, capped family scoring, and bounded incident lifetime tests in `tests/test_identity_normalization_and_incidents.py`.
  - Dedicated IP anomaly and novel user on host tests in `tests/test_user_ip_anomalies.py`.
  - F5 BIG-IP load balancer SNAT, XFF, X-Real-IP, and IP spoofing rejection in `tests/test_f5_lb_normalization.py`.
  - Reference compatibility and WSSE ingestion tests in `tests/test_reference_compat.py` and `tests/test_wsse_ingestion.py`.
  - Service boundary, workload splitting, and topology tests in `tests/test_service_boundaries.py`, `tests/test_split_workloads_integration.py`, and `tests/test_deployment_topology.py`.
  - Host/probe agent trace isolation in ClickHouse (`tests/test_agent_traces_only.py`).
  - System telemetry log retention and truncation (`tests/test_system_retention.py`).
  - Compact AggregatingMergeTree principal readiness summary (`tests/test_principal_readiness_summary.py`).
  - Aggregation worker start time cutoff, historical data bypass, checkpoint fast-forwarding, and Elasticsearch sync initial page range filtering (`tests/test_worker_start_time.py`).
  - All 22 code review findings verified and documented in `FIX_REPORT.md`.
- **End-to-End Curl & JS Safety Test Suite**: 48/48 tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - Tested all 20 SPA routes (including `/agent-stats`, `/agent-stats/:node`, and 6 user workspace sub-routes) with HTTP 200 and valid HTML shell bundle delivery.
  - Tested 28 backing APIs against frontend TypeScript contracts via `backend/scripts/validate_js_safety.py`.
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
- **Dataset Baseline (1-month dataset via Elasticsearch & ClickHouse)**: Ingested 60,000 documents spanning 30 days from `/home/ubuntu/Viettel/Data/otel_elk_traces_1month.jsonl.gz` into Elasticsearch NodePort `:32073` (`apm-7.17.24-transaction-000001`, 29.6 MB). Synced into ClickHouse `traces` (24.79 MiB) by `tracescope-worker`. Computed 153,181 metric buckets (1m and 5m), 7,418 principal baselines, 48,914 service baselines, 3,448 user behavioral change events, and 55 security incidents. All accounts established (`learning_status: established`). System logs truncated to 2.25 MiB with 1-day TTL.
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
  - `send_traces.py`: High-performance streaming ingestion tool supporting HTTP batch POSTing (`--mode http`) and fast direct ClickHouse batch writes (`--mode direct`, auto-tuned 5,000 batch size).
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
- **Presentation Layer Migration (RPS to TPS)**: Standardized all user-facing throughput units, metrics, tooltips, chart legends, and comparison tables across the React frontend and API responses (`/users/{principal}/investigations`, `/anomalies`) from RPS / `req/s` to TPS / `tps` without breaking underlying database schemas or compatibility.
- **JavaScript Safe Integer Precision & Anomaly ID Guard**:
  - `deterministic_anomaly_id` (`anomaly_repository.py`) uses `(raw_hash % 9_000_000_000_000_000) + 1` to guarantee newly generated anomaly IDs strictly fit within JavaScript `Number.MAX_SAFE_INTEGER` ($2^{53} - 1 = 9,007,199,254,740,991$), preventing IEEE-754 precision loss and trailing-zero rounding in web browsers.
  - `get_anomaly`, `update_status`, and `anomaly_users` implement automatic float64 ULP tolerance fallback ($\pm 4096$) for any IDs $> 9 \times 10^{15}$, ensuring legacy or bookmarked URLs resolve accurately.
  - Database reset executed via `backend/scripts/reset_testbed.py` (truncated ClickHouse analytical tables, deleted Elasticsearch APM indices, truncated system telemetry logs).
- **Behavioral Change Events Deduplication (`principal_change_events FINAL`)**:
  - Enforced ClickHouse `FINAL` modifier across all `principal_change_events` queries in `UserRepository` (`list_changes`, `summary`, `analytics`, `service_users`, `graph`), ensuring `ReplacingMergeTree` collapses duplicate rows inserted across periodic micro-batches.
  - Added client-side defensive deduplication by fingerprint/key in `UserChangesTab.tsx`.
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
- **ClickHouse single store**: the single-replica `tracescope-clickhouse`
  StatefulSet owns the ReadWriteOnce data PVC. Application roles (storage API,
  ingest, agent-stats, worker) are stateless and connect over HTTP 8123;
  network/RWO-only applies to the ClickHouse volume.
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

## 5. ClickHouse Persistence & Storage Architecture

- **Architecture Overview**: TraceScope has migrated its primary persistence layer to ClickHouse (`http://127.0.0.1:8123`, default database `tracescope`).
- **Database Engine & Driver**:
  - Python driver: `clickhouse_connect` HTTP client with thread-local client caching and connection lifecycle management in `backend/app/repositories/db_context.py`.
  - Schema & Migrations: `backend/clickhouse_migrations/001_initial.sql` defining 35 tables with `ReplacingMergeTree` engines for mutable entity sets, microsecond monotonic default IDs (`toUnixTimestamp64Micro(now64(6))`), and tracked via `schema_migrations`.
- **Data Parity & Migration**:
  - Offline migration copied 351,936 rows across 35 tables with 100% exact row parity (script and SQLite source purged 2026-09-11 after verification).
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
  - Pytest Suite: 150/150 tests passed across all 13 modules in `tests/` in an isolated test database harness (`test_pytest_<id>`).
  - End-to-End Curl & Safety Suite: 48/48 checks passed (`sh backend/scripts/curl_test_all_pages.sh`), covering all 17 SPA routes and 31 backing API endpoints with 0 JavaScript crash vulnerabilities.
  - Manifest Validation: `python3 deploy/k8s/validate_manifests.py deploy/k8s` passed with 16 documents and 0 errors.
  - Live Ingestion & Coalescing Writer: Direct ClickHouse asynchronous batched inserts (`traces` and `ingest_batches`), bounded queue backpressure (429 + `Retry-After: 1`), and atomic replay deduplication.

---

## 6. Helm Chart Design & Topology Modes (`deploy/helm/tracescope/`)

- **Production Helm Chart**:
  - Located at `deploy/helm/tracescope/` with `Chart.yaml` (v0.2.6), comprehensive `values.yaml`, and modular templates.
  - App pod named `tracescope-app-0` (StatefulSet `tracescope-app`), rendered with simplified `values.yaml` `app.image:` configuring `migrate`, `api`, and `analytics-worker` in one place with image tag `app-0.2.6`.
  - Ingestion workload runs `ingest-0.2.6` with HPA (3–12 replicas).
  - Supports full **Distributed Mode**, **Consolidated / Merged Modes**, and **Elasticsearch / ELK Mode**:
    - **Default Managed Topology (3-Tier)**: `ui.enabled: false` (UI merged into API) and `agentStats.enabled: false` (agent telemetry merged into API). Reduces deployment overhead from 5 workloads (9–21 pods) down to 3 workloads (5 pods: ClickHouse, Storage API+UI+Worker, and Ingest HPA pool).
    - **Full Distributed Mode**: Enable `ui.enabled: true` and `agentStats.enabled: true` for independent scaling pools.
    - **External ClickHouse Mode**: `clickhouse.enabled: false` connects to external ClickHouse clusters via `clickhouse.host` and `clickhouse.password`.
    - **Elasticsearch / ELK Mode**: `storage.backend: elasticsearch` routes application trace queries directly to Elasticsearch/ELK clusters (`elasticsearch.url`, `elasticsearch.index`, `elasticsearch.apiKey`), while retaining host/agent telemetry in ClickHouse.
  - **Docker Images Published**:
    - `xhatsu101/tracescope:app-0.2.6` (digest: `sha256:63ae3efc8c2ae7fddba3082fff2d29f0e6c0e9ae1d1c1726a2f9529c85a4a8cf`)
    - `xhatsu101/tracescope:ingest-0.2.6` (digest: `sha256:11e96722ca50c919ccebebeadece3c458c7dbc58670facb6b314ea8166e9b861`)
  - **Verification**: Verified via `helm lint` (0 errors) and `helm template` across all topology permutation cases. Docker containers verified with smoke tests (`APP_SMOKE_OK`, `INGEST_SMOKE_OK`).

---

## 7. 2-Image Architecture & Build/Push Pipeline

- **Consolidated 2-Image Architecture**:
  - Image 1 (`Target: api`): Main App image (`xhatsu101/tracescope:app-<version>`), serving FastAPI analytics queries, bundled React 19 UI (`/app/frontend/dist`), schema migration init container, agent-stats, and background analytics worker via container command override.
  - Image 2 (`Target: ingest`): Ingest image (`xhatsu101/tracescope:ingest-<version>`), serving high-throughput trace batch ingestion with HPA horizontal scaling.
  - Database: Official upstream `clickhouse/clickhouse-server:24.8` (no custom build required).
- **Automated Build & Push Script (`scripts/build_and_push.sh`)**:
  - 100% POSIX `/bin/sh` compliant script (symlinked to `deploy/docker/build_and_push.sh`).
  - Robust directory discovery: searches upwards for `deploy/docker/Dockerfile` so it executes seamlessly from any working directory or symlink location.
  - Outputs strictly 2 images: `xhatsu101/tracescope:app-<version>` and `xhatsu101/tracescope:ingest-<version>`.
  - Supports token replacement templates (`{image}` and `{tag}`).
  - Supports `--dry-run` (`-d`) and `--no-push` (`-n`) flags.
  - Aligned with Helm chart (`deploy/helm/tracescope/values.yaml`): `agentStats.enabled: false` (consolidated into storage-0) and configured to use `xhatsu101/tracescope:app-0.2.0` if enabled.

---

## 8. Live Production User Data Push & End-to-End Verification (2026-09-12)

- **Production Target**: `https://trace.n2d.id.vn`
- **Shipper Execution**: `/tmp/push_to_production.py` streamed 250,000 spans from `/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz` in 500 OTLP `resourceSpans` batches (Gzip-compressed, 3 threads, persistent keep-alive, unique `X-Batch-Id`).
  - Throughput: 4,449.3 spans/sec (8.9 batches/sec), 56.19s duration.
  - Data transfer: 228.49 MB uncompressed -> 24.58 MB compressed (9.3x compression ratio).
  - Reliability: 100% acked (250,000 / 250,000), 0 rejected, 0 429s, 2 transient 5xx cleanly retried and committed.
- **User-Analysis End-to-End Verification**:
  - `otlp_parser.py` consumed `enduser.id` semantic conventions into `principal_name` dimensions in ClickHouse.
  - `/api/v1/users`: Populated with all 8 named identities (`minh.ngoc`, `linh.pham`, `mai.tran`, `khanh.vu`, `duong.nguyen`, `quang.bui`, `hong.dang`, `thao.trang`).
  - `/api/v1/users/minh.ngoc`: Exact match against ground truth on all microservice request counts (`session-cache`: 6186, `api-gateway`: 3514, `notification-service`: 2874, `catalog-service`: 1925, `cart-service`: 1335).
  - `/api/v1/user-graph`: 28 nodes (10 users, 17 targets) and 188 directed dual-layer access edges.
  - `/api/v1/user-analytics`: All 10 ranking categories populated.
  - `/api/v1/user-changes`: 625 change events across 4 detector families (`USERNAME_FIRST_SEEN`, `NEW_SOURCE_IP`, `NEW_TARGET`, `NEW_OPERATION`) complete with 7-question explainability cards.
  - `/api/v1/incidents`: 18 bounded security incidents with capped family scoring (Score 75 across all 8 named users).
  - ClickHouse trace lookups: Spot checks on multi-tier spans across all users returned HTTP 200 with waterfalls spanning up to 16 microservices.
- **Identified Production Infrastructure Limit**:
  - ClickHouse worker aggregation (`aggregate_traces`) hit container memory ceiling: `Code: 241. DB::Exception: Memory limit (total) exceeded: would use 1.81 GiB, maximum: 1.80 GiB`.
  - Recommendation: Increase ClickHouse container RAM limit to >= 4 GiB and implement bounded time-window chunking (max 24h slices) in `aggregate_traces`.
- **Deliverable**: Full verbatim test report stored at `USER_DATA_PUSH_TEST_REPORT.md`.

---

## 9. Release 0.2.2 Deployment Preparation & Preflight Fixes (2026-09-14)

- **Release Version**: `0.2.2`
  - Chart metadata: `deploy/helm/tracescope/Chart.yaml` bumped to `version: 0.2.2`, `appVersion: "0.2.2"`.
  - Application version: `backend/app/application.py` FastAPI `version="0.2.2"`.
  - Image tags: `xhatsu101/tracescope:app-0.2.2` and `xhatsu101/tracescope:ingest-0.2.2` built and pushed to Docker Hub.
    - App Digest: `sha256:721acd2ef5e7a35be9f1e3879c8daba5be728bc8bd57b481c624665da8052cbf`
    - Ingest Digest: `sha256:d03d3e20549bc44a43d8f2b3e993c07105c29f3760034bad27e1e0b38c0d05af`
- **Security & Secret Provisioning**:
  - Independent cryptographically random tokens (64 chars, urlsafe base64) generated and embedded into `deploy/helm/tracescope/values.yaml` under `secrets.internalApiToken` (`1Ioi...(64 chars)`) and `secrets.apiKey` (`XOyx...(64 chars)`).
  - Redaction enforced across all logs, stdout, and reports.
  - Public mutation endpoints (`/api/ingest`, `/v1/traces`) now enforce authentication when deployed with chart defaults.
  - Ingress blocks external access to `/internal/*` via nginx `location ^~ /internal/ { return 404; }`.
  - Dockerfile cleaned: removed `ENV OTEL_CLICKHOUSE_PASSWORD=""`, eliminating Docker `SecretsUsedInArgOrEnv` warnings.
- **ClickHouse Headroom & Retention**:
  - ClickHouse memory raised in `values.yaml`: requests `2Gi`, limits `4Gi`.
  - Schema Migration 004 created (`backend/clickhouse_migrations/004_live_table_retention.sql`): applies 30-day TTL on `traces` and fixed 90-day TTL on `metric_buckets`.
- **Configuration Parity**:
  - Nine backend environment variables mapped into `values.yaml` and ConfigMap templates (`configmap.yaml` and `edge-configmap.yaml`): `OTEL_INGEST_MAX_BATCH_BYTES` (33554432), `OTEL_AGGREGATION_MAX_MEMORY_USAGE` (1073741824), `OTEL_AGGREGATION_EXTERNAL_GROUP_BY_BYTES` (268435456), `OTEL_AGGREGATION_SHADOW_ENABLED` (true), `OTEL_AGGREGATION_CUTOVER` (false), `OTEL_BASELINE_CADENCE_SECONDS` (300), `OTEL_BASELINE_SERIES_BUDGET` (100), `OTEL_ANOMALY_WINDOW_BUDGET` (100), `OTEL_ANALYTICS_STAGE_BUDGET_SECONDS` (55).
  - Used `{{ int .Values.config.<key> | quote }}` to prevent scientific notation formatting in rendered templates.
  - Production origin `https://trace.n2d.id.vn` added to `config.corsOrigins`.
- **Validation**:
  - `helm lint deploy/helm/tracescope`: 0 warnings, 0 failures, exit code 0.
  - `helm template tracescope deploy/helm/tracescope --namespace tracescope > /tmp/rendered-0.2.2.yaml`: exit code 0.
  - Full test suite: 123/123 tests passed in isolated test harness (`123 passed in 201.64s`).
  - Report deliverable: `DEPLOY_FIX_REPORT.md` written to repository root.

---

## 10. Release 0.2.2 Commit & Secret Isolation (2026-09-14)

- **Secret Isolation**:
  - Real secrets (`secrets.internalApiToken` `1Ioi...(64 chars)` and `secrets.apiKey` `XOyx...(64 chars)`) moved from `deploy/helm/tracescope/values.yaml` into gitignored `deploy/helm/tracescope/values-secrets.yaml`.
  - Added `values-secrets.yaml` to `.gitignore`.
  - `values.yaml` retains empty string defaults with explicit comments pointing to `values-secrets.yaml`.
  - Updated operator runbook in `DEPLOY_FIX_REPORT.md` §4 and §5 to supply `-f deploy/helm/tracescope/values-secrets.yaml`.
  - Verified `helm template` passes with `-f values-secrets.yaml` and fails without it due to template validation guard.
- **Repository Cleanup**:
  - Confirmed database purge (ClickHouse sole datastore; no local SQLite/DuckDB files).
  - Cleaned untracked junk directories (`.agents`, `.codex`).
  - Flagged ambiguous task briefs for retention.
- **Verification**:
  - 123/123 tests passed cleanly (`123 passed in 260.88s`).
  - Verified 0 hits on secret leak scan across all Git history.

---

## 11. Overview Fix & User-Centric Anomalies Overhaul (2026-09-15)

- **Overview Page & API Health**:
  - Root cause of broken Overview page resolved: `filters_model` in `backend/app/application.py` had rigid `start: datetime, end: datetime` requirements with no defaults and no parameter alias matching frontend's `from`/`to`, throwing HTTP 422 `Field required`.
  - Added `_parse_time_param` to parse ISO strings, epoch milliseconds, epoch seconds, and datetimes, with rolling 3h defaults.
  - Storage repository dashboard queries (`dashboard_summary`, `dashboard_series`, `rankings`, `heatmap`) redirected to live `metric_buckets` and `traces` in ClickHouse instead of legacy empty tables.
  - Added `_detect_clickhouse_host()` probe in `backend/config.py` to auto-discover ClickHouse on local or cluster IPs.
  - Enhanced `queryString` in `frontend/src/api.ts` to output `start`, `from`, `end`, and `to`.
  - Added defensive fallback default in `frontend/src/pages/Overview.tsx` for `summary.data`.
- **User-Centric Anomalies Overhaul**:
  - `frontend/src/pages/Anomalies.tsx`:
    - Summary KPI cards: Total Findings, Identity-Centric Findings, Impacted Users count, Top Offending Identity with direct link to user profile.
    - Perspective switcher: `All Findings` | `User & Identity Centric` (cyan-accented) | `Service & Fleet` (violet-accented).
    - Real-time search filter across user, IP, service, operation, or detector type.
    - Table column: Prominently attributes identities with clickable user badge linking to `/users/:user` (with User icon and external link) and Source IP badge.
    - Anomaly Detail Page: Hero "User Intelligence & Identity Context" card with user investigation action buttons, and enhanced "Related Users" panel with traffic share bars and behavioral changes flags.
    - Fixed Minified React error #31 by creating `getEntityName` to safely parse both string and object `{name, requests, error_rate}` shapes in `blast_radius.affected_principals` and `direct_callers`.
- **Validation**:
  - Playwright Chromium Real Browser Test Suite (`python3 backend/scripts/test_pages_playwright.py`): All 15/15 real browser pages passed in headless Chromium with 0 unhandled JS errors, 0 failed API requests, and 0 ErrorState renders.
  - Pytest Suite (`.venv/bin/python -m pytest tests/ -q`): All 139/139 unit and integration tests passed cleanly in 130s.
- **Kubernetes Deployment Invariants & Parity**:
  - `deploy/docker/Dockerfile`: Multi-stage build (`ui-builder` -> `api`, `ingest`, `agent-stats`, `worker`) tested with 100% clean TypeScript/Vite compilation.
  - In Kubernetes, `OTEL_CLICKHOUSE_HOST` is supplied via `tracescope-config` ConfigMap as `tracescope-clickhouse`. `backend/config.py` preserves explicit environment variables with zero probe delay.
  - `deploy/k8s/validate_manifests.py`: 17 documents across 10 resource kinds verified (0 errors).
  - Helm chart `deploy/helm/tracescope`: `helm lint` passes cleanly with `values-secrets.yaml`, and `helm template` renders valid Kubernetes manifests.
  - Strictly adherence to the constraint: never execute `kubectl` command.

---

## 12. 6 User-Centric Pages & Supporting Attribution Signal Architecture (2026-09-16)

- **6 User-Centric Operational Pages**:
  1. `User Overview` (`/users/:principal/overview`): *“Is this user behaving normally right now?”* — 8 KPI cards, 4 high-contrast line charts in a 2x2 grid (two lines, each line two cards: RPS vs base, error rate, p95, Abnormality Score Spike scaled with high RPS deviation where 10% off base = 10 pts, protected with a 0.5 req/s baseline significance floor to prevent sub-second traffic from inflating to 100 pts), mini change timeline, new relationship summary.
  2. `Activity & Performance` (`/users/:principal/activity`): *“How has this user’s traffic/performance changed?”* — Throughput RPS line chart, 100% stacked status distribution (2xx/4xx/5xx/timeout), multi-percentile latency area chart (p50/p95/p99), and interactive pinned time-slice inspector.
  3. `Access & Topology` (`/users/:principal/topology`): *“What systems is this user touching?”* — Dedicated canvas graph (`User → Caller → Target → Operation`), collapsible target operations breakdown, edge metrics inspector drawer.
  4. `Behavior Changes` (`/users/:principal/changes`): *“What is different from the user’s normal behavior?”* — Deviation-only behavioral shifts, before vs now category distribution bars, and 7-questions explainability timeline.
  5. `Usage Patterns` (`/users/:principal/patterns`): *“When and how does this user normally operate?”* — 24h × 7d activity heatmap, target services distribution bars, operations distribution bars, and behavioral scope time series.
  6. `Anomalies & Investigations` (`/users/:principal/investigations`): *“What needs investigation?”* — Triage queue, trigger hypotheses, BEFORE vs NOW metrics comparison table, causal relationship chain, and operator review controls.
- **Supporting Attribution Signal Architecture (IP as Context)**:
  - **Core Model**: Primary behavioral path is `User → Caller → Target → Operation`. Aggregation key is `principal × caller × target × operation`.
  - **IP Context**: Observed source IP is attached as supporting context (`observed_source_ip`, `effective_client_ip`, `source_ip_role`, `attribution_confidence`).
  - **Classification**: `classify_source_ip_role` categorizes IPs into `load_balancer`, `reverse_proxy`, `nat_gateway`, `service_ingress`, `client`, and `infrastructure` with `high`, `medium`, and `low` confidence.
  - **Incident Weighting**: Known/likely load balancers (`low` confidence) are suppressed or zero-weighted in incident scoring, while genuine client IPs are elevated.
  - **Selective Integration**:
    - Overview: Card 8 `Source IPs` with dashed border and `Secondary Attribution Context` pill.
    - Activity: Source IP filter dropdown with role pills (`Client` vs `Load Balancer`).
    - Topology: Pure behavioral path default; optional `[ ] Show network path (IPs / Proxies)` toggle to reveal intermediate network hops.
    - Changes: High-value novelties (`NEW_CALLER`, `NEW_TARGET`, `NEW_OPERATION`, `NEW_RELATIONSHIP`) prioritized over supporting network novelties.
    - Patterns: Known IPs baseline card as secondary attribution context.
    - Investigations: IP included as corroborating evidence with explicit role labels.
- **Validation**:
  - TypeScript & Vite build: 100% clean (`tsc -b && vite build`).
  - Curl & JS Safety Test Suite (`sh backend/scripts/curl_test_all_pages.sh`): All 48/48 tests passed (0 JS crash risks).
  - Playwright Chromium Real Browser Test Suite (`python3 backend/scripts/test_pages_playwright.py`): All 17/17 pages passed with 0 unhandled JS exceptions.
  - Pytest Suite: All 17 unit and behavioral normalization tests passed cleanly.

---

## 13. Deployment Artifacts & Multi-Platform Readiness (Helm, K8s, Docker) (2026-09-17)

- **Helm Chart (`deploy/helm/tracescope`)**:
  - Chart SemVer bumped to `0.3.0` (`Chart.yaml`).
  - Configured `llm:` block in `values.yaml` with `enabled`, `singleOwnerAck`, `baseUrl`, `model`, `responseMode`, `allowLoopbackHttp`, `contextTokens`.
  - Configured `secrets.llmApiKey` in `values.yaml` and `values-secrets.yaml`.
  - ConfigMap template (`templates/configmap.yaml`) and Secret template (`templates/secret.yaml`) cleanly map `OTEL_LLM_*` and `OTEL_LLM_API_KEY`.
  - Verified with `helm lint deploy/helm/tracescope/ -f deploy/helm/tracescope/values-secrets.yaml` (0 chart errors) and `helm template`.
- **Plain Kubernetes Manifests (`deploy/k8s/`)**:
  - `deploy/k8s/10-configmap.yaml`: Configured with `OTEL_LLM_*` environment variables and documentation.
  - `deploy/k8s/11-secret.example.yaml`: Configured with `OTEL_LLM_API_KEY` placeholder.
- **Docker & Docker Compose**:
  - `docker-compose.yml`: Parameterized `api` container with `OTEL_LLM_*` and `OTEL_API_KEY`, and `frontend` container with `VITE_API_KEY`.
  - `Dockerfile` & `deploy/docker/Dockerfile`: Standardized multi-stage container build supporting optional build-time frontend environment arguments (`VITE_API_KEY`, `VITE_API_URL`).

---

## 14. Investigation Route Auth Decoupling (2026-09-17)

- In `backend/app/api/investigations.py`, decoupled `investigation_auth` from mandatory `settings.api_key`.
- If `OTEL_API_KEY` is not set on the backend, `/api/v1/investigations/*` routes operate in open mode (matching the rest of the TraceScope telemetry endpoints), eliminating the `503 auth_unconfigured` barrier when deploying with public/edge-authenticated dashboards.
- If `OTEL_API_KEY` is configured, strict `X-API-Key` comparison via `hmac.compare_digest` is enforced as before (HTTP 401 on invalid/missing key).

---

## 15. Unified Global Helm Image Tag Resolution (`0.3.3`)

- **Helm Chart Bump**: `deploy/helm/tracescope/Chart.yaml` bumped to `version: 0.3.3` and `appVersion: "0.3.3"`.
- **Global Helper**: `deploy/helm/tracescope/templates/_helpers.tpl` added `tracescope.globalImageTag` helper.
- **Templates**: All component workloads (`storage-statefulset.yaml`, `ingest-deployment.yaml`, `agent-stats-deployment.yaml`, `ui-deployment.yaml`) default to the global image tag (`global.image.tag: "0.3.3"`).
- **Interchangeability**: Added explicit `command: ["uvicorn", "backend.ingest_main:app", "--host", "0.0.0.0", "--port", "8000"]` to `ingest-deployment.yaml` so the unified container runs any component role.

---

## 16. Build and Push Script Unified Image Tag Support (`scripts/build_and_push.sh`)

- **Root Cause Fix**: `scripts/build_and_push.sh` previously hardcoded `app-${VERSION}` and `ingest-${VERSION}` as tag suffixes, preventing creation of the base version tag `xhatsu101/tracescope:0.3.3` that Helm expects under `global.image.tag: "0.3.3"`.
- **Unified Build Target**: Main App build target (`--target api`) now tags both `xhatsu101/tracescope:0.3.3` and `xhatsu101/tracescope:app-0.3.3` (`-t $GLOBAL_IMAGE -t $APP_IMAGE`) and pushes both.
- **Flags Added**:
  - `--unified-only` (`-u`): Builds and pushes only the unified application image (`:0.3.3` and `:app-0.3.3`).
  - `--ingest-only`: Builds and pushes only the standalone ingest image (`:ingest-0.3.3`).
- **POSIX Compliant**: 100% standard POSIX `/bin/sh` syntax.
- **Verification**: Verified via `--dry-run` across all flag permutations and automated regression tests in `tests/test_deployment_topology.py` (27/27 passed).

---

## 17. Investigation Model UUID Parsing & Anomaly API Endpoints

- **Pydantic Strict Mode Fix**: Added `_coerce_uuid` validator to `InvestigationCreate.retry_of` (`backend/app/models/investigation.py`) so string UUIDs sent in HTTP JSON payloads are cleanly converted to `uuid.UUID` objects without raising strict model `ValidationError`.
- **Deduplication Behavior**: Without `retry_of`, `POST /api/v1/investigations` returns the existing cached run (`reused: true`). Supplying `retry_of: "<prev-run-id>"` initiates a new execution attempt with `retry_index = 1`.
- **Endpoints**:
  - Snapshot: `GET /api/v1/investigations/source?kind=anomaly_event&id=<id>`
  - Create/Retry: `POST /api/v1/investigations`
  - Get Status: `GET /api/v1/investigations/<run_id>`
  - History: `GET /api/v1/investigations?kind=anomaly_event&id=<id>`
- **Verification**: 14/14 LLM investigation unit tests passed; full test suite (168 tests) passed.


