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
  - Detectors: Traffic spike (`traffic_spike`), traffic drop (`traffic_drop`), latency shift (`latency`), error rate increase (`error_rate`), new service relationship (`new_service_edge`), new principal relationship (`new_principal_edge`), unusual access (`unusual_access` / "Truy cập Bất thường"), unusual execution time (`unusual_time`), and source IP behavioral anomalies (`user_new_source_ip` / `ip_new_user`).
  - Incident blast-radius analysis (upstream callers, affected principals/operations) and deterministic root-cause heuristic origin.
  - Serves fast analytics dashboards via FastAPI and an interactive React/TypeScript frontend.
- **Storage Invariant**: OTel trace data from application services is stored in Elasticsearch (`tmp-elk-svc`) with a strict **7-day maximum retention** policy enforced via ILM policy (`tracescope-7day-retention` and override of `apm-rollover-30-days` with delete phase after 7 days) and worker background asynchronous pruning (`_delete_by_query` on `@timestamp < now - 7d`). ClickHouse trace data copied for worker SQL calculations enforces a strict **1-day TTL** (`TTL toDateTime(intDiv(timestamp_ms, 1000)) + toIntervalDay(1)` via Migration 009). This ensures both ClickHouse and Elasticsearch disk usage stays strictly bounded and minimal, while Elasticsearch serves multi-tier span waterfalls on `/traces/:id` up to 7 days.
- **Root Directory**: `/home/ubuntu/Viettel/OtelTrace`
- **Active Storage**: Application APM traces are read from Elasticsearch (`http://127.0.0.1:32073`); ClickHouse (currently reached at `10.105.101.253:8123`) holds worker metric buckets and other derived data. `run_server.sh` defaults analytics to `OTEL_STORAGE_BACKEND=clickhouse` and Trace Explorer to `OTEL_TRACE_STORAGE_BACKEND=elasticsearch`. Set the latter to `clickhouse` explicitly for an offline ClickHouse trace testbed. `OTEL_ES_URL` alone configures the ELK connection but does not select the trace read backend.
- **Helm ELK Wiring**: The chart keeps analytics on ClickHouse, uses `storage.traceBackend=elasticsearch` for raw trace reads, and defaults worker ELK requests to `http://tmp-elk-svc.tmp-elk.svc.cluster.local:9200`. `elasticsearch.enabled=false` clears the URL passed to the worker. Helm release `tracescope` is now revision 27 with this configuration; the app/worker pod is healthy and the worker is materializing ELK metrics into ClickHouse.
- **Active Dashboard Port**: `0.0.0.0:30102` (lifecycle-script default and current listener).
- **NetworkTracing Hub Port**: `0.0.0.0:30102` (OTLP / Ingest Hub in `~/Viettel/NetworkTracing`).
- **Ingest NodePort**: `http://<node-ip>:30103/api/ingest` (Plain HTTP / non-SSL NodePort entrypoint for legacy C++ shippers such as `nt-ship-cpp` / `nt-sniff-cpp`; verified on public node `129.150.59.233:30103`).
- **Ingress HTTP NodePort**: `http://<node-ip>:31561` (Cluster Ingress-Nginx plain HTTP NodePort routing `/api/ingest`, `/api/agent/stats`, `/api`, and `/` without TLS; verified on public node `129.150.59.233:31561`).
- **Cluster APM & Elasticsearch Services**:
  - `tmp-elk-svc` (NodePort `9200:32073/TCP`, ClusterIP `10.97.180.119:9200`): Elasticsearch 7.17.24 holding APM indices (`apm-*-transaction-*`, `apm-*-metric-*`, `apm-*-span-*`, `apm-*-error-*`). Wired directly to `tracescope-worker` and dashboard on `http://127.0.0.1:32073`.
  - `apm-server` (NodePort `10.99.87.70:8200` -> NodePort `32765`): Ingestion gateway daemon streaming APM data into Elasticsearch.
- **Lightweight Monitoring Stack (`light-mon`)**:
  - Namespace: `monitoring`
  - Release: `light-mon` (Chart: `prometheus-community/kube-prometheus-stack` via Helm with `--skip-crds -f values-lightweight.yaml`, Revision 5)
  - Configuration: `values-lightweight.yaml` (ephemeral emptyDir, 2d retention, Alertmanager/nodeExporter/kubeStateMetrics disabled, Grafana NodePort `32080` with admin/admin, `additionalScrapeConfigs` scraping `https://trace.n2d.id.vn:443/metrics`).





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
    - `GET /api/v1/topology/bandwidth`: Byte-aware system or filtered bandwidth rate and five-minute series for the dashboard, read from worker-owned `metric_buckets` in both storage modes. The worker materializes byte totals in both 1-minute and 5-minute buckets.
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
  - `trace_repository.py` & `elasticsearch_trace_repository.py`: Normalized trace batch insert, query, and search. `list_traces` filters out non-trace metric documents and requires `trace.id`, preventing unresolvable synthetic IDs from appearing in the UI. `get_trace` includes `_id` fallback in search.
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
  - `normalization.py`: Normalizes OTel / ELK payloads, extracts canonical `enduser.id` / `labels.enduser.id` / `user.id` as principal username, derives trusted IP / proxies, extracts WSSE usernames with case preservation, sets canonical `operation_key` (`Service/operation`), and maps decoupled `auth_result` / `auth_evidence`.
  - `aggregation.py`: Computes 60s and 300s rollups with exact p50/p95/p99 percentiles.
  - `baseline.py`: Computes rolling median and MAD across dimensions.
  - `anomaly_detection.py`: Detectors: traffic_spike, traffic_drop, latency, error_rate, new_service_edge, new_principal_edge, unusual_access (behavioral shift by learned user or IP accessing a new endpoint never seen in baseline, or 401/403 authorization failure bursts without hardcoded strings), unusual_time (off-hours activity for established accounts), and user_new_source_ip / ip_new_user.
  - `blast_radius.py`: Recursive caller traversal and impact calculation.
  - `root_cause.py`: Probable origin heuristic.
  - `principal_extractor.py`, `principal_relationships.py`, `principal_profile.py`, `principal_baseline.py`, `principal_change_detector.py`, `principal_graph.py`, `principal_analytics.py`: incremental credential-behavior derivation from the existing sanitized `traces` table.
- **Maintenance & Migration Scripts** (`backend/scripts/`):
  - `generate_10day_demo_dataset.py`: Generates a complete 10-day dataset with 13 enterprise personas and randomized abnormalities; writes request/response byte totals and sample counts into both 1-minute and 5-minute `metric_buckets`, plus 5-minute interactive topology relationship rollups and ClickHouse trace retention.
  - `rebuild_aggregates.py`: Recomputes all rollups, edges, baselines, and detects anomalies.
  - `import_json.py`: Imports NDJSON, JSON arrays, and Elasticsearch hits.
- **Lifecycle Script** (`run_server.sh`):
  - `./run_server.sh {start|stop|restart|status}` managing tmux sessions `tracescope-30102` and `tracescope-worker`.

### Frontend (`frontend/`)
- **Tech Stack**: React 19, Vite, TypeScript, Tailwind CSS, TanStack Query, Recharts, HTML5 Canvas.
- **Design System & Typography**: Clean, matte, non-glossy glanceable observability monitor design system.
  - Typography: 100% standard font scaling, 12px Recharts axis ticks, crisp typography hierarchy.
  - Surfaces: Grafana-style matte canvas (`#0b0c0e`), panels (`#111217`), raised controls (`#181b1f`), compact side rail (`#111217`).
  - Zero Glossy Effects: Eliminated all `radial-gradient` ambient sheens, `backdrop-blur` frosted glass filters, and glowing `shadow-[0_0_...` neon halos.
  - Borders: Crisp, flat borders `#2a2d30` with stronger control borders `#34373b`; no card shadows.
  - Multi-Accent Palette:
    - Healthy / successful: Green (`#73bf69`).
    - Primary telemetry / informational: Blue (`#5794f2`).
    - Warning / elevated: Orange (`#ff9830`).
    - Failure / critical: Red (`#f2495c`).
    - Secondary series: Purple (`#b877d9`); baseline/grid: muted gray (`#303236`).
    - Entity identity accents are separate from status: User/Credential lavender (`#b877d9`), Service blue (`#5794f2`), API teal (`#56b9a8`), and IP neutral gray (`#a7a9ab`). Use them only on relationship labels, icons, paths, topology nodes, and selected entity context; operational status colors remain independent. For non-human principals, the primary call path is `Caller Service → Target Service → API / Operation`, with the observed credential attached as evidence on that call rather than drawn as the initiating actor. Only confirmed human principals may be presented as a User actor. Color alone must never carry role meaning, and related Trace evidence is required to confirm exact causality or credential forwarding.
  - Multi-Color Visualizations: Restrained low-opacity fills, compact legends, HTTP status mapping (2xx green, 3xx blue, 4xx orange, 5xx red), and semantic topology nodes/edges without specular sheen.
- **Built Output**: `frontend/dist` served directly by FastAPI on port 30102.
- **Navigation & Pages**:
  - `Overview` (`/`): Dense Grafana-style operational layout with 6 top health KPIs (TPS, Error rate, Bandwidth, P95 latency, Active users, and Services) equipped with sparklines and secondary telemetry (avg/peak TPS, peak error %, avg/peak bandwidth, p50/p99 latency, active users now, and registered services), Row 2 with an expanded Total TPS chart beside a taller consolidated Important changes panel (Critical, Attention, and Changed counters plus up to 6 recent episodes in an internally scrollable list), and Row 3 with Top Services and Top Users tables. Redundant separate bottom Recent Changes and Change evaluation panels eliminated.
  - `Topology` (Legacy `/topology`): Redundant generic service topology removed from primary navigation; redirects cleanly to `/users`. User access topology is served within the user workspace at `/users/:principal/topology`.
  - `Changes` (`/changes`, `/changes/:id`): Unified operator model over service anomaly signals and User behavior-change signals. Detector facts are correlated into episodes, then evaluated separately as `EXPECTED`, `CHANGED`, `NEEDS ATTENTION`, or `CRITICAL`. Legacy `/anomalies` and `/anomalies/:id` routes redirect into this experience. Every global episode card exposes `View details` and `Investigate`; Investigate opens the episode detail directly at its LLM investigation section. Detail pages include metric diff, relationship path, timeline, evidence, abnormality reasons, Trace links, operator decisions, and the LLM investigation UI.
  - `Services` (`/services`, `/services/:name`): Service catalog, operation percentiles, caller graphs, and instances. Service Detail places compact clickable KPI cards above a configurable TPS line chart; selecting Requests, Error rate, P95 latency, or Bandwidth overlays its available series while TPS remains plotted. The shared KPI card and TPS chart labels follow the User Activity style, and bandwidth uses its measured bucket series.
  - `Principals` (`/principals`, `/principals/:name`): Identity behavior explorer, target services, operations, callers, and hourly activity profiles.
  - `Traces` (`/traces`, `/traces/:id`): Trace explorer with filters and multi-tier interactive waterfall visualization.
  - `User Intelligence`:
    - `User Directory` (`/users`): Searchable principal inventory with live stats, risk level badges, sort controls, and launcher into user workspace.
    - `User Workspace & Layout` (`/users/:principal`): Compressed 2-row Grafana-style sticky header saving 100-150px vertical height above the fold, featuring identity, environment, active/baseline/behavior-state badges, inline metrics ribbon (`Requests`, `Services`, `APIs`, `Callers`, `IPs`, `Window`), compact `Switch ▾` account button, and embedded `Activity` / `Changes` navigation tabs:
      1. `Activity` (`/users/:principal/activity`): Dense User activity workspace with an integrated `Behavior | Access` segmented control. Behavior has 4 clickable KPI Stat panels (TPS, Error rate, P95 latency, Bandwidth) and a TPS vs Baseline chart that always retains both TPS lines. Clicking another KPI overlays its configured metric lines on a permanently reserved right axis; clicking TPS clears the overlay while right-side TPS values remain visible. The plot bounds and TPS path do not shift across selections, and the TPS scale runs from zero to the actual positive peak of its plotted series, including fractional peaks below 1 TPS (with a 1 TPS fallback only for all-zero data). Dense TPS windows keep the original worker five-minute metric buckets for data/state logic while the line chart renders at most 450 source points using min/max-preserving selection; lines are linear with animation disabled. The hover readout maps the cursor time back to the nearest original five-minute bucket. Missing bandwidth bytes leave the chart on TPS without a warning beneath it. A 100% non-error versus failed request outcome chart sits beside it on wide screens, and the active-hour heatmap occupies the row below. Hovering either chart updates a shared time-bucket readout with worker aggregate metrics and outcome counts. The former Baseline-vs-current and Normal Footprint panels were removed. Access uses an optimized 3-column `Selected IP (25%) → Service (35%) → API (40%)` board titled `Access for {principal}`, with the selected principal retained in context and Caller Service evidence appearing in the selected relationship panel when worker IP rollups exist.
      2. `Changes` (`/users/:principal/changes`): Episode-based change view with a consistent Needs attention / All / Reviewed workflow and compact readable cards. `/users/:principal/changes/:episodeId` is the single investigation surface: deterministic summary, before-vs-now comparison, timeline, evidence, related Trace link, inline LLM analysis, and source-scoped operator decisions in one vertical flow. Evaluation state (`Changed`, `Needs attention`, `Critical`) is displayed separately from workflow state (`Open`, `Monitoring`, `Resolved`). The former `/users/:principal/investigations` route is a compatibility redirect into Changes or the selected Change detail AI section.
    - Global Feeds & Analytics: `/user-changes`, `/user-graph`, `/user-analytics`, `/incidents`.
  - `Infrastructure`: `Agent Fleet` (`/agent-stats`) and `Agent Drilldown` (`/agent-stats/:node`) with interactive time-series dashboards.
  - **TPS chart invariant**: `/services`, `/services/:name`, API detail routes, and every `/users/:principal/*` workspace route render scoped TPS first. Activity satisfies this through its default Behavior segment; Access is the only separate internal view on the same route. Activity's worker metric buckets expose non-error and failed request counts for its percentage view.
  - Global Search in header: Search services, principals, or jump directly to trace waterfall by ID.
  - **Localization (i18n)**: Canonical Vietnamese UI copy across active pages, charts, tables, cards, and modals with persistent language switcher (`🇻🇳 VI` / `🇬🇧 EN`) defaulting to Vietnamese. DevOps/product vocabulary remains English where it improves operator recognition (`Service`, `API`, `User`, `TPS`, `Latency`, `Trace`, `IP`, `Baseline`, `Agent`, and protocol/database names); surrounding explanatory copy is translated.

---

## 3. Rules & Operational Guidelines
- **Rule xHatsu**: Always start responses with `"I HAVE FOLLOW THE RULE xHatsu DEFINED FOR ME BY DEFAULT"`.
- **POSIX Shell**: Strictly POSIX `/bin/sh` compliant. Never use bashisms (`[[ ]]`, `local`, `declare`, `array[i]`, `&>`, etc.).
- **Timers**: Set a schedule timer before executing fast commands to detect/prevent freezing.
- **Kubernetes**: NEVER execute any `kubectl` command.
- **Testing**: Always test API endpoints and scripts to confirm functionality across cases.
- **State Management**: Keep `AGENTS.md` and `STATE.md` updated with system state, access instructions, and guides.

---

- **Test Suite**: 197/197 tests passed in an isolated temporary-database harness (`.venv/bin/python -m pytest tests/ -q`); production data is never mutated by tests:
  - Canonical `enduser.id` extraction from Elasticsearch APM documents across top-level, nested, labels, attributes, and search fields (`tests/test_elk_enduser_normalization.py`).
  - Worker metrics exposure via `/metrics` Prometheus endpoint (`tests/test_prometheus_metrics.py`).
  - F5 BIG-IP unresolved IP handling without guessing client IP (`observed_ip = F5 IP`, `effective_client_ip = "unavailable"`, `ip_resolution = "load_balancer_unresolved"`), with explicit infrastructure IP categorization (`known_f5`, `known_lb`, `known_reverse_proxy`, `known_nat`) and suppression of IP behavioral signals on LBs (`tests/test_f5_lb_normalization.py` and `tests/test_user_ip_anomalies.py`).
  - Anonymous Traffic Isolation (`user = -anonymous-`): isolated from user directory, user baselines, user risk scoring, and active accounts, while retaining 100% telemetry volume for TPS, RPS, latency, and capacity (`tests/test_user_ip_anomalies.py`).
  - Detection of unauthorized / sensitive unusual access patterns (`unusual_access` / "Truy cập Bất thường") in `tests/test_user_ip_anomalies.py`.
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
  - Change episode evaluation and aggregation tests (`tests/test_changes_episode_evaluation.py`).
  - All 22 code review findings verified and documented in `FIX_REPORT.md`.
- **End-to-End Curl & JS Safety Test Suite**: 50/50 tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - Tested all 21 SPA routes (including `/changes`, `/agent-stats`, `/agent-stats/:node`, and user workspace sub-routes) with HTTP 200 and valid HTML shell bundle delivery.
  - Tested 29 backing APIs against frontend TypeScript contracts via `backend/scripts/validate_js_safety.py` and curl.
  - 0 JavaScript crash risks identified (zero undefined `toFixed`, `length`, or `map` vulnerabilities).
- **Frontend Lint/Build**: Passed (`tsc -b && vite build` built in 10.9s with 0 errors).
  - Design tokens (`--canvas: #0b0c0e`, `--surface: #111217`, `--surface-raised: #181b1f`, `--border: #2a2d30`, `--border-strong: #34373b`, `--grid: #303236`, `--blue: #5794f2`, `--green: #73bf69`, `--orange: #ff9830`, `--red: #f2495c`, `--radius-panel: 3px`) implemented across all components.
  - Application Shell: compact rail (Dashboard, Explore [Services, Users, Topology], Changes, Investigate [Traces], System [Agent Fleet]), dynamic `TraceScope / {Current Entity}` header, global search, and explicit Refresh button.
  - User Overview tab: TPS vs Baseline (1.6fr) beside 2x2 KPI grid (1fr: Requests, Bandwidth, Error Rate, P95 Latency), Important Changes episodes, paired Error/Latency charts, Bandwidth time series, and Source IP evidence table. Standalone TPS chart removed from Overview.
  - Global Dashboard (`Overview.tsx`): 1. Health KPI summary strip, 2. Main TPS chart beside "What changed", 3. Top Services & Top Users tables, 4. Recent Changes episodes.
  - ServiceDetailPage & ApiDetailPage: Structured operational layout (Header, TPS vs Baseline, Health metrics, APIs/Operations, Users, Latency/Errors, Dependencies, Changes episodes, Representative Traces).
- **Playwright Real Browser E2E Suite**: 15/15 pages passed (`python3 backend/scripts/test_pages_playwright.py`).
  - Headless Chromium navigated to all 15 existing and User Intelligence SPA routes.
  - Full React hydration, query resolution, and visual canvas/chart rendering verified.
  - 0 unhandled `pageerror` exceptions, 0 React render crash boundaries, and 0 console error failures.
- **Port 30102 Status**: Online and healthy, listening on all interfaces (`http://0.0.0.0:30102`).
- **High-TPS Hub Deployment (2026-09-11)**: Bounded/coalescing writer is active on `:30102`; live ingestion status reported `writer_alive=true`, queue `0/256`, successful durable commits, zero failed requests, and atomic duplicate replay. Full isolated test suite passed 74/74 and the live curl/JavaScript contract suite passed 42/42 after deployment.
- **Testbed State**: Cleanly wiped testbed state via `backend/scripts/reset_testbed.py`. ClickHouse analytical tables (0 traces, 0 metric buckets, 0 principals, 0 anomalies) and Elasticsearch APM indices (`apm-*`) reset to clean state ready for new ingestion. System telemetry logs truncated. Dashboard online and healthy on port 30102.
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
- **Unauthenticated Traffic (`-anonymous-`) Architecture & Codex Review Guide**: Saved in [`docs/PLAN_ANONYMOUS_USER_HANDLING.md`](file:///home/ubuntu/Viettel/OtelTrace/docs/PLAN_ANONYMOUS_USER_HANDLING.md) and [`docs/GUIDE_PLAN_CODEX_REVIEW.md`](file:///home/ubuntu/Viettel/OtelTrace/docs/GUIDE_PLAN_CODEX_REVIEW.md).
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
- **Topology API Connection Focus**: The topology canvas renders service-to-service wires by default. Selecting an expanded API overlays only that API's observed caller-service connections; clearing the selection or selecting another object removes those contextual API wires. The bounded endpoint is `GET /api/v1/topology/services/{service}/api-connections?api=...`.
- **Topology Fast Travel Search**: The full-page topology search finds services, APIs, and users across the seven-day slider horizon. Choosing a result jumps to its latest five-minute observation, expands its ancestry, centers the canvas card, and opens the matching detail inspector.
- **Topology Selection Layering**: Selected topology cards are promoted above all other canvas cards, while selected relationship wires render last in the SVG layer so overlapping objects do not obscure the active selection.
- **JavaScript Safe Integer Precision & Anomaly ID Guard**:
  - `deterministic_anomaly_id` (`anomaly_repository.py`) uses `(raw_hash % 9_000_000_000_000_000) + 1` to guarantee newly generated anomaly IDs strictly fit within JavaScript `Number.MAX_SAFE_INTEGER` ($2^{53} - 1 = 9,007,199,254,740,991$), preventing IEEE-754 precision loss and trailing-zero rounding in web browsers.
  - `get_anomaly`, `update_status`, and `anomaly_users` implement automatic float64 ULP tolerance fallback ($\pm 4096$) for any IDs $> 9 \times 10^{15}$, ensuring legacy or bookmarked URLs resolve accurately.
  - Database reset executed via `backend/scripts/reset_testbed.py` (truncated ClickHouse analytical tables, deleted Elasticsearch APM indices, truncated system telemetry logs).
- **Behavioral Change Events Deduplication (`principal_change_events FINAL`)**:
  - Enforced ClickHouse `FINAL` modifier across all `principal_change_events` queries in `UserRepository` (`list_changes`, `summary`, `analytics`, `service_users`, `graph`), ensuring `ReplacingMergeTree` collapses duplicate rows inserted across periodic micro-batches.
  - Added client-side defensive deduplication by fingerprint/key in `UserChangesTab.tsx`.
- **24-Hour Authentic PCAP Dataset Ingestion to ELK & ClickHouse (2026-09-17)**:
  - Tool: `/home/ubuntu/Viettel/Data/generate_pcap_to_elk.py`
  - Ingested 25,000 authentic transaction documents directly into Elasticsearch NodePort `:32073` (`apm-7.17.24-transaction-000001`, 8.9 MB) derived from production PCAP captures (`tcpdump_10.240.147.249.pcap` & `tcpdump_10.240.147.247.pcap`).
  - Realistic Gaussian latency distributions (p50: 25ms-120ms, p95: 80ms-220ms), authentic PCAP identities (`cm2.0`, `sale`, `myViettel`, `vtp`, `chatbot`, `cc2.0`, `product`, `cyber_space`, etc.), realistic status codes (97.5% 200, 1.5% 4xx, 1% 5xx), and 4 realistic scenarios (payment tail latency degradation, sale service traffic spike, product service error rate surge, novel caller/principal switch).
  - Streamed into ClickHouse `traces` (25,073 rows), 46,831 metric buckets (1m and 5m), 2,726 baseline metrics, 6,940 principal baselines, 121 principal change events, 16 security incidents, and 168 detected behavioral anomalies.
  - Verified with 100% pass on curl & JS contract safety test suite (48/48 tests passed across all 20 SPA routes and 28 backing APIs).
- **Anomaly Detail Incident Time Horizon Line Graph Fix (2026-09-18)**:
  - Fixed blank/missing line chart on `/anomalies/:id` (e.g. anomaly `6130971176347858`).
  - Backend `GET /api/v1/anomalies/{anomaly_id}` now accepts time range query parameters (`from`, `to`, `start`, `end`), allowing custom inspection windows matching global time picker filters.
  - Backend enriches `series` points with canonical millisecond `timestamp_ms` (`bucket_start * 1000`), computed `rps` / `tps` (`requests / 60.0`), `actual` values mapped according to anomaly metric type (latency p95, error rate %, or rps/tps), and `expected` baseline values.
  - Frontend `Anomalies.tsx` AnomalyDetailPage passes global filter time parameters to the query and maps `chartData` with defensive fallbacks (`timestamp_ms`, `requests`, `rps`, `p95_ms`, `http_5xx_rate`, `actual`, `expected`).
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
  - Pytest Suite: 197/197 tests passed across all test modules in `tests/` in an isolated test database harness (`test_pytest_<id>`).
  - End-to-End Curl & Safety Suite: 50/50 checks passed (`sh backend/scripts/curl_test_all_pages.sh`), covering all 21 SPA routes and 29 backing API endpoints with 0 JavaScript crash vulnerabilities.
  - Active Testbed Dataset: Clean 10-user enterprise hybrid dataset (184,896 historical 1m & 5m metric buckets injected directly for Days 0–23, 8,489 full raw traces for the active 7-day window synchronized across Elasticsearch `apm-7.17.24-transaction` and ClickHouse `traces`, 2,382 baselines, 145 anomaly events, 570 behavioral change events, 10 distinct user identities with dedicated abnormalities). Generated via `backend/scripts/generate_30day_demo_dataset.py`.

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
  2. `Activity & Performance` (`/users/:principal/activity`): *“Which Services used this identity, what did they call, and how did that traffic behave?”* — TPS vs Baseline first, compact operational KPIs, service-first relationship table and API drilldown, paired latency/status charts, with IP and normal-pattern data as secondary evidence.
  3. `Access & Topology` (`/users/:principal/topology`): *“Where was this principal observed?”* — IP-scoped relationship explorer whose primary call path is `Caller Service → Target Service → Operation`; a non-human principal is displayed as an observed credential attached to the call, while a confirmed human principal remains a User identity.
  4. `Behavior Changes` (`/users/:principal/changes`): *“What is different from the user’s normal behavior?”* — Deviation-only behavioral shifts, before vs now category distribution bars, and 7-questions explainability timeline.
  5. `Usage Patterns` (`/users/:principal/patterns`): *“When and how does this user normally operate?”* — 24h × 7d activity heatmap, target services distribution bars, operations distribution bars, and behavioral scope time series.
  6. `Anomalies & Investigations` (`/users/:principal/investigations`): *“What needs investigation?”* — Triage queue, trigger hypotheses, BEFORE vs NOW metrics comparison table, causal relationship chain, and operator review controls.
- **Supporting Attribution Signal Architecture (IP as Context)**:
  - **Core Model**: The telemetry aggregation key remains `principal × caller × target × operation`, but the UI must not imply that every principal initiated the request. For service/system/shared/integration credentials, show `Caller Service → Target Service → Operation` as the primary call path and attach the credential as observed authentication context. For `principal_type=human`, the principal may be labeled User. Exact propagation claims require supporting Trace evidence.
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

---

## 18. OpenTelemetry Collector Telemetry Metrics Schema Migration Fix

- **Issue**: OTel Collector Contrib pod failed during startup with:
  `'migration.MetricsConfigV030' has invalid keys: address, no need for metrics`
- **Root Cause**:
  1. OpenTelemetry Collector schema migration `MetricsConfigV030` deprecated `service.telemetry.metrics.address` in favor of Prometheus pull `readers`.
  2. Unquoted / uncommented text `no need for metrics` inside YAML dictionary was parsed as an invalid mapping key.
- **Resolution (`/home/ubuntu/agy/otel-obi/otel-collector.yaml`)**:
  - Replaced legacy `address: 0.0.0.0:8888` with valid schema:
    ```yaml
    service:
      telemetry:
        logs:
          level: info
        metrics:
          readers:
            - pull:
                exporter:
                  prometheus:
                    host: 0.0.0.0
                    port: 8888
    ```
  - For disabling collector internal metrics, use `level: none`.

---

## 19. Prometheus Exposition Metrics from Web Services

- **Module**: `backend/app/services/prometheus_metrics.py`
  - In-memory thread-safe `PrometheusMetricsRegistry` with pure ASGI `PrometheusMiddleware`.
  - Exposes standard web application metrics at `GET /metrics`:
    - `http_requests_total{method, handler, status}`: Request count per HTTP method, route, and status code.
    - `http_request_duration_seconds_bucket{method, handler, le}`: Latency histogram with standard duration buckets (`0.005` to `10.0s` and `+Inf`), plus `_sum` and `_count`.
    - `http_requests_in_progress`: In-flight active request gauge.
    - Process metrics: `process_resident_memory_bytes`, `process_cpu_seconds_total`, `process_start_time_seconds`, `process_uptime_seconds`.
    - Service info: `tracescope_service_info{version="0.3.3", role="...", backend="..."}`.
    - Ingest writer metrics: `tracescope_ingest_writer_queue_depth`, `tracescope_ingest_writer_alive`, `tracescope_ingest_writer_committed_total`, etc.
- **Cadence & Worker Integration**:
  - Web requests only update in-memory request counters and latency histograms.
  - Heavy database metrics (`total_spans`, `nodes_reporting`, `c_2xx`, `c_err`, `users_rpm`, `open_anomalies`) are **ONLY updated once per cycle by `backend.worker`** (`update_prometheus_metrics` stage).
  - Snapshot is saved to ClickHouse `checkpoints(source='worker_prometheus_metrics')` and `/tmp/tracescope_worker_metrics.json`.
  - Scraping `GET /metrics` never queries ClickHouse aggregations directly, serving the precomputed snapshot in microseconds.
  - Exposes `tracescope_worker_last_run_timestamp_seconds` and `tracescope_worker_cycle_duration_seconds`.
- **Verification**: Dedicated test suite in `tests/test_prometheus_metrics.py` (6/6 passed); worker integration verified via `python -m backend.worker --once`; full regression test suite passed (178/178 passed).

---

## 20. 30-Day Multi-Persona Demo Dataset & Behavioral Anomaly Cases

- **Generator Script**: `backend/scripts/generate_30day_demo_dataset.py`
  - Generates 38,734 realistic transaction traces across 30 days (`2026-08-19` to `2026-09-18`) spanning 10 distinct user personas.
  - Dual ingestion: Indexed into Elasticsearch `apm-7.17.24-transaction` at `http://127.0.0.1:32073` with canonical `enduser.id` and inserted into ClickHouse `traces`.
  - Rebuilt rollups (33,092 1m buckets, 23,265 5m buckets), baselines (2,967 median/MAD baselines), anomaly evaluations (327 anomaly events), and principal behavioral derivations (7 incidents, 11 principals).
- **10 User Personas & Anomaly Cases**:
  1. `alice` (Steady Golden Baseline): 6,003 traces across 30 days. Clean reference account with 0 security incidents.
  2. `bob` (Candidate Promotion): 5,062 traces. Accesses `billing-service` on Days 20–29, promoted to established baseline. `unusual_access` detected on initial transition.
  3. `charlie` (Traffic Spike & Rate Surge): 2,673 traces. Sudden 1,200 req burst in recent window vs baseline ~100–200 reqs (`traffic_spike` & `PRINCIPAL_RATE_SURGE`).
  4. `david` (Traffic Drop / Outage): 11,514 traces. Collapses from 400 req/day to only 2 requests in recent window (`traffic_drop`).
  5. `eve` (Latency Shift & Blast Radius): 2,321 traces. Latency blowout on `payment-service` to 950ms–1800ms (`latency` shift).
  6. `frank` (Error Rate Surge): 3,000 traces. 45% 5xx Internal Server Errors on `order-service` (`error_rate` critical).
  7. `grace` (Target Fanout Surge & New Edges): 2,696 traces. Sweeps 5 new target services (`auth`, `billing`, `payment`, `inventory`, `notification`) in 45m (`new_service_edge`, `new_principal_edge`, `TARGET_FANOUT_SURGE`, `unusual_access` x22, incident score 40).
  8. `heidi` (Unusual Access & Credential Shift): 2,365 traces. Switches caller to `api-client` and executes administrative billing actions (`unusual_access`, `OPERATION_MIX_SHIFT`, `CALLER_PRINCIPAL_SWITCH`, incident score 70 - High).
  9. `ivan` (Off-Hours Night Activity & Novel IP): 2,098 traces. Off-hours activity at 02:00–04:30 UTC (`unusual_time`) and novel external source IP `194.26.29.11` (`user_new_source_ip`, incident score 35).
  10. `judy` (Auth Attack & Novel User on Known IP): 132 traces. Credential brute-force / auth failure burst (`AUTH_FAILURE_BURST` with 130+ 401s, then `FAILURE_THEN_SUCCESS` 200 OK login) and novel user on known internal IP `198.51.100.50` (`ip_new_user`, incidents scored 60 and 55 - High).

---

## 21. Pure TPS & Historical Baseline Chart Refactor (Overview Dashboard)

- **Backend Fix (`backend/repository.py`)**:
  - Resolved `baseline_rps` duplication bug in `dashboard_series` where `baseline_rps` was set to `rps`.
  - Now queries `baseline_metrics` (`rps_median`) grouped by `(hour_of_day, day_of_week)` matching active filter (`service`, `account`, `operation`, or system-wide sum across services).
  - Also enriches `dashboard_summary` with `baseline_rps` and `baseline_tps`.
- **Frontend Refactor (`frontend/src/pages/Overview.tsx` & `frontend/src/i18n.tsx`)**:
  - Converted "Tốc độ Lưu lượng Định danh & Tỷ lệ Lỗi" panel into a clean, dedicated TPS and Historical Baseline chart: "Tốc độ Thông lượng Định danh & Chuẩn Lịch sử".
  - Subtitle updated to "Thông lượng giao dịch theo bucket 60s so với chuẩn lịch sử".
  - Action header shows `TPS: {observed_tps} • Chuẩn Lịch sử: {baseline_tps}`.
  - Eliminated the 5xx error rate line and secondary right Y-axis.
  - Tooltip formatted strictly for TPS (`{val} tps`).
  - Verified across 48 automated curl & JS safety tests.

---

## 22. Smooth Time-Series Generation & Prometheus Baseline TPS Exposition

- **Smooth Timestamp Generation (`backend/scripts/generate_30day_demo_dataset.py`)**:
  - Replaced high-variance Poisson `random.uniform()` with `generate_smooth_timestamps()`.
  - Partitions target time ranges into 60-second intervals and applies profile weighting (`diurnal` half-sine bell curve for daytime, `ramp_up` for Charlie's surge and Judy's brute-force, `ramp_down` for David's collapse, `bell` for Ivan's off-hours).
  - Micro-spaces events evenly within each minute with sub-second jitter, producing smooth, continuous 60s bucket curves without random zero drops or jagged spikes.
- **Prometheus Exposition (`backend/app/services/prometheus_metrics.py`)**:
  - Added `tracescope_observed_tps` and `tracescope_baseline_tps` gauge metrics to `GET /metrics`.
  - Computed during periodic worker cycle (or on-demand snapshot) with historical fallback, serving instant in-memory responses with zero database load on Prometheus scrapes.

---

## 23. 7-Day & 30-Day Global Time Range Redesign & Multi-Grain Downsampling

- **Global Time Range Controls (`frontend/src/App.tsx`)**:
  - Expanded the segmented control in the top navigation bar from `1h`, `3h`, `6h`, `24h` to include **`7d` (168h)** and **`30d` (720h)**: `[{ label: "1h", hours: 1 }, { label: "3h", hours: 3 }, { label: "6h", hours: 6 }, { label: "24h", hours: 24 }, { label: "7d", hours: 168 }, { label: "30d", hours: 720 }]`.
  - Dynamic active state detection: `Math.abs(rangeHours - hours) <= 1` prevents sub-minute floating point discrepancies from de-selecting the active preset button.
  - Added descriptive title tooltips (`Last 7d`, `Last 30d` / `7 ngày qua`, `30 ngày qua`) and localized labels in `frontend/src/i18n.tsx`.
  - Dynamic Rollup Indicator Badge: Dynamically switches between `60s rollup` (`<= 36h`), `5m rollup` (`36h < range <= 192h`), and `1h rollup` (`> 192h`).
- **User Topology Tab Presets (`frontend/src/pages/user/UserTopologyTab.tsx`)**:
  - Expanded topology view time filter buttons to `["5m", "1h", "24h", "7d", "30d", "all"]`.
  - Wired `7d` to `extra.start = now - 7 * 86400_000` and `30d` to `extra.start = now - 30 * 86400_000`.
- **Backend Dynamic Downsampling (`backend/repository.py` & `backend/app/repositories/user_repository.py`)**:
  - `backend/repository.py:dashboard_series`:
    - Auto-scales aggregation grain based on time window duration:
      - `<= 36h`: 60-second buckets (`grain_sec = 60`), preserves high resolution for 1h/3h/6h/24h.
      - `36h < duration <= 192h` (7 days): 5-minute buckets (`grain_sec = 300`, `intDiv(bucket_start, 300) * 300`), returns ~500–650 points.
      - `> 192h` (30 days): 1-hour buckets (`grain_sec = 3600`, `intDiv(bucket_start, 3600) * 3600`), returns ~250–350 points.
    - Prevents 43,200 raw bucket transfer bottlenecks, ensuring instant, lag-free chart rendering on 7d and 30d views.
  - `backend/app/repositories/user_repository.py:performance`:
    - Auto-adapts `bucket_ms` based on query horizon: 1h buckets for `> 192h`, 5m buckets for `> 36h`, and 60s/300s buckets for shorter intervals.
- **Chart Date Formatting for Multi-Day Ranges (`Overview.tsx`, `UserOverviewTab.tsx`, `UserActivityTab.tsx`)**:
  - Added multi-day date detection (`rangeHours > 24`).
  - XAxis tick formatters display `M/D HH:mm` when viewing 7d/30d ranges instead of ambiguous repeated time-only strings (`HH:mm`).
  - Tooltips display full locale timestamp (`Month Day, Year HH:mm:ss`) for unambiguous investigation context.
- **Testing & Verification**:
  - Vite production bundle built cleanly (`npm run build` exited code 0).
  - All 48 curl and JavaScript safety tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - Verified 1h (60 points), 7d (627 points), and 30d (275 points) API series queries returning in sub-10ms.

---

## 24. Enterprise System Account Dataset & 100% Anomaly/Change Coverage

- **Database Clean Reset & Dual-Ingest Simulation**:
  - Script: `backend/scripts/generate_30day_demo_dataset.py`.
  - Wiped and re-indexed ClickHouse (`tracescope`) and Elasticsearch (`apm-7.17.24-transaction` on `127.0.0.1:32073`).
  - Transformed persona identities into realistic enterprise system/service accounts modeled after `~/Viettel/Data`:
    - `sys_erp_batch` (golden baseline diurnal jobs)
    - `api_gateway_sync` (candidate promotion to billing)
    - `svc_order_dispatcher` (traffic spike & rate surge)
    - `cron_reconciler` (traffic drop / complete service outage)
    - `paygate_settlement` (latency shift to 950ms+)
    - `billing_integrator` (45% 5xx server error rate surge)
    - `inventory_sync_worker` (target fanout surge across 5 microservices)
    - `sec_audit_collector` (unusual access & caller switch to CLI)
    - `infra_monitor_daemon` (off-hours night access & novel external IP)
    - `partner_b2b_client` (brute-force auth failure burst & novel user on known internal IP)
    - `legacy_backup_job` (dormant account reactivation after 25 days)
  - Trace Volume: 49,606 traces, 41,958 1m buckets, 14,281 5m buckets, 1,410 baselines.
- **100% Detector Coverage**:
  - **All 10 Anomaly Types** (`tracescope.anomaly_events`):
    1. `unusual_access`: 37 events
    2. `new_service_edge`: 25 events
    3. `new_principal_edge`: 22 events
    4. `unusual_time`: 20 events
    5. `traffic_drop`: 12 events
    6. `latency`: 4 events
    7. `error_rate`: 3 events
    8. `user_new_source_ip`: 2 events
    9. `traffic_spike`: 1 event
    10. `ip_new_user`: 1 event
  - **All 7 Behavioral Change Types** (`tracescope.principal_change_events`):
    1. `TARGET_FANOUT_SURGE`: 17
    2. `CALLER_PRINCIPAL_SWITCH`: 8
    3. `PRINCIPAL_RATE_SURGE`: 4
    4. `FAILURE_THEN_SUCCESS`: 2
    5. `AUTH_FAILURE_BURST`: 2
    6. `DORMANT_REACTIVATED`: 1
    7. `OPERATION_MIX_SHIFT`: 1
    (plus novelty detections: `NEW_RELATIONSHIP`: 35, `NEW_OPERATION`: 19, `NEW_TARGET`: 11, `NEW_CALLER`: 2, `NEW_SOURCE_IP`: 2, `USERNAME_FIRST_SEEN`: 1).
- **Anomaly Detail 24h Horizon & Time Toggles**:
  - Expanded `GET /api/v1/anomalies/{id}` with `window` parameter defaulting to 24h (`now - 86400`).
  - Added dynamic bucket sizing (`300s` for >12h horizons, `60s` for short horizons) and dynamic RPS calculation (`round(reqs / float(chosen_b_size), 3)`).
  - Frontend `frontend/src/pages/Anomalies.tsx`: Added interactive horizon toggle buttons (`1h`, `6h`, `24h`, `7d`) in panel action bar and date-time tick formatting (`MM/DD HH:mm`) on XAxis.
- **Defensive Float Sanitization (`NaN`/`Inf`)**:
  - Added `_clean()` helper in `backend/app/repositories/user_repository.py` to prevent ClickHouse `quantile(0.95)` from emitting `NaN` on 0-request outage windows, eliminating FastAPI 500 crashes.

---

## 25. Behavioral Scope Stability Redesign (Radar · Grouped Bar · Stability Trend)

- **Problem Addressed**:
  - The previous "Behavioral Scope Stability" component drew 4 overlapping stair-step lines (`stepAfter`) for integer dimensions (Targets, Operations, Callers, Source IPs) with small values (1 to 5) jumping on top of each other.
  - The chart was hard to read and did not clearly convey whether the identity was operating within authorized boundaries or performing privilege escalation.
- **Redesigned Multi-View Scope Component (`frontend/src/pages/user/UserPatternsTab.tsx`)**:
  - **Concept & Purpose**: Monitors the identity's credential footprint / scope envelope against its learned baseline across 4 dimensions: Target Services, Operations/APIs, Callers, and Source IPs. Protects against lateral movement, privilege escalation, and token hijacking.
  - **View 1: Radar Multi-Axis Chart (`scopeViewMode === 'radar'`, Default)**:
    - Recharts `<RadarChart>` rendering two overlapping multi-axis polygons:
      - **Historical Baseline**: Violet/Indigo shaded polygon (`#818cf8`) representing the learned normal perimeter.
      - **Observed Current**: Cyan (`#00f0ff`) or Amber (`#f59e0b`) polygon representing live observed scope.
    - An immediate glanceable visual: if Current is contained inside Baseline, the credential is strictly contained; if any axis extends outward, privilege expansion is detected.
    - Side-by-side **Stability Score Card** (`0% - 100%`) with containment badge (`ShieldCheck` for Contained / `AlertTriangle` for Expansion) and 4 dimension summary tiles showing baseline vs current numbers and delta tags (`+N new` or `Stable`).
  - **View 2: Grouped Bar Comparison (`scopeViewMode === 'bar'`)**:
    - Recharts `<BarChart>` displaying side-by-side bars for each of the 4 dimensions (Targets, Operations, Callers, Source IPs), comparing Baseline vs Current with clear numbers and distinct fills.
  - **View 3: Timeline Stability Trend (`scopeViewMode === 'timeline'`)**:
    - Recharts `<AreaChart>` with a single smooth gradient curve displaying the **Scope Stability Score (%)** over time with an 80% Safe Threshold reference line, completely replacing the 4 crisscrossing stair-step lines.
- **Testing & Verification**:
  - Vite production bundle built cleanly (`npm run build` completed in 19.1s).
  - All 48 curl and JavaScript safety tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - All 17 Playwright Chromium headless browser pages passed (`python3 backend/scripts/test_pages_playwright.py`) with 0 unhandled JS exceptions and 0 render errors on `/users/:principal/patterns`.

---

## 26. Unknown & Unauthenticated Users Traffic Monitor (`/unknown-users`)

- **Architecture & Rationale**:
  - Implements the architectural design from `PLAN_ANONYMOUS_USER_HANDLING.md`: Isolates `-anonymous-`, `unknown`, and empty principal traffic from human and service account directories and risk ranking algorithms, preventing pseudo-user risk score distortion while maintaining 100% telemetry visibility.
- **Backend API (`GET /api/v1/unknown-users` & `GET /api/v1/users/unknown-traffic`)**:
  - Method: `UserRepository.unknown_users_analytics(start_ms, end_ms, limit=50)`
  - Returns comprehensive unauthenticated traffic KPIs:
    - `total_requests`: unauthenticated transaction volume and `traffic_percentage` of total estate ingress.
    - Status code breakdown: 2xx success, 401/403 authorization failures (`auth_fail_rate`), and 5xx server errors (`error_rate`).
    - Latency: exact `avg_latency`, `p95_latency`, and `p99_latency`.
    - Probed surface: `unique_targets`, `unique_operations`, `unique_sources`.
    - Time-series buckets (`series`) correlating throughput with auth failure bursts.
    - Top target services, top probed endpoints, and top source IPs with infrastructure roles (Load Balancer, Client IP, Reverse Proxy).
    - Recent 50 unauthenticated traces with HTTP statuses and direct links to multi-tier trace waterfall.
- **Frontend Page (`frontend/src/pages/UnknownUsers.tsx` -> `/unknown-users`)**:
  - Navigation: Prominently added to SideNav under `Identity & Access` (`[UserX, "Unknown Users", "/unknown-users"]`).
  - Routing: Wired to `/unknown-users`, with automatic redirects for `/users/-anonymous-` and `/users/unknown`.
  - Header in `UserDirectory.tsx`: Added an amber badge link `[Unknown Users & Public Traffic]` leading directly to the monitor page.
  - Interactive features: Search filter by service, operation, or IP; quick status tabs (`All`, `Auth Fails (401/403)`, `5xx Errors`); one-click jump to Trace Waterfall inspector.
- **Testing & Verification**:
  - All 50 curl tests passed in `sh backend/scripts/curl_test_all_pages.sh` (100% JS contract safe).
  - All 18 real browser pages passed in `python3 backend/scripts/test_pages_playwright.py` with 0 console errors and 0 unhandled exceptions.

---

## 27. Enterprise System Accounts Dataset Regeneration & 100% Detector Verification (2026-09-18)

- **Identity Renaming & Realism**:
  - Replaced legacy account names with 11 authentic enterprise and telecom infrastructure system accounts:
    1. `telecom_sync_svc`: Steady Golden Baseline (Days 0-29, 100% normal health).
    2. `vtp_express_dispatch`: Candidate Promotion (Days 20-29 promoted to established baseline).
    3. `pos_checkout_terminal`: Traffic Spike & Principal Rate Surge (Sudden volume ramp to 200+ req/5m).
    4. `billing_reconcile_job`: Traffic Drop / Outage (Daily 02:00-04:00 batch completely collapses to 0 req).
    5. `interbank_settlement_gw`: Latency Degradation & Blast Radius (Payment latency blowup to 950ms on `PayService/chargeCard`).
    6. `partner_sales_broker`: Error Rate Surge & Caller Switch (45% 5xx server errors on order creation + CustomerService calls).
    7. `enterprise_b2b_gateway`: New Service Edge + New Principal Edge + Target Fanout Surge (Sweeps 5 services in 45m).
    8. `secops_monitor_agent`: Unusual Access + Operation Mix Shift + Caller Switch (Switches to api-client & billing APIs).
    9. `sysadmin_deploy_agent`: Unusual Time (Off-Hours Night Rogue Access) + User New Source IP (Active 02:00-04:30 UTC from 185.220.101.5).
    10. `mobile_miniapp_gateway`: Auth Attack (Failure Burst then Success) + IP New User (130+ 401s then 200 OK on host 172.16.10.45, baseline host user `worker_health_monitor`).
    11. `audit_compliance_worker`: Dormant Reactivated (Active Days 0-1, silent 27 days, reactivated on Day 29).
    12. `unknown` / `-anonymous-`: Unauthenticated Public Traffic & Auth Probes (Populates the Unknown Users Monitor with 1,634 transactions and 401/403 authorization probes).
- **Database Metrics & Ground-Truth Coverage**:
  - Database Volume: 51,348 traces, 43,616 1m buckets, 14,538 5m buckets, 1,304 baselines, 820 anomaly events, 399 principal behavioral change events.
  - 10/10 Anomaly Detectors Active: `unusual_access` (48), `new_service_edge` (25), `new_principal_edge` (19), `error_rate` (10), `latency` (6), `unusual_time` (5), `traffic_spike` (4), `traffic_drop` (4), `ip_new_user` (1), `user_new_source_ip` (1).
  - All Behavioral Detectors Active: `NEW_IP_CALLER_PAIR` (2981), `NEW_OPERATION` (90), `UNUSUAL_TIME` (79), `NEW_TARGET` (73), `NEW_RELATIONSHIP` (31), `NEW_SOURCE_IP` (19), `TARGET_FANOUT_SURGE` (18), `NEW_CALLER` (11), `CALLER_PRINCIPAL_SWITCH` (8), `PRINCIPAL_RATE_SURGE` (4), `AUTH_FAILURE_BURST` (4), `FAILURE_THEN_SUCCESS` (2), `DORMANT_REACTIVATED` (1), `USERNAME_FIRST_SEEN` (1), `OPERATION_MIX_SHIFT` (1).
- **Verification Suites**:
  - `sh backend/scripts/curl_test_all_pages.sh`: 50/50 tests passed (0 JS crash risks).
  - `python3 backend/scripts/test_pages_playwright.py`: 18/18 real browser pages passed in headless Chromium with 0 unhandled exceptions.
  - `.venv/bin/python3 -m pytest tests/ -q`: 188/188 unit & integration tests passed cleanly in temporary test databases.

## 28. Interactive Service Topology (2026-09-18)

- `backend/clickhouse_migrations/008_interactive_topology.sql` defines bounded five-minute/current service, API, principal, and principal/IP topology tables, plus normalized source-IP/attribution and request/response byte columns on sanitized trace rows.
- `backend/app/repositories/interactive_topology_repository.py` reads those derived ClickHouse tables in ClickHouse mode and uses bounded server-side Elasticsearch aggregations in ELK mode; it never adds application trace persistence to ClickHouse for an ELK topology request.
- Interactive API routes live under `/api/v1/topology/services`, `/api/v1/topology/services/{service}/apis`, `/api/v1/topology/services/{service}/apis/{api}/principals`, service/API/principal metrics, and cursor-paginated principal IPs. They expose operational metrics, direct/inferred evidence, confidence, anonymous attribution, and previous-window change indicators.
- The frontend `/topology` route is service-only initially, expands branches explicitly, keeps source IPs in the detail panel, and preserves node positions while loading child branches.

## 29. Full-Canvas Topology Interaction Redesign (2026-09-18)

- `/topology` now uses the complete route viewport as a matte grid canvas; the previous page header, graph card, reserved inspector column, and attribution card layout were removed.
- Time-window controls, graph legend, relationship change counts, and identity-attribution quality are compact floating canvas controls.
- The detail inspector is a floating right-side window rendered only after a node or edge is clicked; closing it or clicking blank canvas restores the unobstructed graph.
- Canvas navigation supports mouse-wheel zoom, explicit `+`/`-` zoom controls (50%-250%), primary-pointer drag panning, and reset by clicking the percentage or double-clicking blank canvas.
- Service, API, and principal node cards display TPS, p95 latency, error rate, and change state as vertically stacked label/value rows for faster scanning.
- Service, API, and principal cards can be dragged independently across an effectively unbounded grid; connection lines follow the moved cards and whole-canvas panning remains unrestricted.
- The floating node inspector includes a TPS-over-time line chart backed by ClickHouse five-minute series or bounded Elasticsearch date-histogram aggregation.
- The inspector TPS chart uses a smooth curve and fixed five-minute buckets across every observation window; longer windows never change the aggregation to hourly or multi-hour buckets.
- The topology range pills were replaced by a seven-day slider containing 2,016 selectable five-minute windows. Scrubbing previews the timestamp and releasing the pointer or keyboard key commits one exact five-minute topology snapshot.
- Sidebar links leaving `/topology` use a full route load to prevent React Router's in-memory location from retaining the old canvas after the browser URL changes; modified clicks still preserve normal browser behavior.
- The topology route owns exactly the available height below the global header. Its isolated stacking context remains below the persistent sidebar, so sidebar navigation stays clickable even while the topology inspector is open.
- Added Vietnamese strings for topology canvas actions and accessible labels.
- Verification: frontend TypeScript lint and production build passed; live `/topology` and `/api/v1/topology/services?window=24h` returned HTTP 200; the Playwright suite passed **18/18** pages with zero browser exceptions and now asserts zoom/reset, hidden-until-selection inspector behavior, and `/topology` to `/services` sidebar navigation.

## 30. Canonical Service/API/User/IP Investigation Model (2026-09-19)

- `Service` remains the highest-level operational entity; no additional System entity, resolver, rollup, or anomaly layer is introduced.
- The shared topology facts support both investigation directions without inverse duplicate tables: `Service -> API -> User -> IP` and `User -> Service -> API -> IP`.
- Principal-first interactive endpoints are `GET /api/v1/topology/principals/{principal}/services` and `GET /api/v1/topology/principals/{principal}/services/{service}/apis`; source-IP evidence continues through the existing bounded, cursor-paginated principal IP endpoint with service/API filters.
- The User Access & Topology tab uses progressive disclosure. It initially renders User and Service relationships, reveals APIs after service selection, and keeps IPs outside the default topology until an API is selected.
- Existing topology tables, legacy user topology APIs, service edges, principal profiles, baselines, and anomalies remain compatible; the inverse queries reuse `topology_principal_edges_5m` and `topology_principal_ip_5m`.

## 31. Persistent Light Theme (2026-09-19)

- The frontend keeps dark mode as the default and exposes a persistent light/dark toggle in the global header.
- Theme preference is stored in browser `localStorage` under `tracescope-theme`; the root `data-theme` and browser `color-scheme` are updated at runtime.
- Light mode remaps the established matte palette globally across the app shell, shared cards, controls, tables, text, borders, scrollbars, and Recharts axes/grids without duplicating page implementations.

## 32. Operational Dashboard Refresh (2026-09-19)

- The dashboard now presents four top cards: Total TPS, Total Users, Total Services with unhealthy-service count, and Abnormal Changes.
- The main charts are Total TPS, Error %, and a horizontal stacked abnormal-score distribution. Existing dashboard series and service/user endpoints are reused without backend changes.
- Bandwidth is intentionally shown as a frontend placeholder because the existing dashboard API does not expose request/response byte series. No API or backend schema was changed.
- Global range controls were replaced by a fixed five-minute-bucket / seven-day history view. Specialized anomaly and user-topology pages no longer expose alternate time-range selectors.

## 33. Service Detail Chart Contract Fix (2026-09-19)

- `/services/:name` now normalizes the existing service detail rollup response (`bucket_start`, `requests`, `errors`, `latency_p95`) into the frontend chart contract (`timestamp_ms`, `tps`, `p95_ms`, and error-rate fields).
- The service trend chart uses numeric time axes and displays a clear no-telemetry state instead of rendering an empty Recharts surface.
- This was implemented entirely in `frontend/src/pages/Services.tsx`; no backend or API response changes were made.
- Verification: `npm run build` passed and `git diff --check` passed.

## 34. Separate Service Trend Charts (2026-09-19)

- The service detail view now renders TPS and p95 latency as separate line charts with independent Y-axis scales; the combined dual-metric area chart was removed.
- Both charts reuse the normalized frontend series from the existing service endpoint. No backend/API changes were made.
- Verification: frontend TypeScript lint and production build passed.

## 35. Card Row Layout (2026-09-19)

- Larger panel/card sections now cap at two cards per row across the dashboard, service, account, anomaly, trace, agent, principal, user, topology, and unknown-user views.
- Compact KPI/info cards (for example Total TPS, Total Users, Total Services, and Abnormal Changes) use four cards per desktop row; larger cards and charts still wrap after two.
- Data tables and topology canvases retain their functional layouts.
- This is a frontend-only responsive layout change. Verification: TypeScript lint and production build passed.

## 36. Monitoring UI Refactor (2026-09-19)

- The primary `/` route now redirects to `/dashboard`; sidebar navigation is organized as Dashboard, Services, Users, Topology, Changes, Traces, and Agent Fleet. The legacy `/unknown-users` route remains available but is no longer a primary navigation item.
- The default dashboard is organized around status and change investigation: KPI summary, important changes, five-minute TPS/error/p95 trends over seven-day history, service/user hotspots, and secondary abnormal-score distribution. The unavailable bandwidth series was not fabricated and no backend/API contract was changed.
- Services use an operational table and service detail surfaces prioritized operations. A subordinate API drilldown route (`/services/:service/apis/:api`) reuses existing topology metrics, principal, and caller APIs and keeps the Service → API → User path intact.
- User workspace headers and tabs are compacted; important changes and new relationships are surfaced before detailed charts. Topology node cards and history controls are less dense while preserving lazy expansion and the inspector.
- The grouped anomaly view now leads with eight operational columns (severity, what changed, identity, service/API, current vs baseline, since/duration, status, actions), while raw findings and expandable incident slices remain available.
- Visible terminology uses “Unattributed Traffic” / “Identity Attribution” for unknown identity observations without changing backend semantics; explicit 401/403 authentication failures remain distinct.
- Changes are frontend-only. Validation completed with `npm run lint`, `npm run build`, and `git diff --check`; unrelated backend, test, and report files remain unstaged.

## 37. Service/API/User Bandwidth Backend (2026-09-19)

### Worker metric-bucket bandwidth (2026-09-23)

- The Elasticsearch metrics stage uses its `worker_elasticsearch_sync` checkpoint to paginate bounded six-hour windows across the retained seven-day source range. It writes both 60-second and 300-second buckets and refreshes the latest ten minutes during backfill.
- The Elasticsearch metrics stage writes grouped transaction counts, latency summaries, byte totals, and byte sample counts into worker-owned `metric_buckets` at both 60-second and 300-second grain. A byte-schema checkpoint version triggers one retained-window rebackfill after upgrading older buckets. With `OTEL_CLICKHOUSE_ONLY_AGENT_TRACES=true`, the stage skips raw Elasticsearch-to-ClickHouse sync entirely.
- `/api/v1/topology/bandwidth`, Overview, Services, API detail, and User Activity read byte totals from `metric_buckets`. Bandwidth is unavailable only when those buckets contain no measured byte samples.

- Service, API, and principal topology metrics now expose cumulative `request_bytes`, `response_bytes`, and `total_bytes`, plus explicit rates: `request_bytes_per_second`, `response_bytes_per_second`, `bandwidth_bytes_per_second`, and `bandwidth_bits_per_second`.
- Five-minute transaction series expose the same bandwidth fields for line-chart use. Both ClickHouse and Elasticsearch worker paths write and read these fields through `metric_buckets`.
- `GET /api/v1/services/{service}/bandwidth` provides a dedicated service bandwidth response with window totals and five-minute series. Existing service detail health includes the bandwidth totals/rates and a nested `bandwidth` payload.
- `GET /api/v1/users/{principal}/performance` now includes bandwidth fields per bucket, a top-level bandwidth summary, current/baseline five-minute bandwidth KPIs, and `bandwidth_pct` delta. API drilldowns receive the same fields through the existing topology API metrics response.
- Units are explicit: byte totals are bytes, `*_bytes_per_second` values are bytes/second, and `bandwidth_bits_per_second` is bits/second. Missing byte telemetry remains zero and is never inferred from request counts.
- Verification: focused interactive topology/bandwidth tests passed **5/5**; API and behavioral regressions passed **19/19**; Python compilation and `git diff --check` passed.

## Anomaly vs Behavioral Change IDs (2026-09-22)

- `anomaly_events.id` and `principal_change_events.id` are separate namespaces. Overview “What’s different” records come from `/api/v1/user-changes` and must open `/changes/chg-<id>`, not `/anomalies/{id}`.
- `GET /api/v1/user-changes/{id}` provides direct lookup, and `AnomalyDetailPage` redirects legacy mislinked change IDs to the owning User Changes tab.

## Changes Episode Experience (2026-09-22)

- Added the operator-facing `/changes` route and `/api/v1/changes` adapter above the existing `anomaly_events` and `principal_change_events` detector outputs.
- The adapter groups nearby signals by subject, incident, scope, and a bounded 15-minute window into one episode. The primary contract exposes `subject`, human-readable `summary`, `state`, `status`, `highlights`, `evidence`, `timeline`, and relationship context; detector names and scores remain secondary evidence.
- Added `/api/v1/changes/{episode_id}` with stable `chg-<id>` and `anm-<id>` source IDs. The existing detector tables and lifecycle APIs remain unchanged.
- The sidebar and dashboard “What’s different” actions now use `/changes`; `/anomalies` redirects to `/changes` while `/anomalies/:id` remains available for legacy anomaly deep links.
- Added the frontend Changes list/detail experience with operational filters for subject type, state, and search, plus Vietnamese translations for the new operator-facing copy.
- Reduced the primary User workspace to `Overview`, combined `Activity`, and `Changes`. The former `topology` and `patterns` routes redirect to combined Activity; `investigations` redirects to User Changes. The scoped TPS panel remains above all three views.
- Verification: isolated FastAPI Changes route smoke test passed, application OpenAPI registration passed, frontend `npm run lint` and `npm run build` passed, backend compilation passed, and `git diff --check` passed. Playwright 1.63.0 and Chromium were installed in `.venv`; after restarting `tracescope-30102`, the public `/changes` list and `/changes/anm-1886229056538689` detail passed Chromium checks with HTTP 200, Changes API HTTP 200, zero console errors, and zero page errors.
- `backend/requirements.txt` now includes the reproducible Playwright test dependency; install Chromium separately with `.venv/bin/python -m playwright install chromium`.

## Time-series chart stroke (2026-09-23)

- `frontend/src/index.css` defines `--chart-line-width: 1.25px` for every Recharts Line/Area curve and the custom topology-inspector TPS curve. Topology relationship edges, grid lines, and hover markers keep their separate widths. The thinner traces improve visibility of narrow peaks.

## User Activity TPS history recovery (2026-09-23)

- `/users/:principal/activity` merges performance and bandwidth-rollup buckets by the selected time resolution. The Elasticsearch rollup's measured `request_count` supplies TPS even when ClickHouse trace rows have expired or the legacy performance response rounds sparse RPS to zero. Raw performance rows still supply detailed latency and HTTP status values where available.
- For `billing_reconcile_job`, the public bandwidth API returned 1,250 measured five-minute buckets and 63,152 requests over the selected seven-day range. The rebuilt public page rendered a nonzero TPS trace with 382 line segments and displayed the latest sparse rate as `0.0033` TPS. Frontend build and Chromium page check passed with no page errors.

## User Activity metric-bucket TPS source (2026-09-23)

- The worker derives `metric_buckets` from its configured telemetry source, and `GET /api/v1/principals/{principal}/metrics?bucket=300` reads the retained five-minute rollups. User Activity uses this endpoint for transaction counts, TPS, error rate, latency, and measured bandwidth.
- Public verification for `billing_reconcile_job`: the principal metrics API returned 1,741 buckets and 119,605 requests over seven days. The rebuilt page fetched that API successfully and rendered 428 main TPS line segments with no browser page errors.

## Frontend time-series provenance (2026-09-23)

- Transaction line/area charts on Overview, Services, Service Detail, User Activity, User Changes header, API Detail, topology detail, and Unknown Users read worker `metric_buckets` for request rate, errors, and latency. User Activity baseline comes from worker baseline rollups through `/api/v1/dashboard/series`.
- API/topology detail, Overview, Services, and User Activity read transaction counts, latency, and byte rates from worker `metric_buckets` in both storage modes. Frontend charts do not query traces or a separate bandwidth index.
- Bandwidth lines use worker `metric_buckets`, and Agent Fleet lines use `agent_stats_history`.
- User Activity charts and request outcomes derive from worker `metric_buckets` and materialized `principals` metadata; the activity view does not request `/api/v1/users/{principal}/performance`. The shared User workspace header loads its identity profile from `/api/v1/users/{principal}` so an empty selected-window series cannot make an existing principal appear missing. The outcome bar reports non-error versus failed requests because metric buckets do not retain exact HTTP status classes.
- User Activity Access reads worker `topology_principal_ip_5m` rollups. If an Elasticsearch deployment has not materialized IP relationships in ClickHouse, Access has no relationship rows; it does not query raw APM for them. Unknown Users' trend uses `metric_buckets`; its other summary/evidence sections still use trace data.
- The workspace keeps historical activity visible from retained five-minute buckets when the one-minute profile view is empty. It does not invent a principal when both are empty.
- In `OTEL_CLICKHOUSE_ONLY_AGENT_TRACES=true` mode, the Elasticsearch worker now queries transaction aggregates server-side and writes only grouped 60s/300s `metric_buckets` into ClickHouse. It refreshes the latest ten minutes and backfills the Elasticsearch seven-day retention window through a bounded checkpoint. No application trace document is copied into ClickHouse by this stage. Elasticsearch latency percentiles in this path use Elasticsearch's percentile aggregation and are approximate.

## Raw-trace read boundary and topology navigation (2026-09-24)

- User-facing analytics and topology APIs must read worker-owned `metric_buckets`, topology rollups, and other aggregate/read-model tables. Keep raw ClickHouse `traces` access in ingestion and explicit worker/backfill processing only; do not add a request-time fallback to raw spans.
- Prometheus `/metrics` reads the worker snapshot/checkpoint; if neither exists yet, return an empty snapshot instead of running worker aggregation in the API process.
- Trace Explorer remains a separately documented temporary exception: it reads the store selected by `OTEL_TRACE_STORAGE_BACKEND` (Elasticsearch for live APM, ClickHouse `traces` for an offline testbed). Keep raw table reads isolated to its two repository methods and ingestion deduplication; do not add this access to other APIs.
- Interactive topology renders service nodes and service-to-service edges only. API, principal, and IP detail stays in lazy, bounded DOM panels; navigation supports Service → API → User and User → Service → API. Use the stable `service_edge_id` helper and backend `edge_ids` for yellow path highlighting.
- Selecting a service highlights its connected service edges in yellow; selected API/user paths use their backend edge IDs. Highlighted edges render above context edges with yellow arrowheads. Click outside a relationship panel or use its close button to dismiss the scrollable panels; the User directory can be reopened from its Users button.
- API and User selections fetch scoped service connections from the five-minute topology rollups. The yellow line and TPS label reflect the selected API/User plus any chosen Service/API scope; unrelated service edges stay blue. The User-focused endpoint is `GET /api/v1/topology/principals/{principal}/connections` with optional `service` and `api` filters.
- The `/topology` canvas keeps its floating title/search/mode card compact, caps relationship lists at 240px wide and 220px high, places history in a small on-demand popup, and uses compact zoom and legend controls to leave more graph visible.
- Preserve graph coordinates on selection, panel changes, and metric refresh. Read-model rollups and interactive lists must use bounded windows and keyset pagination where cardinality can be high.
- Database connection role is selected with `OTEL_CLICKHOUSE_ROLE=api|worker|owner`; role credentials fall back to the existing base credentials when unset. The API role needs rollup reads; it needs raw `traces` SELECT only while the temporary ClickHouse-mode Trace Explorer is enabled. ELK mode does not require that grant.
- See `docs/topology-read-model.md` for the table boundary, topology flow, edge ID rule, and role grant guidance. The AST boundary regression lives in `tests/test_api_read_model_boundary.py`.

## Active ELK worker and Trace Explorer repair (2026-09-24)

- The Sep 23 bandwidth-rollup change introduced `topology.metric_operation` with Painless `replaceAll` calls using string regex arguments. Elasticsearch 7.17 rejects them with `Cannot cast from [java.lang.String] to [java.util.regex.Pattern]`, causing the worker's `process_elasticsearch` stage to fail with HTTP 400 while APM ingestion continues.
- `backend/app/repositories/elasticsearch_metric_repository.py` now uses Painless regex literals and replacement lambdas. The live aggregation request returns HTTP 200; the restarted worker completed the ELK stage and wrote recent 60-second and 300-second metric buckets. The seven-day checkpoint backfill continues on its normal 60-second cadence.
- `run_server.sh` keeps the analytics/topology backend on ClickHouse and selects Elasticsearch for Trace Explorer via `OTEL_TRACE_STORAGE_BACKEND`. This avoids a ClickHouse SQL error in the broad ELK topology path while resolving live APM trace `2fed16bb627eb937602ba972d48c456c` through both list and waterfall APIs on `:30102`; before the change the same ID returned an empty list and 404.
- The older cluster worker at `10.244.1.196` still writes DNS failures to the shared `jobs` row. The active host worker's Elasticsearch requests and cycles succeed; `/api/v1/ingestion/status.jobs` may show either worker's latest write until the older deployment is updated separately.
