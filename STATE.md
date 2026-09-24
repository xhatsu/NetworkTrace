# TraceScope & Testbed Cluster Services — STATE.md

## 1. Active Cluster Services & Telemetry Ingestion

### Kubernetes Testbed Services
- **Elasticsearch Datastore (`tmp-elk-svc`)**:
  - Namespace: `tmp-elk`; in-cluster service URL: `http://tmp-elk-svc.tmp-elk.svc.cluster.local:9200`.
  - Service Type: `NodePort` (previously `ClusterIP`)
  - Cluster IP: `10.97.180.119:9200`
  - NodePort: `32073` (`http://127.0.0.1:32073` or `http://<NODE_IP>:32073`)
  - Status: Healthy, open, serving cluster `tracescope-elk-testbed` (version 7.17.24).
  - **Elasticsearch 7-Day Retention Invariant**:
    - Strictly stores a maximum of 7 days of APM traces and telemetry (`min_age: "7d"`).
    - Enforced on cluster level via ILM policy `tracescope-7day-retention` and override of default `apm-rollover-30-days` (delete phase at 7 days).
    - Applied via index template `tracescope-7day-retention-template` matching `apm-*`, `traces-apm*`, `tracescope-*`.
    - Automated worker background document pruning: `_run_elasticsearch_sync()` executes asynchronous `_delete_by_query` (`@timestamp < now - 7d`) on APM indices to keep un-rolled individual indices strictly pruned.
  - Indices:
    - `apm-*-transaction-*`: Ingested APM transaction traces across `networktracing`, `order-service`, `payment-service`.
    - `apm-*-metric-*`: System and runtime metrics.
    - `apm-*-span-*`: Distributed span hierarchy.
    - `apm-*-error-*`: Unhandled exceptions and error envelopes.
  - TraceScope Helm chart defaults keep analytics in ClickHouse, set raw trace reads to Elasticsearch, and use this service URL for worker metric aggregation. Release `tracescope` was upgraded to revision 27 on 2026-09-24; its app/worker pod returned to 2/2 Running. The new worker source inserted 57 `metric_buckets` batches and 42 checkpoint updates after rollout, with no ClickHouse insert exceptions.
  - Root cause: the old release passed `http://elasticsearch:9200` to the newest worker even while `elasticsearch.enabled=false`; the actual service is `tmp-elk-svc` in namespace `tmp-elk`. The chart now gates the URL on `elasticsearch.enabled` and supplies the current service DNS name.

- **Elastic APM Server Ingestion Gateway (`apm-server`)**:
  - Service Type: `NodePort`
  - Cluster IP: `10.99.87.70:8200`
  - NodePort: `32765` (`http://127.0.0.1:32765` or `http://<NODE_IP>:32765`)
  - Role: Stateless ingestion pipeline validating OTLP / APM agent payloads and buffering them into Elasticsearch (`tmp-elk-svc`).

- **ClickHouse Cluster Datastore (`tracescope-clickhouse`)**:
  - Service Type: `ClusterIP`
  - Cluster IP: `10.105.101.253:8123` (auto-detected by `backend/config.py:_detect_clickhouse_host`)
  - Status: Healthy, open, serving ClickHouse 24.8.14.39.
    - `tracescope` (Application database): **Populated with 10-day continuous dataset across all 24 hours of every day (175,164 1m buckets, 35,420 5m buckets in ClickHouse; 225,982 traces in Elasticsearch; 41,808 traces in ClickHouse with 1-day TTL)**.
    - **ClickHouse Trace Retention Invariant (1-Day TTL)**:
      - Raw traces copied into ClickHouse for worker SQL rollups expire automatically after 1 day (`TTL toDateTime(intDiv(timestamp_ms, 1000)) + toIntervalDay(1)` applied via `backend/clickhouse_migrations/009_trace_1day_ttl.sql`).
      - All permanent multi-tier span waterfalls on `/traces/:id` are served directly by Elasticsearch (`tmp-elk-svc`), preventing dual-storage bloat while giving the worker its required window for calculations.
    - **10-Day Dataset, 24/7 Continuous Hourly Coverage & Randomized Abnormalities on Last 3 Days**:
      - **10-Day Timespan & Complete 24/7 Hourly Coverage**:
        - Days 0 through 6 (Days -10 to -4, 7 full days): Clean historical baseline traffic covering all 24 hours of every single day (24/24 hours continuous, zero dead hours) modeled with smooth diurnal curves ($0.30 + 0.70 \sin^2$).
        - Normal baseline traffic across all personas is steady and gentle (~0.15 - 0.32 TPS peak per 1m bucket).
      - **Fresh Enterprise Personas (Zero PCAP Usernames)**:
        - All PCAP usernames (`cm2.0`, `sale`, `myViettel`, `vtp`) were eliminated and replaced with 13 fresh enterprise personas: `svc_checkout_gateway`, `batch_settlement_reconciler`, `payment_clearing_engine`, `partner_order_broker`, `enterprise_sync_agent`, `secops_audit_scanner`, `devops_release_operator`, `remote_workplace_client`, `retail_miniapp_client`, `catalog_discovery_sync`, `customer_support_bot`, `logistics_fulfillment_svc`, `mobile_banking_gateway`.
      - **Spike ONLY at Abnormality**:
        - On Day 9 (Today / -1d), `svc_checkout_gateway` surges with a realistic ~200% increase over baseline (from ~0.20 TPS up to ~0.60–0.78 TPS peak; ~47 requests in a 1-minute bucket) calling `apex-order-service` / `OrderService/createOrder`. Avoids aggressive 22 TPS spikes while reliably triggering traffic spike detectors.
      - **Randomized Abnormalities Distributed on the Last 3 Days (Days 7, 8, and 9)**:
        - Day 7 (-3d): Randomized anomalies: `operation_mix_shift`, `target_fanout_surge`, and `rogue_source_ip`.
        - Day 8 (-2d): Randomized anomalies: `dormant_reactivation`, `error_rate_surge`, and `auth_failure_burst`.
        - Day 9 (Today / -1d): Randomized anomalies: `traffic_spike` (~200% increase to ~0.60–0.78 TPS peak), `latency_blowout`, and `unusual_time_access`.
      - **Bandwidth Telemetry & 10-Day Availability Root Cause & Permanent Resolution**:
        - **Root Cause of Single-Day Bandwidth Data**:
          1. **ClickHouse 1-Day TTL on `traces` Table**: ClickHouse enforces a strict 1-day TTL on `traces` (`TTL toDateTime(intDiv(timestamp_ms, 1000)) + toIntervalDay(1)` via Migration 009) to keep local disk usage minimal. The worker's `materialize_slice` queries `FROM traces WHERE timestamp_ms >= ...` to compute the 5m topology byte rollups. Because raw traces older than 24h were purged upon insert, ClickHouse topology tables (`topology_service_edges_5m`, `topology_api_edges_5m`, `topology_principal_edges_5m`, `topology_principal_ip_5m`) were only populated for the most recent 24 hours.
          2. **Separate Bandwidth Rollup Backfill**: User workspace and overview previously depended on an Elasticsearch bandwidth index with its own six-hour-per-cycle backfill. This duplicated work and left bandwidth history empty until that index caught up.
          3. **Default Time Window**: In `backend/app/api/services.py`, `_time_window(from_t, to_t)` defaulted to `max(min_max[0], min_max[1] - 86400)` (last 24h) when explicit parameters were omitted.
        - **Permanent Resolution Implemented**:
          - Enhanced [`backend/scripts/generate_10day_demo_dataset.py`](file:///home/ubuntu/Viettel/OtelTrace/backend/scripts/generate_10day_demo_dataset.py) to seed byte metrics through the existing bucket model:
            * Aggregates 5-minute byte-aware rollups directly in Python from all 314,912 records across the full 10-day span.
            * Inserts full 10-day rollups into ClickHouse: `topology_service_edges_5m` (24,318 rows), `topology_api_edges_5m` (32,570 rows), `topology_principal_edges_5m` (35,423 rows), `topology_principal_ip_5m` (35,423 rows), and current tables.
            * Writes request/response byte sums and sample counts to the same 1-minute and 5-minute `metric_buckets` as request counts and latency.
            * Removes the separate Elasticsearch bandwidth index and its checkpoint; an Elasticsearch metrics schema version triggers one retained-window rebackfill for existing buckets.
          - Overview, Service, API, and User Activity bandwidth series now read from worker `metric_buckets`; no chart endpoint reads trace documents or a separate bandwidth index.
    - Elasticsearch Datastore (`tmp-elk-svc` on `:32073`): **225,982 transactions in `apm-7.17.24-transaction`**, 100% synchronized with ClickHouse traces for the active 7-day forensics window.
    - **TPS Surge Detection & Anomalies Page Visibility**:
      - Detected and verified all 3 principal-level TPS surge cases requested:
        1. `pos_checkout_terminal` on `apex-order-service`: baseline 0.15 -> current 0.59 TPS (+293.3%, Anomaly ID `879726895952825`).
        2. `vtp_express_dispatch` on `apex-customer-service`: baseline 0.15 -> current 0.32 TPS (+113.3%, Anomaly ID `3319515299048063`).
        3. `unknown` (Unauthenticated) on `apex-edge-gateway`: baseline 0.15 -> current 0.30 TPS (+100.0%, Anomaly ID `8194410154801793`).
      - Resolved omission root causes:
        * Added principal-level traffic spike detector in `anomaly_detection.py` so individual identity surges are not diluted by background service traffic.
        * Adjusted frontend `Anomalies.tsx` default perspective to `"all"` and broadened `isUserAnomaly` matching to include `metadata.principals`.
        * Fixed integer day truncation in `principal_daily_stats` (eliminating 617,425 bloated float-division rows down to 31 clean daily rows, accelerating `/api/v1/users/:principal` from 19.05s to 0.29s).
    - **Interactive Service Topology Data Availability & DB Fix**:
      - Resolved "Topology data is unavailable":
        * Restarted FastAPI on port 30102 to load the interactive topology router endpoints (`/api/v1/topology/services`, `/api/v1/topology/services/{service}/apis`, `/api/v1/topology/services/{service}/apis/{api}/principals`, etc.) which were previously returning HTTP 404.
        * Fixed `InteractiveTopologyRepository.backend` property: strictly checks `settings.storage_backend in ("elasticsearch", "elk")`, preventing false Elasticsearch fallbacks when ClickHouse contains the active durable dataset and `OTEL_ES_URL` is set for APM sync.
        * Fully materialized and populated all 8 ClickHouse topology tables directly from the 2,000,000 traces in `tracescope.traces`:
          - `topology_service_edges_5m`: **42,291 rows** (5-minute multi-service rollups with exact p50/p95/p99 percentiles).
          - `topology_api_edges_5m`: **74,856 rows** (API-level endpoint rollups).
          - `topology_principal_edges_5m`: **78,396 rows** (Principal-to-API caller rollups).
          - `topology_principal_ip_5m`: **78,396 rows** (Client IP attribution and classification context).
          - `topology_*_current`: Latest point-in-time lookup tables populated across all 4 dimensions.
        * Enhanced `InteractiveTopologyPage` (`frontend/src/pages/InteractiveTopology.tsx`): Defaults to `24h` window (displaying 20 nodes and 23 edges across `apex-*` microservices), added interactive pill buttons (`5m`, `15m`, `1h`, `6h`, `24h`, `7d`, `all`), added 1-click fallback button on empty states, and applied authentic Vietnamese localization.
    - **100% Anomaly & Behavioral Coverage Verified**:
      - 10/10 Anomaly Detectors active: `unusual_access`, `new_service_edge`, `new_principal_edge`, `error_rate`, `latency`, `unusual_time`, `traffic_spike`, `traffic_drop`, `ip_new_user`, `user_new_source_ip`.
      - All Behavioral Detectors active: `NEW_IP_CALLER_PAIR`, `NEW_OPERATION`, `UNUSUAL_TIME`, `NEW_TARGET`, `NEW_RELATIONSHIP`, `NEW_SOURCE_IP`, `TARGET_FANOUT_SURGE`, `NEW_CALLER`, `CALLER_PRINCIPAL_SWITCH`, `PRINCIPAL_RATE_SURGE`, `AUTH_FAILURE_BURST`, `FAILURE_THEN_SUCCESS`, `DORMANT_REACTIVATED`, `USERNAME_FIRST_SEEN`, `OPERATION_MIX_SHIFT`.
    - **Baseline Generation & Detector Readiness Timelines**:
      - **Metric Baselines (`baseline_metrics`)**: Do **NOT** require 28 days. Generated immediately once `>= 2` five-minute bucket samples exist for a matching `(hour_of_day, day_of_week)` dimension.
      - **Behavioral Readiness Tiers (`evaluate_readiness_from_stats`)**:
        - **Day 0 (Immediate)**: `AUTH_FAILURE_BURST`, `FAILURE_THEN_SUCCESS`, `SOURCE_IDENTITY_FANOUT`, `NEW_PRINCIPAL_ON_SOURCE`, and `DORMANT_REACTIVATED` (requires only `>= 5 total observations` prior to dormancy gap).
        - **Day 1 to 7**: `NEW_CALLER`, `NEW_TARGET`, `NEW_OPERATION`, `NEW_SOURCE_IP`, `NEW_IP_CALLER_PAIR` emit with `low_confidence` starting on Day 1 (if `total_obs >= 5` or `10`), and reach full `ready` confidence at Day 7 (`elapsed_days >= 7.0`, `active_days >= 3`, `total_obs >= 100`). `RELATIONSHIP_DISAPPEARED` activates at Day 7.
        - **Day 14**: `OPERATION_MIX_SHIFT`, `PRINCIPAL_RATE_SURGE`, `CALLER_PRINCIPAL_SWITCH`, `TARGET_FANOUT_SURGE` activate (`elapsed_days >= 14.0`, `active_days >= 5`, `total_obs >= 200`).
        - **Day 28 (Only 1 Detector)**: `UNUSUAL_TIME` is the **only** detector that requires 28 days (`elapsed_days >= 28.0`, `active_days >= 10`), strictly because learning a user's true off-hours work pattern requires a 4-week monthly baseline to prevent false alarms on first-week shift workers.
    - `system` (ClickHouse internal engine logs): Truncated with enforced 1-day TTL retention (`event_date + toIntervalDay(1)`).
  - Elasticsearch Datastore on `:32073`: APM index `apm-7.17.24-transaction` holds **2,000,334 transaction documents** with canonical `enduser.id` field and zero mapper parsing errors.
  - Table Engine: `ReplacingMergeTree`. Queries across `principals`, `principal_callers`, etc., use `FINAL` (e.g. `FROM principals AS p FINAL`) to guarantee deduplicated records across asynchronous background merges.
  - Anomaly Time Horizon: Incident Time Horizon line graph on `/anomalies/:id` defaults to a **24-hour horizon** with interactive `1h` / `6h` / `24h` / `7d` controls and dual date-time XAxis ticks (`MM/DD HH:mm`).
  - User Performance API Resilience: Implemented defensive `_clean()` float sanitization in `UserRepository.performance()` to safely handle empty / zero-traffic outage windows (ClickHouse `quantile(0.95)` returning `NaN`), ensuring 100% JSON-compliant numeric responses.
  - Behavioral Scope Stability Redesign: Replaced confusing 4-line overlapping stair-step graph on `/users/:principal/patterns` with an interactive multi-view Scope Stability system:
    1. **Radar View (Default)**: Recharts `RadarChart` comparing learned baseline polygon vs live observed scope across 4 dimensions (Targets, Operations, Callers, Source IPs) with side-by-side Stability Score card (`0%-100%`), containment badges, and 4 dimension metric tiles.
    2. **Grouped Bar View**: Side-by-side comparison of baseline vs current counts per dimension.
    3. **Stability Trend View**: Single smooth `AreaChart` tracking scope stability score over time with an 80% safe reference threshold.
  - Unknown & Unauthenticated Users Traffic Monitor (`/unknown-users`): Added dedicated monitoring page and backing API (`/api/v1/unknown-users`) for unauthenticated, anonymous (`-anonymous-`), and `unknown` traffic. Displays volume %, auth failure rate (401/403), avg/p95 latency, explored surface, throughput & error time series, top target services, top probed endpoints, top source IPs, and recent raw traces with direct links to distributed waterfall views. Accessible via SideNav under `Identity & Access` and via the header in `UserDirectory.tsx`.

- **TraceScope Dashboard Hub & Aggregation Worker**:
  - Dashboard API & Frontend: `http://0.0.0.0:30102` (FastAPI + React 19 SPA)
    - Operational Dashboard: 6 top KPI cards (`TPS`, `Error rate`, `P95 latency`, `Active users`, `Services`, `Needs attention`) equipped with instant SVG gradient sparklines, colored accent dots, and dense secondary telemetry (`avg/peak`, `5xx max`, `p50/p99`, active users now, degraded service count, critical change count).
  - Aggregation Worker: `tracescope-worker` (`python -m backend.worker --interval 60`)
  - Ingest NodePort: `http://<node-ip>:30103/api/ingest`
  - Ingress HTTP NodePort: `http://<node-ip>:31561`

- **Lightweight Monitoring Stack (`light-mon`)**:
  - Namespace: `monitoring`
  - Release: `light-mon` (Chart: `prometheus-community/kube-prometheus-stack` deployed via Helm with `--skip-crds -f values-lightweight.yaml`, Revision: 5)
  - Configuration: [values-lightweight.yaml](file:///home/ubuntu/Viettel/OtelTrace/values-lightweight.yaml)
  - Components Enabled:
    - Prometheus (`light-mon-kube-prometheus-prometheus`, retention 2d, 30s scrape interval, ephemeral emptyDir storage)
    - Grafana (`light-mon-grafana`, NodePort `32080`, `http://<NODE_IP>:32080`, adminPassword: `admin`, persistence disabled)
    - Prometheus Operator (`light-mon-kube-prometheus-operator`)
  - Additional Scrape Target:
    - Job: `tracescope` scraping `https://trace.n2d.id.vn:443/metrics` (SNI/TLS verified)
  - Disabled Components: `alertmanager`, `nodeExporter`, `kubeStateMetrics` (trimmed for minimal resource footprint)




---

## 2. Aggregation Worker & Elasticsearch NodePort Wiring

### Wiring Configuration
- **Target NodePort**: `http://127.0.0.1:32073`
- **Environment Variables**:
  - `OTEL_ES_URL="http://127.0.0.1:32073"`
  - `OTEL_ES_INDEX="apm-*,traces-apm*"`
  - `OTEL_STORAGE_BACKEND="clickhouse"` for active analytics and topology read models.
  - `OTEL_TRACE_STORAGE_BACKEND="elasticsearch"` for active application trace list and waterfall reads.
- **Lifecycle Integration (`run_server.sh`)**:
  - Default `ELASTICSEARCH_NODEPORT="32073"`
  - Automatically exports `OTEL_STORAGE_BACKEND`, `OTEL_TRACE_STORAGE_BACKEND`, `OTEL_ES_URL`, and `OTEL_ES_INDEX` to both `tracescope-30102` and `tracescope-worker` tmux sessions. Set `OTEL_TRACE_STORAGE_BACKEND=clickhouse` explicitly for an offline ClickHouse trace testbed.
  - `run_server.sh status` verifies connectivity directly to NodePort 32073.
- **Worker Stages (`backend/worker.py`)**:
  1. `process_elasticsearch`: In the active `OTEL_CLICKHOUSE_ONLY_AGENT_TRACES=true` mode, server-side Elasticsearch transaction aggregation writes grouped 60-second and 300-second `metric_buckets` to ClickHouse; raw application APM traces stay in ELK. The legacy incremental `ElasticsearchReader` trace-copy path is used only when that agent-only setting is disabled.
     - **ELK `enduser.id` Extraction**: Automatically extracts username from `enduser.id`, `labels.enduser.id`, `labels.enduser_id`, `enduser: {id}`, `attributes: [{"key": "enduser.id", ...}]`, `user.id`, `user.name`, and search `fields["enduser.id"]`. Sets `principal_name = enduser.id`, `identity_source = "enduser_id"`, and `principal_id = "<env>:<enduser.id>"`.
     - **ELK Trace Search Isolation**: `ElasticsearchTraceRepository.list_traces()` strictly filters for `processor.event: ["transaction", "span"]` or `exists: trace.id` and excludes `processor.event: "metric"`. Prevents non-trace metric documents from generating synthetic hash IDs that fail resolution in `/traces/{id}`. `get_trace()` includes `_id` fallback in search.
  2. `aggregate_traces`: Bounded 1m/5m rollups computed across newly ingested traces.
  3. `rebuild_baselines`: Rolling median & MAD baseline recomputation.
  4. `detect_anomalies`: Detectors evaluated across updated metric buckets (including `unusual_access`, `unusual_time`, `user_new_source_ip`, `ip_new_user`).
  5. `process_principal_intelligence`: Identity behavioral change detection and incident scoring.

---

## 3. Quick Guide: How to Inspect & Query Data

### A. Check Elasticsearch NodePort Health & Indices
```sh
# Elasticsearch Cluster Info via NodePort 32073
curl -s "http://127.0.0.1:32073/"

# List all indices and document counts
curl -s "http://127.0.0.1:32073/_cat/indices?v"

# Cluster health
curl -s "http://127.0.0.1:32073/_cluster/health?pretty"
```

### B. Query APM Transactions (Traces)
```sh
# View recent transaction records directly from NodePort 32073
curl -s "http://127.0.0.1:32073/apm-*-transaction-*/_search?pretty&size=5"

# Search by specific service
curl -s "http://127.0.0.1:32073/apm-*-transaction-*/_search?q=service.name:networktracing&pretty"
```

### C. Verify TraceScope Dashboard & Worker
```sh
# Lifecycle status (includes NodePort 32073 check)
sh ./run_server.sh status

# Health endpoint showing Elasticsearch configured
curl -s "http://127.0.0.1:30102/api/v1/health"

# Query traces (reads through to NodePort 32073 with ClickHouse fallback)
curl -s "http://127.0.0.1:30102/api/v1/traces?limit=5"

# View live aggregation worker cycle logs
tmux capture-pane -pt tracescope-worker -S -30
```

---

## 4. Aggregation Worker Cutoff & History Filtering

### Parameter & Checkpoint Support
Previously, ClickHouse `checkpoints` tracked `(ingest_order, row_uid, last_ts)` but lacked initial cutoff filtering, always querying `MIN(timestamp_ms)` across all traces on cold start. 
Now, TraceScope supports ignoring historical trace data and only processing traces after a specified cutoff time (e.g. deployment time):

- **Parameters**:
  - `OTEL_WORKER_START_TIME` (CLI `--start-time`): Start timestamp cutoff. Accepts:
    - `"now"` or `"deploy_time"`: Evaluates to current system timestamp at startup.
    - ISO-8601 string: e.g. `"2026-09-16T00:00:00Z"` or with timezone offset `+07:00`.
    - Epoch ms or epoch seconds: e.g. `"1789560000000"` or `"1789560000"`.
  - `OTEL_WORKER_IGNORE_PAST_DATA` (CLI `--ignore-past-data`): Boolean (`true`/`false`). Automatically evaluates to deployment timestamp (`time.time() * 1000`) if `OTEL_WORKER_START_TIME` is not explicitly set.

- **Storage & Checkpoint Behavior**:
  - **Aggregation Cursor (`aggregation_cursor`)**:
    - If `worker_start_time_ms` is set on cold start and no traces exist $\ge$ cutoff yet, an incremental checkpoint is initialized immediately at the latest existing trace `ingest_order` with `last_ts = worker_start_time_ms`, permanently bypassing past traces.
    - If traces exist $\ge$ cutoff, bootstrap bounds are constrained (`WHERE timestamp_ms >= ?`) and aligned to 5-minute boundaries without querying earlier data.
    - Existing checkpoints with `last_ts < worker_start_time_ms` are automatically fast-forwarded to the cutoff cursor.
    - Incremental queries filter with `AND timestamp_ms >= ?`.
  - **Principal Behavioral Intelligence (`principal_intelligence`)**:
    - Initializes the checkpoint cursor at `worker_start_time_ms` without scanning historical data for bootstrap.
    - Incremental fetches query `AND timestamp_ms >= ?`.
  - **Elasticsearch Ingestion Sync (`ElasticsearchReader`)**:
    - Cold-start initial queries (`search_after=None`) append range filter `{"range": {"@timestamp": {"gte": start_time_ms}}}` to pull only post-cutoff hits from ELK.

- **Helm & Kubernetes Configuration**:
  - `deploy/helm/tracescope/values.yaml`:
    ```yaml
    app:
      worker:
        startTime: ""        # e.g. "now", "2026-09-16T00:00:00Z", or epoch ms
        ignorePastData: false # set true to ignore all data before deployment
    config:
      workerStartTime: ""
      workerIgnorePastData: false
    ```
  - `deploy/helm/tracescope/templates/configmap.yaml` & `deploy/k8s/10-configmap.yaml`:
    Exports `OTEL_WORKER_START_TIME` and `OTEL_WORKER_IGNORE_PAST_DATA`.
  - `deploy/helm/tracescope/templates/storage-statefulset.yaml`:
    Supplies both environment variables and CLI arguments (`--start-time`, `--ignore-past-data`) to `analytics-worker`.

---

## 5. 6 User-Centric Observability Architecture

### Operational Questions & Page Mapping
The user workspace has been completely redesigned around 6 user-centric operational questions:

| Page | Route | Core Question | Core Signals & Features | Visualizations |
| :--- | :--- | :--- | :--- | :--- |
| **1. User Overview** | `/users/:id/overview` | *“Is this user behaving normally right now?”* | Current 5m RPS, req/min, error rate, p95/p99 latency, active callers, targets, operations, IPs, anomaly score, deltas vs baseline | 8 KPI Cards, 4 High-Contrast Line Charts (RPS vs base, error rate, p95 latency, Abnormality Score Spike vs base 0), Mini Change Timeline, New Relationships Summary |
| **2. Activity & Performance** | `/users/:id/activity` | *“How has this user’s traffic/performance changed?”* | Throughput RPS, Request volume/min, HTTP status breakdown (2xx, 4xx, 5xx, timeouts), p50/p95/p99 latency percentiles, burstiness | Traffic RPS line chart, 100% Stacked status bar chart, Multi-percentile latency area chart, Interactive pinned time-slice inspector |
| **3. Access & Topology** | `/users/:id/topology` | *“What systems is this user touching?”* | Dedicated dependency path: `User → Caller Services → Target Services`, expandable Target Operations, edge RPS, error rates, p95 | Interactive Canvas Dependency Graph, Collapsible Target Operations breakdown, Edge Metrics Inspector Drawer |
| **4. Behavior Changes** | `/users/:id/changes` | *“What is different from the user’s normal behavior?”* | Behavioral shifts from baseline: identity/network, resource/target, relationship, execution distribution shifts | Before vs Now Distribution Bars, Category Filter Tabs, Explainable 7-Questions Change Timeline |
| **5. Usage Patterns** | `/users/:id/patterns` | *“When and how does this user normally operate?”* | Hourly & weekly activity rhythm, target services distribution, top operations distribution, behavioral scope evolution | 24h × 7d Activity Heatmap, Target Service Share Horizontal Bars, Operation Share Bars, Behavioral Scope Evolution Series |
| **6. Anomalies & Investigations** | `/users/:id/investigations` | *“What needs investigation?”* | Active investigation queue, automated trigger hypotheses, BEFORE vs NOW metrics comparison, introduced relationship chains | Investigation Incident Queue, Before vs Now Comparison Table, Visual Causal Relationship Chain, Operator Triage Controls |

### Navigation & Layout Standard
- **System Navigation**: Clean left SideNav with `Dashboard` (`/dashboard`), `Users Hub` (`/users`), `Anomalies` (`/anomalies`), `Services` (`/services`), `Traces` (`/traces`), `Agent Fleet` (`/agent-stats`). The redundant generic service-to-service topology (`/topology`) has been removed from navigation and redirects cleanly to `/users`; user-centric access topology is strictly served within the user workspace at `/users/:principal/topology`.
- **TPS chart invariant**: `/services`, `/services/:name`, API detail routes, and every `/users/:principal/*` workspace route render the scoped TPS line graph as the first operational panel above detail metrics and tables.
- **User Workspace Banner (`UserLayout.tsx`)**:
  - Sticky entity header with user avatar, display name, account classification, risk level badge, current 5m RPS, error rate, and active targets.
  - In-header **Quick Account Switcher** dropdown for jumping between users.
  - Distinct 6-tab navigation bar with route-synchronized active state indicator.
  - **Color, Contrast & Non-Glossy Styling Standard**:
  - Grafana-style matte dark surfaces: Canvas `#0b0c0e`, panels `#111217`, raised controls `#181b1f`, compact side rail `#111217`, borders `#2a2d30` / `#34373b`.
  - Zero glossy effects: No `radial-gradient` background sheens, no `backdrop-blur` frosted glass overlays, and zero neon `shadow-[0_0_...` glowing reflections.
  - Crisp high-contrast text (`#ffffff` headers, `#f1f5f9` primary data, `#94a3b8` labels). Zero washed-out or dim text.
  - Semantic accent badges: Green (`#73bf69`) for healthy, blue (`#5794f2`) for primary telemetry, orange (`#ff9830`) for warnings, red (`#f2495c`) for failures, and purple (`#b877d9`) for secondary series.

### Redesigned Identity Observability Dashboard (`/`)
The primary system dashboard (`Overview.tsx`) has been redesigned to focus strictly on **User and Identity Statistics** (relieving redundant service/infrastructure monitoring handled by external systems):
- **Operational landing hierarchy**: TPS is paired with “What’s different right now,” followed by five primary health KPIs, Top Services, Top Users, and behavior-change history.
- **Identity Velocity vs Error Dynamics**: Dual-axis chart comparing attributed throughput RPS against HTTP failure proportions.
- **Identity Risk Cohort Split**: Distribution of accounts across risk severity tiers and active transacting states.
- **Actionable User Triage**: Prioritized user accounts ranked by anomaly score with 1-click `Inspect` buttons leading into the 6-tab user workspace (`/users/:principal/overview`).
- **Shared Credentials & Ingress Fan-Out**: Identifies accounts invoked across multiple callers or distributed networks.
- **Live Behavioral Change Stream & Incidents**: Chronological feed of explainable baseline violations and active multi-signal behavioral incident queue.

---

## 6. Supporting Attribution Signal Architecture (IP as Context)

### Core Architectural Principle
IP addresses are treated strictly as **supporting attribution signals**, not primary behavioral dimensions:
- **Primary Behavioral Path**: `User → Caller → Target → Operation`
- **Supporting Context**: `Source IP` (`observed_source_ip`, `effective_client_ip`, `source_ip_role`, `attribution_confidence`).
- **Aggregation Key**: Remains centered on behavior: `principal × caller × target × operation`. The 5D combination is not used as the baseline key, preventing intermediate proxy or load-balancer hops from triggering false behavioral drift.

### Role Classification & Attribution Confidence
TraceScope classifies observed source IP addresses into roles with associated attribution confidence (`classify_source_ip_role`):
- `load_balancer`: Configured or recognized load balancers (`low` confidence). Suppressed or zero-weighted in incident scoring.
- `reverse_proxy` / `service_ingress`: Known reverse proxies or ingress controllers (`medium` confidence).
- `nat_gateway` / `infrastructure`: Infrastructure gateways (`medium` confidence).
- `client`: Genuine external/client IP addresses (`high` confidence). Meaningful in behavioral shifts.

### Selective Integration Across 6 User Pages
1. **User Overview (`/users/:id/overview`)**:
   - Secondary "Source IPs" count/delta card (Card 8) with dashed border, muted styling, and `Secondary Attribution Context` pill.
    - **4 High-Contrast Line Charts** in a 2x2 grid (two lines, each line two cards: `grid grid-cols-1 gap-5 lg:grid-cols-2`):
      - Line 1, Card 1: **RPS vs Baseline** (Cyan `#00f0ff` vs Purple dashed `#b388ff`).
      - Line 1, Card 2: **Error Rate Over Time** (Red `#ff1744` 4xx/5xx error proportion).
      - Line 2, Card 3: **P95 Latency Over Time** (Amber `#ffab00` tail execution latency ms vs Slate dashed `#94a3b8`).
      - Line 2, Card 4: **Abnormality Score Spike** (Fuchsia `#d946ef` observed anomaly score surge 0–100 vs Slate dashed `#64748b` baseline 0; categorizes into Normal, Low Spike <25, Medium Spike 25-59, High Spike $\ge$60). Backend aggregates `principal_change_events` and `anomaly_events` time-bucketed in `UserRepository.performance()` into the `series` array.
      - **Scaled RPS Abnormality Score & Low-Baseline Floor**: When observed RPS exceeds baseline normal, abnormality score scales dynamically (10% off base = 10 pts, scaled proportionally, not fixed). To avoid the low-baseline denominator trap where sub-second traffic (e.g. 0.20 req/s bumping to 0.28 req/s) falsely inflated to 100 pts, an effective significance floor (`effective_base = max(b_base_rps, 0.5)`) is applied (`rps_pct_off = ((b_rps - b_base_rps) / effective_base) * 100.0`). A 0.28 vs 0.20 bump correctly scores a mild 13–15 pts. Event scoring is bounded to peak event severity with diminishing increments, and combined into `anomaly_score` via `max(event_score, rps_score)` rather than uncapped sums.
2. **Activity & Performance (`/users/:id/activity`)**:
   - Optional Source IP breakdown filter dropdown with role pills (`Client` vs `Load Balancer`) and active filter indicator.
3. **Access & Topology (`/users/:id/topology`)**:
   - Clean 3-column behavioral graph by default: `User → Caller Services → Target Services`.
   - Optional `[ ] Show network path (IPs / Proxies)` toggle dynamically renders intermediate network hops between User and Caller without polluting the microservice dependency architecture.
4. **Behavior Changes (`/users/:id/changes`)**:
   - High-value behavioral novelties (`NEW_CALLER`, `NEW_TARGET`, `NEW_OPERATION`, `NEW_RELATIONSHIP`) sorted first.
   - Supporting network/IP novelties (`NEW_SOURCE_IP`, `SOURCE_IP_DISTRIBUTION_SHIFT`, `NEW_IP_CALLER_PAIR`) filtered under "Supporting Network & IP" tab with attribution confidence indicators.
5. **Usage Patterns (`/users/:id/patterns`)**:
   - Section 4: "Known Source IPs Baseline (Secondary Attribution Context)" card with IP share bars and role indicators.
6. **Anomalies & Investigations (`/users/:id/investigations`)**:
   - Section 3: Corroborating "Supporting Ingress & Network Evidence" with explicit labeling (`Source Address: Likely load balancer · Low attribution confidence`).

---

## 7. Testbed Wipe, Sample ELK Seeding, & Usability Verification

### Data Reset & Reseeding Lifecycle
1. **ClickHouse Reset**:
   - Truncated all 36 analytical, aggregate, baseline, and behavioral tables in the ClickHouse `tracescope` database (preserving schema migrations).
2. **Elasticsearch Reset**:
   - Cleanly deleted all legacy APM indices via `DELETE http://127.0.0.1:32073/apm-*`.
3. **Realistic Sample APM Data Generation**:
   - Script: [`backend/scripts/generate_sample_elk_data.py`](file:///home/ubuntu/Viettel/OtelTrace/backend/scripts/generate_sample_elk_data.py).
   - Indexed 12,000 realistic APM transaction documents directly into Elasticsearch NodePort (`http://127.0.0.1:32073/apm-7.17.24-transaction-000001`).
   - Distributed across the last 3.5 hours up to the current timestamp to ensure full visibility within the dashboard's active observation window.
   - Realistic multi-service topology: `frontend-web`, `api-gateway`, `order-service`, `payment-service`, `inventory-service`, `customer-service`, `notification-service`, `auth-service`, `billing-service`.
   - Behavioral and anomaly scenarios injected: `mallory` rate surge on payment-service, `oscar` 401 auth bursts on auth-service, `judy` novel billing-service relationship, `peggy` tail latency blowout on cancelOrder, `heidi` dormant reactivation, `ivan` shared credential fan-out, and realistic client/proxy/LB IP classifications.
4. **Worker Derivations**:
   - Synchronized 12,000 records from ELK into ClickHouse `traces`.
   - Generated 207 1m buckets, 154 5m buckets, 22 service edges, 107 principal edges, 808 rolling baselines, 1,287 core observability anomalies, 17 distinct identities, 649 behavioral change events, and 20 security incidents.
5. **Verification & Testing**:
   - Curl & JavaScript safety test suite passed 48/48 tests (`sh backend/scripts/curl_test_all_pages.sh`).
   - Playwright Chromium real-browser suite passed 17/17 pages (`python3 backend/scripts/test_pages_playwright.py`).
   - Zero duplicate accounts in User Directory (`FROM principals AS p FINAL`).
   - Port 30102 live and fully functional.

---

## 8. Baseline Duration & Normal Behavior Promotion Rules

In TraceScope, "normal" is evaluated on two layers:

### A. Operational Metrics (Latency, RPS, Error Rates)
- **Bucket Grain**: 5-minute aggregation buckets (`bucket_size = 300s`).
- **Baseline Window**: Rolling medians and MAD (Median Absolute Deviation) computed across matching **hour-of-day (0–23)** and **day-of-week (0–6)**.
- **Normal Envelope**: Telemetry is considered normal within the median ± 3× MAD threshold.

### B. User & Identity Behaviors (New Actions, Targets, Callers, IPs)
1. **Candidate Promotion to Established Baseline (`behavioral_engine.py`)**:
   - When an identity performs a new action (new target, new operation, new caller, new source IP), it is initially flagged as a novelty and placed into `candidate_behaviors`.
   - **Promotion Criteria**: The action becomes part of the identity's established baseline ("normal") when it is observed:
     - On at least **3 distinct days** (`distinct_days_count >= 3`), AND
     - In at least **5 separate 15-minute windows** (`distinct_windows_count >= 5`).
   - Once promoted to `established_baselines`, this action is permanently considered normal for this user and will no longer trigger novel behavior alerts.
2. **Detector Learning & Readiness Periods**:
   - **Novel Callers, Targets, Operations, Relationships, IPs**: Requires $\ge$ **7 elapsed days**, $\ge$ **3 active days**, and $\ge$ **100 observations** to graduate from "learning" to "ready".
   - **Operation Mix Shift & Rate Surge**: Requires $\ge$ **14 elapsed days**, $\ge$ **5 active days**, and $\ge$ **200 observations**.
   - **Unusual Time (Off-Hours)**: Requires $\ge$ **28 elapsed days** (4 full weekly cycles) and $\ge$ **10 active days** to establish diurnal/weekly habits.
   - **Authentication Policy Violations**: Evaluated immediately (0-day learning requirement).
3. **Manual Operator Acceptance**:
   - Operators can immediately mark any novel action as normal via the Operator Review UI (`/api/v1/user-changes/{id}/review`). This inserts an `operator_override` (either permanent or with a custom expiry period).

---

## 9. 15-Day 5-User Demonstration Dataset & Usability Suite

### Configuration & Persona Mapping
- **Generator**: [`backend/scripts/generate_15day_demo_data.py`](file:///home/ubuntu/Viettel/OtelTrace/backend/scripts/generate_15day_demo_data.py)
- **Timespan**: Exactly 15 days (360 hours) from `2026-09-01T04:40:08Z` to `2026-09-16T04:40:08Z`.
- **Dataset Size**: 19,227 APM transaction records bulk-indexed into Elasticsearch NodePort (`http://127.0.0.1:32073/apm-7.17.24-transaction-000001`).
- **5 Focused Demo Personas**:
  1. `alice` (**Steady Golden Baseline**):
     - Active on all 15 days during normal business hours (08:00 - 18:00 UTC).
     - 7,441 total requests across `user-service`, `order-service`, `inventory-service`.
     - Status: Established baseline, Score: 0 (Low Risk), 0 changes, 99.5% success rate.
  2. `bob` (**Candidate Promotion Showcase**):
     - Active on all 15 days on `order-service` and `user-service`.
     - On Days 10–15, regularly accessed new target `billing-service` (`BillingService/getInvoice`).
     - 657 requests across 6 distinct days and >20 separate 15-minute windows.
     - Met candidate promotion criteria ($\ge 3$ distinct days, $\ge 5$ windows), promoted to `established_baselines`.
     - Status: Established baseline, Score: 0 (Low Risk), 0 changes.
  3. `mallory` (**Traffic Surge & Blast Radius**):
     - Low background activity for 14 days (~80 reqs/day on `order-service`).
     - In the final 2 hours, unleashed a 2,200-request surge on `payment-service` (`PaymentService/chargeCard`) via `order-service` with 380ms tail latency and 25% 5xx errors.
     - Status: Active, Score: 85 (High Risk), 4 changes.
  4. `oscar` (**Credential Abuse & Auth Failure Burst**):
     - Sporadic token checks for 14 days (~35 reqs/day).
     - In the final 45 minutes, executed 140 rapid HTTP 401 Unauthorized attempts on `auth-service` from foreign IP `185.220.101.5`, followed by a successful login.
     - Triggers `AUTH_FAILURE_BURST` and `FAILURE_THEN_SUCCESS`.
     - Status: Active, Score: 65 (High Risk), 4 changes.
  5. `judy` (**Architectural Drift & Off-Hours Access**):
     - Daytime activity on Days 1–13.
     - On Days 14–15, accessed `billing-service` at 02:30–04:00 UTC (off-hours) from a new IP `103.251.167.22`.
     - Triggers `NEW_TARGET`, `UNUSUAL_TIME`, and `NEW_SOURCE_IP`.
     - Status: Active, Score: 65 (High Risk), 4 changes.

### Worker & Testbed Verification
- **Worker Derivations**:
  - `elasticsearch_read` / `elasticsearch_inserted`: 19,227
  - `1m_buckets`: 16,339 | `5m_buckets`: 13,394
  - `service_edges`: 341 | `principal_edges`: 399
  - `baselines`: 2,971 rolling median & MAD records
  - `principal_records`: 19,245 | `principal_changes`: 178 | `incidents`: 9
- **Validation**:
  - Curl & JavaScript Safety Test Suite (`sh backend/scripts/curl_test_all_pages.sh`): 48/48 tests passed (0 JS crash risks).
  - Playwright Chromium Real-Browser E2E Suite (`python3 backend/scripts/test_pages_playwright.py`): 17/17 real browser pages passed with 0 unhandled JS exceptions.
  - Active Hub: `http://0.0.0.0:30102`

---

## 10. Chart Tooltip & Line Label Alignment (2026-09-16)

### Issue Identified
In multi-line Recharts components, hover tooltips were rendering the same series name and unit for all lines (e.g., both throughput lines showing `"Requests / Min"` or both latency lines showing `"Baseline P95"`). This was caused by tooltip `formatter` functions attempting to match raw `dataKey` values (`"rps"`, `"latency_p95"`) against the formatted `name` prop passed by Recharts (`"RPS"`, `"Observed P95"`), falling through to the false branch for all series.

### Fix Applied
1. **`UserActivityTab.tsx`**:
   - Throughput Chart: Checked `item?.dataKey` and `name` to accurately format `"Throughput (RPS)"` (`${val} req/s`) vs `"Requests / Min"` (`${val} req/min`).
   - Latency Chart: Defensively resolved `item?.name || item?.dataKey` to preserve distinct labels (`"p50 (Median)"`, `"p95 (Tail)"`, `"p99 (Extreme Tail)"`).
2. **`UserOverviewTab.tsx`**:
   - RPS vs Baseline Chart: Accurately distinguishes `"Observed RPS"` from `"Baseline RPS"`.
   - P95 Latency Chart: Accurately distinguishes `"Observed P95"` from `"Baseline P95"`.
3. **`UserPatternsTab.tsx` & `Overview.tsx`**:
   - Added explicit formatters to ensure distinct line labels and correct units (`req/s`, `%`, count).
4. **Verification**:
   - Frontend built cleanly (`tsc -b && vite build` in 9.65s).
   - Curl & JS Safety Test Suite: 48/48 passed.
   - Playwright Real-Browser E2E Suite: 17/17 pages passed with 0 JS errors.

---

## 11. User Fetch Request Latencies & Polling Cadence

### Live Server Response Times (HTTP 200 via Node.js/FastAPI on :30102)
- `GET /api/v1/users/{principal}/investigations`: **~17 ms**
- `GET /api/v1/user-graph/{principal}`: **~22 ms**
- `GET /api/v1/users/{principal}/changes`: **~43 ms**
- `GET /api/v1/users/{principal}/topology`: **~44 ms**
- `GET /api/v1/users/{principal}/timeline`: **~54 ms**
- `GET /api/v1/user-changes`: **~69 ms**
- `GET /api/v1/user-analytics`: **~85 ms**
- `GET /api/v1/users/summary`: **~95 ms**
- `GET /api/v1/users` (Directory inventory): **~144 ms**
- `GET /api/v1/users/{principal}/performance`: **~146 ms**
- `GET /api/v1/users/{principal}` (Full comprehensive profile): **~408 ms**

### Frontend Caching & Refresh Cadence
- **Default Stale Time**: 15 seconds (`staleTime: 15_000` in TanStack Query).
- **Auto-Refetch Interval**: 30 to 60 seconds (`refetchInterval: 30_000` / `60_000`).
- **Worker Derivation Cadence**: Every 60 seconds (`--interval 60`).

---

## 12. Complete Vietnamese Localization (i18n) & Language Toggle (2026-09-16)

The active catalog now uses canonical Vietnamese copy while preserving operator-facing DevOps/product terms in English (`Service`, `API`, `User`, `TPS`, `Latency`, `Trace`, `IP`, `Baseline`, `Agent`, and protocol/database names). The English catalog is populated from the same key set so language switching does not expose stale missing-key fallbacks.

### Architecture & Implementation
- **I18n Engine (`frontend/src/i18n.tsx`)**:
  - `I18nProvider` wrapping `<App />` with reactive language state (`"vi"` / `"en"`).
  - Persists preference in `localStorage.getItem("tracescope_lang")`, defaulting to Vietnamese (`"vi"`).
  - Bidirectional lookup with case-insensitive fallback.
  - `<LanguageSwitcher />`: Compact header pill displaying `🇻🇳 VI` / `🇬🇧 EN` with instant toggle.
- **Coverage Across All 17 Pages & SPA Components**:
  1. **Global Navigation & Shell** (`App.tsx`, `components.tsx`):
     - Sidebar navigation, header search bar, timezone, filter bar dropdowns, loading indicators, error boundaries.
  2. **Overview (Dashboard)** (`pages/Overview.tsx`):
     - 8 Primary User Signal cards, traffic velocity vs error dynamics charts, risk cohort distribution, prioritized anomalous user accounts, shared credentials, live behavioral changes feed, and correlated security incidents.
  3. **All 8 User Workspace Views** (`pages/user/*`):
     - User Directory (`UserDirectory.tsx`): summary KPI cards, tier filters, sort options, principal table.
     - User Workspace Layout (`UserLayout.tsx`): header, risk badge, account switcher, 6 tab questions.
     - Tab 1: Overview (`UserOverviewTab.tsx`): 8 KPI cards, sparklines, RPS/P95 vs baseline, changes timeline, surface expansion.
     - Tab 2: Activity (`UserActivityTab.tsx`): throughput, 100% stacked status, multi-percentile latency, pinned time-slice inspector.
     - Tab 3: Access Topology (`UserTopologyTab.tsx`): user-to-service call paths, expandable operations, edge inspector drawer.
     - Tab 4: Behavior Changes (`UserChangesTab.tsx`): category filters, before-vs-now distribution bars, 7-question explainability timeline, operator review overrides.
     - Tab 5: Usage Patterns (`UserPatternsTab.tsx`): 24h × 7d heatmap, target/operation share, scope stability, source IP baselines.
     - Tab 6: Investigations (`UserInvestigationsTab.tsx`): incident queue, before-vs-now comparison table, causal relationship chain, triage actions.
  4. **Services Directory & Drilldown** (`pages/Services.tsx`):
     - Service inventory cards, deep-dive operations table, caller/downstream dependencies, account distributions, instances.
  5. **Anomalies Directory & Detail** (`pages/Anomalies.tsx`):
     - Anomaly finding queue, severity filters, explainability card, root cause heuristic, blast radius, actual vs baseline timeline.
  6. **Traces & Spans** (`pages/Traces.tsx`):
     - Transaction analytics list, filters, status filters, table headers, multi-tier waterfall execution diagram, span attributes drawer.
  7. **Agent Fleet & Node Drilldown** (`pages/AgentStats.tsx`):
     - Fleet health status, push rates, queue occupancy, node table, delete modals, time-series charts (Throughput, Drop %, System Resources, Buffer Queue, Emitted Events), process hardware limits, and historical snapshot table.

### Verification
- **Production Build**: `tsc -b && vite build` passed cleanly in 10.51s with 0 errors (`dist/index.html` + chunks generated).
- **End-to-End Curl & JavaScript Safety Suite** (`sh backend/scripts/curl_test_all_pages.sh`): 48/48 tests passed (0 JS crash risks).
- **Playwright Real Browser Chromium Suite** (`python3 backend/scripts/test_pages_playwright.py`): 17/17 pages passed with 0 unhandled JS exceptions.
- **Active Hub**: Online and healthy on `http://0.0.0.0:30102`.
---

## 13. Comprehensive User Guide: How to Use TraceScope (OTelTrace)

### 1. Access & Platform Entrypoints
- **Web UI URL**: `http://<NODE_IP>:30102`
  - Local workstation: `http://127.0.0.1:30102`
  - Cluster node: `http://129.150.59.233:30102`
- **Language Switcher**: Click the language badge in the upper-right header (`🇻🇳 VI` / `🇬🇧 EN`) to toggle instantly between Vietnamese and English. Your preference is persisted in browser storage.
- **Time Range Selector**: In the top header, choose observation windows: `15 Phút` (15m), `1 Giờ` (1h), `6 Giờ` (6h), `24 Giờ` (24h), `7 Ngày` (7d), or `15 Ngày` (15d).
- **Global Search**: Type any service name, principal username (e.g., `alice`, `mallory`), or 32-character trace ID to jump directly to that entity.

---

### 2. Primary Navigation & Features

#### A. Overview Dashboard (`/`)
- **8 User Behavioral Signals**: Top glanceable cards for Tracked Users, Active Accounts, High-Risk Users (score ≥ 60), Baseline Drift, Auth Success %, Error Rate, RPS, and Latency P95.
- **Traffic Velocity vs Error Dynamics**: Dual-axis chart comparing system throughput against 4xx/5xx error surges.
- **Risk Cohort Distribution**: Visual breakdown of accounts across High, Medium, and Low risk tiers.
- **Prioritized Anomalous Accounts**: Fast-action table listing accounts with behavioral shifts, current RPS, error rates, risk scores, and 1-click **Inspect** buttons.
- **Shared Credentials**: Highlights credentials concurrently used across multiple source IPs.
- **Live Behavioral Feeds**: Streaming timeline of changes and correlated security incidents.

#### B. User Intelligence & Workspace (`/users` & `/users/:principal`)
1. **User Directory (`/users`)**: Search, filter by risk tier (High, Medium, Low), and sort by risk score or RPS. Click any user to enter their dedicated workspace.
2. **Dedicated User Workspace (`/users/:principal`)**: Features a sticky entity header with user risk badge, current 5m RPS, active targets, and quick account switcher dropdown. Contains 6 specialized investigative tabs:
   - **Tab 1: Overview (`/overview`)**: 8 KPI cards with delta percentages vs 15-day baseline, live sparklines, RPS & P95 comparisons, and attack surface expansion summary.
   - **Tab 2: Activity & Performance (`/activity`)**: Throughput (RPS and req/min), 100% stacked HTTP status mix (2xx/4xx/5xx/timeout), multi-percentile latency area chart (p50, p95, p99), and interactive **Pinned Time-Slice Inspector** (click any bar or drag to inspect exact metrics in that 1-minute bucket).
   - **Tab 3: Access & Topology (`/topology`)**: Interactive `User → Caller Service → Target Service` canvas dependency graph, collapsible operation breakdown, and edge metrics drawer.
   - **Tab 4: Behavior Changes (`/changes`)**: Explains deviations using the **7 Questions Framework** (What happened, Who was affected, What changed vs baseline, etc.). Filter by change type and review operator overrides.
   - **Tab 5: Usage Patterns (`/patterns`)**: 24h × 7d temporal activity heatmap (identifying off-hours access), target service share bars, operation distribution, and client source IP baselines.
   - **Tab 6: Investigations (`/investigations`)**: Incident triage queue with hypotheses, BEFORE vs NOW metric comparison table, causal relationship chain, and operator action buttons (Acknowledge, Suppress, Mark Benign).

#### C. Anomalies & Incidents (`/anomalies`, `/anomalies/:id`)
- Detects 8 core system & user anomalies: Traffic Spike, Traffic Drop, Latency Shift, Error Rate Surge, New Service Edge, New Principal Relationship, New Operation, and Unusual Execution Time.
- Click any anomaly to view the **"What Changed Compared With Normal?"** explainability card, probable root cause heuristic, affected upstream callers (blast radius), and correlated trace evidence.

#### D. Distributed Traces Waterfall (`/traces`, `/traces/:id`)
- Multi-filter trace search: Filter by service, principal, status code, minimum duration, or time range.
- Click any trace row to render the interactive **Multi-Tier Execution Waterfall** showing parent-to-child span hierarchy, relative timing offsets, execution latency bars, and full span metadata.

#### E. Agent Fleet Monitor (`/agent-stats`, `/agent-stats/:node`)
- Real-time telemetry for eBPF / pcap sniffer probe agents across nodes.
- Monitors kernel drop rates, push rates, queue buffer occupancy, and process CPU/memory.
- Drill down into any agent node for detailed time-series telemetry charts, or delete stale nodes directly via the UI.

#### F. Services Directory (`/services`, `/services/:name`)
- Service catalog reporting health, operations breakdown, caller topologies, downstream dependencies, and active user distribution.

---

### 3. Step-by-Step Practical Walkthroughs

#### Walkthrough 1: Investigating an Anomalous Account
1. Open `http://<NODE_IP>:30102/` and check the **Prioritized Anomalous Accounts** table.
2. Locate an account with high risk (e.g. `mallory` with score 78).
3. Click the **Inspect** button to open `/users/mallory/overview`.
4. Review the KPI cards to see what spiked (e.g., RPS +280% or Error Rate +12%).
5. Switch to the **Behavior Changes** tab to review the 7-question explainability card detailing the exact novel operations or target services accessed.
6. Switch to the **Usage Patterns** tab to see if the activity occurred outside normal working hours on the 24h × 7d heatmap.
7. Switch to the **Investigations** tab to triage the incident and confirm root-cause trace links.

#### Walkthrough 2: Diagnosing a Latency or 5xx Outage
1. Navigate to **Traces** (`/traces`).
2. Set the status filter to `5xx` or set minimum duration to `> 500ms`.
3. Click on the slowest or failing trace in the list.
4. The **Trace Waterfall** will expand, showing exactly which downstream child span failed or introduced latency, along with the caller identity and error envelope attributes.

#### Walkthrough 3: Monitoring Probe Agent Health
1. Navigate to **Agent Fleet** (`/agent-stats`).
2. Check the fleet overview cards for any degraded agents or non-zero drop rates.
3. Click on a specific node (e.g., `node-worker-1`) to view historical buffer queue occupancy and CPU/memory usage charts.

---

### 4. Developer & Operator CLI Usage

#### Check Platform & Worker Status
```sh
# Lifecycle status check (Elasticsearch NodePort 32073, ClickHouse, Worker, and Web UI)
sh ./run_server.sh status

# Restart services if needed
sh ./run_server.sh restart
```

#### Sending Telemetry Data
```sh
# Ingest OTel / APM Trace Batches (Plain HTTP NodePort 30103 or Cluster Ingress 31561)
curl -X POST "http://127.0.0.1:30103/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{"events": [{"trace_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90", "span_id": "1234567890abcdef", "service": "order-service", "operation": "POST /checkout", "principal": "alice", "status": "200", "duration_ms": 42.5}]}'
```

#### Ingest Probe Agent Health Sample
```sh
curl -X POST "http://127.0.0.1:30102/api/agent/stats" \
  -H "Content-Type: application/json" \
  -d '{"schema_version": 1, "type": "agent_stats", "node": "worker-1", "instance_id": "inst-1", "sequence": 1, "status": "ok", "reasons": [], "metrics": {"drop_rate": 0.0, "queue_depth": 12, "push_rate": 150.0}}'
```

---

## 9. F5 BIG-IP Load Balancer Architecture & TraceScope Dual-IP Normalization

In Viettel production environments where all incoming traffic traverses an **F5 BIG-IP Local Traffic Manager (LTM)**:

### 1. The F5 SNAT Invariant
- **Source NAT (SNAT AutoMap / SNAT Pools)**: F5 replaces the original client's TCP Source IP with its own internal self-IP (e.g. `10.240.147.249`, `10.240.147.247`) before forwarding the request to backend nodes (e.g. `10.240.147.79`). This enforces symmetric return routing through F5's connection table.
- **Consequence for Raw Sockets**: At the L3/L4 TCP socket layer, 100% of incoming connections to backend application servers appear to originate from F5's SNAT IP.

### 2. Client IP Preservation Mechanisms
- **L7 Virtual Server (Standard VIP with HTTP Profile)**:
  - F5 HTTP Profile: `Insert X-Forwarded-For: Enabled` (automatically inserts or appends client IP to `X-Forwarded-For`).
  - F5 Custom iRule: Strips client-forged headers and inserts `X-Real-IP: [IP::client_addr]`.
- **L4 Virtual Server (FastL4 / SSL Pass-Through)**:
  - F5 cannot inspect or rewrite HTTP headers in L4 mode.
  - Requires **PROXY Protocol v1/v2** (via iRule or native PROXY profile) or **TCP Option Address (TOA)** kernel module on backend hosts.
- **F5 OneConnect (TCP Connection Multiplexing)**:
  - Reuses a single persistent backend TCP connection from F5 to handle requests from thousands of distinct client IPs. Each HTTP transaction in the same connection carries a different `X-Forwarded-For` / `X-Real-IP`.

### 3. Backend & APM Configuration
- **Spring Boot / Tomcat**:
  ```properties
  server.forward-headers-strategy=native
  server.tomcat.remoteip.remote-ip-header=x-forwarded-for
  server.tomcat.remoteip.protocol-header=x-forwarded-proto
  server.tomcat.remoteip.internal-proxies=10\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}
  ```
- **NGINX Reverse Proxy / Ingress**:
  ```nginx
  set_real_ip_from 10.240.147.0/24;
  real_ip_header X-Forwarded-For;
  real_ip_recursive on;
  ```

### 4. TraceScope Dual-IP Normalization Pipeline
- **Dual-IP Schema**:
  - `caller_ip`: Immediate L3 network peer (`10.240.147.249`). Classified by `classify_source_ip_role` as `role: "load_balancer"`, `attribution_confidence: "low"`.
  - `original_client_ip`: Real client/subscriber IP extracted from `X-Real-IP` (priority) or `X-Forwarded-For` (leftmost IP) whenever peer/client is in private RFC 1918 / `known_load_balancers`.
  - `original_client_ip_trusted`: Set to `1` when arriving through trusted F5 proxy, `0` for direct untrusted connections.
- **Behavioral Baselines & Anomaly Detection**:
  - User and identity baselines track `principal_name` and `original_client_ip`.
  - F5 SNAT IPs are excluded from identity-clustering algorithms, preventing false-positive shared-credential alarms caused by the F5 proxy hop.

---

## 6. JavaScript Safe Integer Precision & Testbed Reset State

### Anomaly ID 64-Bit Precision Guard
- **Issue**: Python/ClickHouse generated 64-bit `UInt64` anomaly IDs (e.g. `2626546521826421330`). In JavaScript (React SPA in browser), standard `JSON.parse` uses IEEE-754 double precision floats where `Number.MAX_SAFE_INTEGER = 9,007,199,254,740,991` ($2^{53} - 1$). Any integer above this limit loses precision and rounds least-significant digits (e.g., `2626546521826421330` -> `2626546521826421000`), causing 404 "Anomaly not found" upon frontend navigation.
- **Resolution**:
  1. `deterministic_anomaly_id` (`backend/app/repositories/anomaly_repository.py`): Updated hash derivation to `(raw_hash % 9_000_000_000_000_000) + 1`. Guarantees all newly generated IDs stay strictly within JavaScript's safe integer range without IEEE-754 precision loss.
  2. `get_anomaly` & `update_status` (`AnomalyRepository`): Added automatic fallback resolution within floating-point ULP tolerance ($\pm 4096$) for any IDs $> 9 \times 10^{15}$, allowing legacy or bookmarked URLs with trailing zeros to resolve seamlessly.
  3. `anomaly_users` (`UserRepository`): Added corresponding fallback resolution for related user lookups.

### Testbed Database Wipe
- Executed `backend/scripts/reset_testbed.py`:
  - Truncated all 40 ClickHouse analytical tables in `tracescope`.
  - Deleted all Elasticsearch APM indices (`apm-*`) on NodePort 32073.
  - Truncated internal ClickHouse system logs (`system.metric_log`, `system.query_log`, etc.) to reclaim memory.
  - Restarted services on port 30102 via `run_server.sh restart`.
  - Verified 48/48 End-to-End Curl & JS safety checks pass.

### Behavioral Change Events Deduplication (`principal_change_events FINAL`)
- **Issue**: `principal_change_events` table uses ClickHouse `ReplacingMergeTree() ORDER BY (fingerprint)`. In ClickHouse, `ReplacingMergeTree` keeps multiple unmerged rows across parts unless queries explicitly specify `FINAL`. Queries in `UserRepository` (such as `list_changes`, `summary`, `analytics`, `service_users`, and `graph`) were omitting `FINAL`. When the background worker ingested traces in periodic micro-batches within the 15-minute fingerprint window, duplicate events were returned, displaying redundant rows on `/users/:principal/changes` (e.g. 3 copies of each change for `-anonymous-`).
- **Resolution**:
  1. Updated all queries on `principal_change_events` in `UserRepository` (`user_repository.py`) to consistently use `FINAL` (matching `ReplacingMergeTree` semantics throughout the repository layer).
  2. Added defensive client-side deduplication by fingerprint/key in `UserChangesTab.tsx` to prevent redundant cards or duplicate React keys.
  3. Rebuilt frontend (`npm run build`) and restarted server on port `30102`. Verified all 48/48 curl/JS safety tests pass and verified `/api/v1/user-changes?principal=-anonymous-` returns 100% unique items.

---

## 7. LLM Diagnostic Investigation Deployment Readiness (Helm, K8s, Docker)

The LLM diagnostic investigation subsystem and its operator security layer are integrated and verified across all deployment targets:

### 1. Helm Chart (`deploy/helm/tracescope/`)
- **Version**: Bumped to SemVer `0.3.0` (`Chart.yaml`).
- **Values Configuration (`values.yaml`)**:
  - Added `llm:` block with defaults: `enabled: false`, `singleOwnerAck: false`, `baseUrl: ""`, `model: ""`, `responseMode: "json_object"`, `allowLoopbackHttp: false`, `contextTokens: 32768`.
  - Added `secrets.llmApiKey: ""` under `secrets:`.
- **Templates (`templates/configmap.yaml` & `templates/secret.yaml`)**:
  - Injects `OTEL_LLM_INVESTIGATION_ENABLED`, `OTEL_LLM_SINGLE_OWNER_ACK`, `OTEL_LLM_BASE_URL`, `OTEL_LLM_MODEL`, `OTEL_LLM_RESPONSE_MODE`, `OTEL_LLM_ALLOW_LOOPBACK_HTTP`, `OTEL_LLM_CONTEXT_TOKENS` into the shared ConfigMap.
  - Injects `OTEL_LLM_API_KEY` into the Secret.
- **Verification**: `helm lint` passes with 0 errors (`1 chart(s) linted, 0 chart(s) failed`). `helm template` verified for ConfigMap and Secret generation.

### 2. Kubernetes Plain Manifests (`deploy/k8s/`)
- `deploy/k8s/10-configmap.yaml`: Added `OTEL_LLM_*` environment variables with documentation.
- `deploy/k8s/11-secret.example.yaml`: Added `OTEL_LLM_API_KEY` secret placeholder.

### 3. Docker & Docker Compose
- `docker-compose.yml`: Parameterized `api` container with `OTEL_LLM_*` and `OTEL_API_KEY` environment variables, and `frontend` container with `VITE_API_KEY`.
- `Dockerfile` & `deploy/docker/Dockerfile`: Standardized multi-stage container build supporting optional build-time frontend environment arguments.

---

## 8. Presentation Layer Migration: RPS to TPS
- **Overview**: Standardized all user-facing throughput units, card metrics, chart axes, tooltip formatters, and table columns from "RPS" (Requests Per Second) and "req/s" to "TPS" (Transactions Per Second) and "tps".
- **Frontend Changes**:
  - `i18n.tsx`: Updated English & Vietnamese translations for `TPS`, `Throughput (TPS)`, `TPS vs Baseline`, `Observed TPS`, `Baseline TPS`, `Throughput TPS & Volume / Min`, `Transactions / Sec (TPS)`, `Observed Throughput (TPS)`, `Historical Baseline TPS`, and `Scaled behavioral anomaly & TPS surge (0–100)`.
  - `UserOverviewTab.tsx`: Metric card 2 updated to `{t("TPS")}`, Chart 1 updated to `{t("TPS vs Baseline")}`, tooltip formatters and area series names updated from `req/s` / `Observed RPS` to `tps` / `Observed TPS`, and anomaly risk card updated to `TPS scale:`.
  - `UserActivityTab.tsx`: Pinned slice metric card updated to `TPS` and `{selectedSlice.rps} tps`, section 1 header updated to `Throughput TPS & Volume / Min`, peak and average badges updated to `{maxRps} TPS` / `{avgRps} TPS`, and chart line series and tooltips updated to `Throughput (TPS)` and `tps`.
  - `UserTopologyTab.tsx`: Edge metric drawer card updated from `Throughput (RPS)` and `req/s` to `Throughput (TPS)` and `tps`.
  - `Overview.tsx`: Header action badge updated from `RPS:` to `TPS:`, Y-axis unit updated from `unit=" rps"` to `unit=" tps"`, tooltip formatters and chart legends updated to `tps` / `Observed Throughput (TPS)`.
  - `Services.tsx`: Chart subtitle and area series name updated from `Observed RPS` to `Observed TPS` and `Observed Throughput (TPS)`.
- **Backend Changes**:
  - `backend/app/repositories/user_repository.py`: Line 910 updated Before vs Now Comparison metric name from `"metric": "RPS"` to `"metric": "TPS"` for `/api/v1/users/{principal}/investigations`.
  - `backend/app/api/anomalies.py`: Lines 89 and 186 updated default non-latency/non-error anomaly unit from `"req/s"` to `"tps"`.
  - Fixed missing `import time` in `backend/app/api/anomalies.py`.
- **Verification**:
  - Frontend compiled clean (`npm run build`: 0 errors).
  - 165/165 tests passed in isolated pytest suite (`.venv/bin/python -m pytest tests/ -q`).
  - 48/48 End-to-End Curl & JS safety checks passed (`sh backend/scripts/curl_test_all_pages.sh`).

---

## 9. Investigation Auth Decoupling (Open Dashboard Option B)
- **Problem**: Deployments with `OTEL_LLM_INVESTIGATION_ENABLED=true` but without `OTEL_API_KEY` configured failed closed with `503 auth_unconfigured`. In clusters where the dashboard is already secured by edge ingress/gateway (or run in open developer mode), browser clients received 503 errors when loading `/source` for detected anomalies.
- **Solution (`backend/app/api/investigations.py`)**:
  - Made `investigation_auth` validate `X-API-Key` only when `settings.api_key` is non-empty.
  - When `settings.api_key` is empty (`OTEL_API_KEY=""`), investigation routes (`/api/v1/investigations/*`) permit open access matching the rest of the dashboard telemetry endpoints.
  - When `settings.api_key` is configured, strict `X-API-Key` verification via `hmac.compare_digest` continues to be strictly enforced (HTTP 401 on missing or mismatched key).
- **Verification**: Pytest unit and security tests passed (`tests/test_llm_investigation_*.py`), `py_compile` succeeded with code 0.

---

## 10. LLM Investigation Invalid Output Diagnosis & Resilient Formatting Fix

### 1. Root Cause Diagnosis
When the LLM investigation subsystem invoked the configured model (`deepseek-v4.1-flash` via `https://api.ai-box.vn/v1`), runs failed with `failure_code: "invalid_output"`. Empirical diagnostics and direct curl testing identified three contributing factors:
1. **Token Exhaustion (`finish_reason: "length"`)**: DeepSeek V4/R1 reasoning models allocate hundreds of tokens to internal `reasoning_content` (chain of thought). Because `GenerationRequest.max_tokens` was capped at `1000` in both `investigation_provider.py` and `investigation.py`, the token budget was completely consumed by reasoning before outputting the full JSON payload, resulting in an empty or truncated `content` string with `finish_reason: "length"`.
2. **Sub-Object Prompt Schema Vagueness**: Without explicit JSON schema templates in the prompt, the model returned `missing_evidence` as an array of strings (e.g. `["missing data"]`) rather than objects matching `MissingEvidence` (`[{"code": "unavailable", "explanation": "..."}]`), causing Pydantic `ValidationError` in `_validate_reply`.
3. **Parser Vulnerability to Code Fences and Thinking Tags**: If any model wrapped JSON inside markdown fences (````json ... ````) or `<think>...</think>` tags, raw `json.loads` failed with `JSONDecodeError`, returning `invalid_output`.

### 2. Implementation Changes
- **`backend/app/services/investigation_provider.py`**:
  - In `_parse_object`: Added defensive trimming of whitespace, `<think>...</think>` tag stripping, markdown code fence removal, and robust extraction of outermost `{...}` JSON blocks.
  - In `GenerationRequest`: Increased default `max_tokens` from `1000` to `4000`.
  - In `OpenAICompatibleProvider.generate()`: Updated token budget clamp from `min(1000, request.max_tokens)` to `min(4000, request.max_tokens)`.
- **`backend/app/prompts/investigation_v1.txt`**:
  - Added explicit compact JSON schema for `assessment-v1` detailing the structure and enum constraints for `hypotheses`, `missing_evidence` (`code`, `explanation`, `related_evidence_ids`), and `recommendations` (`action`, `evidence_ids`, `rationale`).
  - Added strict instructions that all cited evidence and calculation IDs must be exact matches from the input telemetry items and calculations.
- **`backend/app/services/investigation.py`**:
  - Updated `_generate`: Set `max_tokens=4000` for both the initial generation request and the repair request.
- **`tests/test_llm_investigation_unit.py`**:
  - Added unit test `test_parse_object_resilience` covering raw JSON, markdown fences, `<think>` blocks, surrounding text, duplicate keys, and invalid types.

### 3. Live Verification & Test Suite
- **Live LLM API Test**: Executed real API call to `https://api.ai-box.vn/v1` with `deepseek-v4.1-flash`:
  - `finish_reason`: `stop`
  - `prompt_tokens`: 973, `completion_tokens`: 1092 (reasoning + text)
  - Result parsed and validated via `InvestigationRunner._validate_reply` with **0 errors**.
- **Pytest Suite**: 166/166 tests passed in `.venv/bin/python -m pytest tests/ -q` (including all 13 investigation unit, api, integration, and security tests).

---

## 11. Unified Global Helm Image Tag Resolution (`global.image.tag` / `0.3.3`)

### 1. Architectural Motivation
Previously, the Helm chart required modifying multiple component tags individually (e.g. `app.image.tag: app-0.3.2`, `ingest.image.tag: ingest-0.3.2`, `agentStats.image.tag: app-0.3.2`, `ui.image.tag: app-0.3.2`). Since all application components share the unified Docker repository (`xhatsu101/tracescope`), requiring distinct tags caused release friction.

### 2. Implementation Changes
- **Chart Metadata (`deploy/helm/tracescope/Chart.yaml`)**:
  - Bumped `version` and `appVersion` to `"0.3.3"`.
- **Global Helper Template (`deploy/helm/tracescope/templates/_helpers.tpl`)**:
  - Added `tracescope.globalImageTag` helper resolving:
    1. `.Values.global.imageTag` (CLI override flag)
    2. `.Values.global.image.tag` (structured values)
    3. `.Chart.AppVersion` (`"0.3.3"`)
- **Template Integration**:
  - `storage-statefulset.yaml`: Migrations initContainer, API container, and Analytics Worker container all resolve their image tag against `tracescope.globalImageTag` when component tag is empty or unset.
  - `ingest-deployment.yaml`: Ingest container defaults to `{{ default (include "tracescope.globalImageTag" .) .Values.ingest.image.tag }}`.
  - `agent-stats-deployment.yaml`: Agent stats container defaults to `{{ default (include "tracescope.globalImageTag" .) .Values.agentStats.image.tag }}`.
  - `ui-deployment.yaml`: Standalone Nginx UI container defaults to `{{ default (include "tracescope.globalImageTag" .) .Values.ui.image.tag }}`.
  - `agent-stats-service.yaml`: Guarded `.Values.agentStats.service` with `$svc := default dict .Values.agentStats.service` to eliminate nil-pointer evaluation when service block is omitted.
  - Database decoupling: `clickhouse/clickhouse-server:24.8` remains unaffected by the application image tag.
- **Default Values (`deploy/helm/tracescope/values.yaml`)**:
  - Configured `global.image.tag: "0.3.3"`.
  - Cleared component tags (`app.image.tag: ""`, `ingest.image.tag: ""`, `agentStats.image.tag: ""`, `ui.image.tag: ""`) so all components automatically inherit the global tag.
  - Operators can now change versions with a single edit in `values.yaml` or `--set global.image.tag=0.3.3` (or `--set global.imageTag=0.3.3`).
  - Retained per-component override capability (e.g. `--set ingest.image.tag=custom-tag`).
- **Documentation (`deploy/helm/tracescope/README.md`)**:
  - Updated configuration table documenting `global.image.tag`.

### 3. Verification & Automated Tests
- **Helm Lint**: `helm lint deploy/helm/tracescope` passed cleanly with 0 errors (`1 chart(s) linted, 0 chart(s) failed`).
- **Helm Template Matrix**: Verified image tag rendering across all 4 scenarios:
  1. Default values: all 6 TraceScope containers rendered `xhatsu101/tracescope:0.3.3`.
  2. Dynamic `--set global.image.tag=0.3.4`: all 6 containers rendered `xhatsu101/tracescope:0.3.4`.
  3. Dynamic `--set global.imageTag=0.3.5`: all 6 containers rendered `xhatsu101/tracescope:0.3.5`.
  4. Per-component override `--set ingest.image.tag=ingest-custom`: ingest rendered `xhatsu101/tracescope:ingest-custom` while app, worker, and agentStats remained `0.3.3`.
- **Automated Regression Suite**: Added `test_helm_global_image_tag_and_component_overrides` to [`tests/test_deployment_topology.py`](file:///home/ubuntu/Viettel/OtelTrace/tests/test_deployment_topology.py); all 27 deployment topology tests passed (`.venv/bin/python -m pytest tests/test_deployment_topology.py -v`).

---

## 12. Build and Push Script Unified Image Tag Support (`scripts/build_and_push.sh`)

### 1. Architectural Motivation & Problem Statement
When running `./deploy/docker/build_and_push.sh xhatsu101/tracescope 0.3.3`, the script outputted component-prefixed tags (`xhatsu101/tracescope:app-0.3.3` and `xhatsu101/tracescope:ingest-0.3.3`), but did not output or push the global version tag `xhatsu101/tracescope:0.3.3` expected by Helm's `global.image.tag: "0.3.3"`.

### 2. Implementation Details
- **Unified Build Target**:
  - Main App (`--target api`) in [`scripts/build_and_push.sh`](file:///home/ubuntu/Viettel/OtelTrace/scripts/build_and_push.sh) (symlinked by `deploy/docker/build_and_push.sh`) builds and tags both `$GLOBAL_IMAGE` (`xhatsu101/tracescope:0.3.3`) and `$APP_IMAGE` (`xhatsu101/tracescope:app-0.3.3`) using `-t $GLOBAL_IMAGE -t $APP_IMAGE`.
  - Pushes both `$GLOBAL_IMAGE` and `$APP_IMAGE` when push mode is active.
  - Retains standalone Ingest build (`--target ingest`) tagged as `$INGEST_IMAGE` (`xhatsu101/tracescope:ingest-0.3.3`).
- **Target Selection Flags**:
  - Added `--unified-only` (`-u`): Builds and pushes only the unified multi-role image (`:0.3.3` and `:app-0.3.3`), skipping standalone ingest image build.
  - Added `--ingest-only`: Builds and pushes only the standalone ingest image (`:ingest-0.3.3`).
- **Ingest Workload Interchangeability**:
  - Added explicit container command in [`deploy/helm/tracescope/templates/ingest-deployment.yaml`](file:///home/ubuntu/Viettel/OtelTrace/deploy/helm/tracescope/templates/ingest-deployment.yaml):
    ```yaml
    command: ["uvicorn", "backend.ingest_main:app", "--host", "0.0.0.0", "--port", "8000"]
    ```
  - This ensures that if the unified image `xhatsu101/tracescope:0.3.3` is deployed to ingest pods, it starts `backend.ingest_main:app` instead of defaulting to the Dockerfile CMD `backend.main:app`.
- **POSIX Shell Standard**:
  - Retained strict 100% standard POSIX `/bin/sh` syntax without any bashisms.

### 3. Verification & Dry Run Outputs
- Verified `sh ./deploy/docker/build_and_push.sh xhatsu101/tracescope 0.3.3 --dry-run`:
  ```
  [DRY RUN] Would execute:
    docker build -f .../Dockerfile --target api -t xhatsu101/tracescope:0.3.3 -t xhatsu101/tracescope:app-0.3.3 ...
    docker build -f .../Dockerfile --target ingest -t xhatsu101/tracescope:ingest-0.3.3 ...
    docker push xhatsu101/tracescope:0.3.3
    docker push xhatsu101/tracescope:app-0.3.3
    docker push xhatsu101/tracescope:ingest-0.3.3
  ```
- Verified `sh ./deploy/docker/build_and_push.sh xhatsu101/tracescope 0.3.3 --unified-only --dry-run`:
  ```
  [DRY RUN] Would execute:
    docker build -f .../Dockerfile --target api -t xhatsu101/tracescope:0.3.3 -t xhatsu101/tracescope:app-0.3.3 ...
    docker push xhatsu101/tracescope:0.3.3
    docker push xhatsu101/tracescope:app-0.3.3
  ```
- Pytest test suite: 27/27 passed in `tests/test_deployment_topology.py` and 167/167 passed across the full test suite.

---

## 13. Investigation Model UUID Coercion & Verification APIs (`/api/v1/investigations`)

### 1. Root Cause Analysis of Persistent "invalid output" on `https://trace.n2d.id.vn/anomalies/7057330353030513`
1. **Deduplication Cache Hit**:
   - Investigation `38b0b0e5-9980-5371-b11e-453f086c6485` previously failed on the server with `failure_code: "invalid_output"`.
   - When a user clicks "Investigate" without supplying `retry_of`, `submit()` computes the deterministic deduplication key for `retry_index = 0`, finds the existing run, and immediately returns `reused: true, state: "failed"` without invoking the LLM.
2. **Pydantic Strict Mode Blocked Retries**:
   - When attempting to retry via `POST /api/v1/investigations` with `{"retry_of": "38b0b0e5-9980-5371-b11e-453f086c6485"}`, `InvestigationCreate` inherited from `StrictModel` (`strict=True`).
   - Pydantic strict mode rejected string UUID values: `Input should be an instance of UUID [type=is_instance_of, input_value='38b0b0e5...', input_type=str]`.
   - As a result, the API rejected any retry payload with HTTP 422 `{"code": "invalid_request"}`.
3. **Model Validation Verified with New Code**:
   - Executing the exact live anomaly bundle (`7057330353030513`) with `deepseek-v4.1-flash` against the updated codebase passed `InvestigationRunner._validate_reply` with 100% success (`finish_reason: "stop"`, 2582 completion tokens).

### 2. Implementation Changes
- **`backend/app/models/investigation.py`**:
  - Added `@field_validator("retry_of", mode="before")` to `InvestigationCreate` to parse incoming string UUIDs into `uuid.UUID` before strict model validation.
- **`tests/test_llm_investigation_unit.py`**:
  - Added unit test `test_investigation_create_coerces_uuid_string` (14/14 tests passing).

### 3. Investigation Testing APIs
- **Step 1: Check Source Snapshot and Latest Run ID**:
  ```sh
  curl -s "https://trace.n2d.id.vn/api/v1/investigations/source?kind=anomaly_event&id=7057330353030513"
  ```
- **Step 2: Submit Retry for Previous Run (Once 0.3.3 image deployed)**:
  ```sh
  curl -s -X POST "https://trace.n2d.id.vn/api/v1/investigations" \
    -H "Content-Type: application/json" \
    -d '{
      "finding": {"kind": "anomaly_event", "anomaly_event_id": "7057330353030513"},
      "source_version": "a7a27f9cac56beb25f095e8fdbce7f97f2f702f8465aea046d4a48a7f0b3c189",
      "retry_of": "38b0b0e5-9980-5371-b11e-453f086c6485"
    }'
  ```
- **Step 3: Poll Investigation Status and Result**:
  ```sh
  curl -s "https://trace.n2d.id.vn/api/v1/investigations/<RUN_ID>"
  ```
- **Step 4: View History**:
  ```sh
  curl -s "https://trace.n2d.id.vn/api/v1/investigations?kind=anomaly_event&id=7057330353030513"
  ```

---

## 18. Continuous Incident Coalescing, Detector Maturity Gating & UI Episode Grouping

### 1. Root Cause of Repetitive "Unusual Time" Alerts
- **Mechanism**:
  - The aggregation worker evaluates 5-minute telemetry windows.
  - When traffic continuously arrived every 5 minutes (e.g., 10:00, 10:05, 10:10, 10:15...), a new anomaly record with a new ID was created for each 5-minute bucket, generating 83+ separate records for the same endpoint (`port:80` `/api/radio/status`, `/opc/v2/instance/`).
  - Detector 8 (`unusual_time`) checked hour-of-day (02:00–04:00 UTC = 09:00–12:00 AM local UTC+7). When new or anonymous traffic started without historical baseline samples, it compared against a 0.0 baseline and raised false-positive alerts on cold start.

### 2. Backend Incident Coalescing (`backend/app/repositories/anomaly_repository.py`)
- **Contiguous Window Coalescing**:
  - `AnomalyRepository.save_anomalies` queries recent open incidents (`status IN ('open', 'acknowledged')` within the last 30 minutes).
  - For contiguous 5-minute windows (arrival within 15 minutes of prior `last_seen`), anomalies matching the same signature `(anomaly_type, caller_service, target_service, principal_name, source_ip, operation)` are coalesced into the active incident.
  - Reuses the existing deterministic incident `id`, updates `last_seen`, preserves `first_seen`, increments `metadata.occurrences`, calculates cumulative `metadata.duration_mins`, and updates severity/score to the peak.
  - ClickHouse's `ReplacingMergeTree ORDER BY id` replaces the existing row cleanly, eliminating repetitive alert spam while preserving single-row incident continuity.

### 3. Detector Maturity Gate (`backend/app/services/anomaly_detection.py`)
- **Detector 8 (`unusual_time`)**:
  - Excludes anonymous traffic (`"-anonymous-"`, `"anonymous"`, empty user).
  - Excludes machine accounts (`system`, `probe`, `agent`, `daemon`, etc.).
  - Enforces baseline maturity requirement: `sample_count >= 10` before flagging "unusual time", ensuring normal traffic starting on cold-start is never falsely alerted without established historical baseline.

### 4. Frontend Episode Grouping (`frontend/src/pages/Anomalies.tsx`)
- **Toggle Control**:
  - `Group Incidents` (default) vs `Raw Findings` in the filter bar.
- **Aggregated Incident Episodes**:
  - Consolidates recurring 5-minute slices into single episodes.
  - Displays recurrence badge (`Nx recurrent` in violet pill), combined time span (`10:00 AM – 10:30 AM (30m)`), latest/peak values, and combined delta.
  - Expandable sub-slice accordion: Click to inspect individual 5-minute telemetry slices with direct navigation to the exact slice detail.
- **DOM Hierarchy & React Safety**:
  - Replaced illegal nested `<tbody key={grp.groupKey}>` elements inside parent `<tbody>` with `<Fragment key={grp.groupKey}>`.
  - In standard HTML and React DOM, nesting `<tbody>` within `<tbody>` violates the table specification and breaks DOM tree reconciliation, triggering React unhandled DOM exceptions and crashing the page.
  - Added safe numeric/Date conversions with fallbacks for `rawStart`, `rawEnd`, and sub-slice timestamps to prevent `RangeError: Invalid time value`.

---

## 19. Default Vietnamese Output for LLM Investigation Responses

### 1. Requirements & Scope
- Operators requested that natural-language outputs from LLM diagnostic investigations (`hypotheses`, `alternatives`, `missing_evidence`, and `recommendations`) default to authentic, professional Vietnamese (Tiếng Việt).
- Programmatic machine-read contracts (JSON schema keys, enum constants like `"assessment-v1"`, `"explained"`, `"low"`, `"unavailable"`, `"inspect_trace_sample"`, and exact `evidence_id` references) must strictly remain intact for client validation.

### 2. Implementation Changes
- **`backend/app/prompts/investigation_v1.txt`**:
  - Added high-priority `LANGUAGE RULE`:
    - "All human-readable explanations, hypothesis statements, alternative explanations, missing evidence explanations, and recommendation rationales MUST be written in clear, professional Vietnamese (Tiếng Việt)."
    - "Keep all schema keys, enum values, and exact evidence/calculation IDs in their required exact code format."
  - Updated JSON schema template with Vietnamese placeholder text for `statement`, `alternatives`, `explanation`, and `rationale`.
  - Added Rule 7 to `CRITICAL SCHEMA RULES`: "Output all statement, alternatives, explanation, and rationale fields in Vietnamese (Tiếng Việt)."
- **`backend/app/services/investigation.py`**:
  - Updated the second-attempt repair prompt to request "Return only assessment-v1 JSON with Vietnamese descriptions."
- **`backend/app/models/investigation.py`**:
  - Verified that UTF-8 Vietnamese diacritics (e.g., `à, á, ả, ã, ạ, ê, ô, ư, đ`) pass `validate_note` and `CONTROL` character checks without restrictions.

### 3. Verification & Live Model Test
- Executed `test_model_live.py` with `deepseek-v4.1-flash` on the live anomaly bundle (`7057330353030513`):
  - Model generated fluent, professional Vietnamese for `statement`, `alternatives`, `explanation`, and `rationale`.
  - Exact code enums and evidence IDs (`source-0`, `related_changes-*`, `attached_baseline-*`) were preserved.
  - Pydantic validation via `InvestigationRunner._validate_reply` succeeded with **0 errors**.
---

## 20. Architectural Strategy for `-anonymous-` (Unauthenticated Traffic) & Review Guide

### 1. Context & Architectural Problem
- Unauthenticated transactions (missing auth headers, public API calls, health probes, crawlers) are currently assigned `principal_name = "-anonymous-"` (or `"unknown"`).
- Because thousands of unrelated clients share this single pseudo-user, `-anonymous-` fans out to hundreds of source IPs and target services, inflating its behavioral score to 100 and polluting the "Top Risky Accounts" cohort.
- Furthermore, the User Directory (`/users`) lists `-anonymous-` as if it were a real employee or service account.

### 2. Proposed Strategy: "Pseudo-Entity Segregation"
- **Data Invariant**: Retain all trace data and metric rollups for `-anonymous-` without dropping rows, guaranteeing 100% accurate service throughput (TPS), error rates, and p50/p95/p99 latency metrics.
- **Behavioral & Identity Engine**: Exclude `-anonymous-` from user risk scoring (behavior_score = 0). Shift unauthenticated threat detection to **Source IP Anomaly** (`caller_ip: unusual_access`, `ip_new_endpoint`) and **Endpoint Security** (401/403 `auth_failure_burst`).
- **User Directory**: Default to filtering out `-anonymous-` from `/api/v1/users`, with an explicit toggle `include_anonymous=true` and a neutral badge `[Public / Unauthenticated Traffic]`.

### 3. Review Artifacts Generated
- **Comprehensive Architecture Plan**: [`PLAN_ANONYMOUS_USER_HANDLING.md`](file:///home/ubuntu/.gemini/antigravity-cli/brain/b7e6946a-d567-447c-8b05-0313a8ad8f01/PLAN_ANONYMOUS_USER_HANDLING.md).
- **Codex (GPT-6 ASTRA Medium) Review Guide & Prompt**: [`GUIDE_PLAN_CODEX_REVIEW.md`](file:///home/ubuntu/.gemini/antigravity-cli/brain/b7e6946a-d567-447c-8b05-0313a8ad8f01/GUIDE_PLAN_CODEX_REVIEW.md).

---

## 21. Completed Implementation: F5 Load Balancer IP Resolution & Anonymous Traffic Segregation

### 1. F5 Load Balancer IP Resolution without Client Guessing
- **Core Principle**: Do NOT guess client IP when telemetry only sees the F5 load balancer address without trusted `X-Forwarded-For` or `X-Real-IP`.
- **Quality Attributes (`backend/app/models/trace.py`, `backend/app/services/normalization.py`)**:
  - `observed_ip = F5 IP`: The physical network connection peer.
  - `effective_client_ip = "unavailable"`: Never falsely set to F5 IP.
  - `ip_resolution = "load_balancer_unresolved"`: Explicitly states LB hop is unresolved.
  - `client_identity_quality = "low"`
  - `context_quality`: 4-tier ladder (`high`, `medium`, `low`, `very_low`).
- **Infrastructure IP Categorization (`backend/config.py`)**:
  - Configurable categories: `known_f5` (`OTEL_KNOWN_F5`), `known_lb` (`OTEL_KNOWN_LB`), `known_reverse_proxy` (`OTEL_KNOWN_REVERSE_PROXY`), `known_nat` (`OTEL_KNOWN_NAT`).
  - Helper `is_known_infrastructure_ip(ip)`: Detects explicit infrastructure addresses without conflating general internal private LAN client IPs (e.g. `10.0.0.2`).
- **IP Behavioral Suppression Behind Unresolved LBs**:
  - `backend/app/services/principal_relationships.py`: Unresolved LB/F5 IPs are suppressed from `NEW_SOURCE_IP`, `NEW_PRINCIPAL_ON_SOURCE`, and `NEW_IP_CALLER_PAIR`. F5 is never recorded as an individual user's personal source IP in `principal_sources`.
  - `backend/app/services/anomaly_detection.py`: When `source_ip` is an unresolved LB/F5, `user_new_source_ip` and `ip_new_user` are suppressed.

### 2. Anonymous Traffic Handling (`user = -anonymous-`)
- **Core Principle**: `-anonymous-` is a Traffic Class, NOT a user identity.
- **Identity Analytics Exclusion**:
  - Excluded from `principals` table bootstrapping, baselines, and relationship generation (`principal_name NOT IN ('unknown', '-anonymous-', 'anonymous', '')`).
  - Excluded from `UserRepository().list_users()` by default (accessible via `include_anonymous=True`).
  - Excluded from `UserRepository().analytics()`: Never appears in `most_active`, `most_changed`, `shared_credentials`, or `dormant_reactivated`.
  - Never assigned a user risk score, never creates user security incidents.
- **100% Telemetry Analytics Retention**:
  - Retains all traces, metric rollups, TPS, RPS, error rates, p50/p95/p99 latency, and service topology dependencies.
  - `UserRepository().summary()` reports `anonymous_requests` and `anonymous_traffic_percentage` (e.g., 9.0% anonymous vs 91.0% identified traffic).
- **Endpoint-Centric Anonymous Anomaly Detection**:
  - Combined worst-case (`anonymous + unresolved F5`) shifts from user-centric to **Endpoint & Traffic-centric behavioral analysis**:
    - `anonymous_new_endpoint`: Novel endpoint accessed anonymously.
    - `auth_failure_burst`: 401/403 authorization bursts.
    - Emits structured Anonymous Anomaly Events (`principal_name = None`, `metadata = {"traffic_class": "anonymous"}`).
- **Frontend Glanceable Visibility (`frontend/src/pages/Overview.tsx`)**:
  - Added live header pill: `Lưu lượng Định danh: 91.0% | Ẩn danh: 9.0%` with full Vietnamese localization.

### 3. Verification & Safety Test Results
- **Pytest Suite**: **174/174 tests passed** (`.venv/bin/python -m pytest tests/ -q` in 02:20).
  - Verified F5 unresolved IP handling and quality ladder (`tests/test_f5_lb_normalization.py`).
  - Verified F5 IP anomaly suppression and anonymous user isolation (`tests/test_user_ip_anomalies.py`).
  - Verified identity normalization and security incident boundaries (`tests/test_identity_normalization_and_incidents.py`).
- **Curl & JavaScript Safety Suite**: **48/48 tests passed** (`sh backend/scripts/curl_test_all_pages.sh`).
- **Frontend Build**: Built cleanly with Vite and TypeScript compiler (`tsc -b && vite build` in 10.77s).
- **Port 30102 Status**: Online, healthy, serving all 20 SPA routes and 28 backing APIs.

---

## 13. OpenTelemetry Collector Telemetry Metrics Migration Fix

### Issue Encountered
`otel-collector` pod in namespace `observability` crashed on startup with:
```text
Error: failed to get config: cannot unmarshal the configuration: decoding failed due to the following error(s):
'service.telemetry.metrics' decoding failed due to the following error(s):
'migration.MetricsConfigV030' has invalid keys: address, no need for metrics
```

### Root Cause
1. **Schema Migration (`migration.MetricsConfigV030`)**: In OpenTelemetry Collector Contrib (`otel/opentelemetry-collector-contrib:latest`), `service.telemetry.metrics.address` is deprecated/removed and replaced with `readers` specifying pull/push exporters.
2. **Invalid YAML Key (`no need for metrics`)**: Raw text `no need for metrics` was unquoted and uncommented under `metrics:`, causing YAML to parse it as an invalid dictionary key.

### Applied Configuration (`/home/ubuntu/agy/otel-obi/otel-collector.yaml`)
Configured modern Prometheus metrics reader on port 8888 (matching the existing Service `otel-collector` port 8888 and Deployment containerPort 8888):
```yaml
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
*(If internal metrics are not needed, `level: none` can be used instead).*
- Validated with Python YAML parser across all 4 documents in `/home/ubuntu/agy/otel-obi/otel-collector.yaml`.

---

## 14. Web Prometheus Metrics Exposition (`/metrics`)

### Implementation Overview
Exposes standard Prometheus 0.0.4 text exposition format at `GET /metrics` on port 30102 (and all roles):
- **Web Application Performance Metrics**:
  - `http_requests_total{method, handler, status}`: Real-time request counts partitioned by HTTP method, parameterized route template, and status code.
  - `http_request_duration_seconds_bucket{method, handler, le}`: Full request latency histogram with standard buckets (`0.005` to `10.0` and `+Inf`), plus `_sum` and `_count`.
  - `http_requests_in_progress`: Current active in-flight request gauge.
- **Process & System Metrics**:
  - `process_resident_memory_bytes`: Accurate RSS memory usage directly from Linux `/proc/self/statm`.
  - `process_cpu_seconds_total`: Total user and system CPU time spent.
  - `process_start_time_seconds` & `process_uptime_seconds`.
- **Ingestion & Engine Telemetry**:
  - `tracescope_ingest_writer_queue_depth`, `tracescope_ingest_writer_alive`, `tracescope_ingest_writer_committed_total`, `tracescope_ingest_writer_batches_total`.
  - `tracescope_service_info{version="0.3.3", role="...", backend="..."}`.
- **Estate & ClickHouse Counters**:
  - `nt_otel_server_spans_total`, `nt_requests_total`, `nt_nodes_reporting`, etc., preserved for backward compatibility.
- **High Cardinality Protection**:
  - Parameterized route templates resolved from Starlette ASGI scope (`/api/v1/services/{service}`).
  - Arbitrary UUIDs, transaction IDs, and hex hashes masked to `{id}`.
  - 404 unrouted scanners collapsed into `not_found`.

### Kubernetes & Prometheus Scraping Configuration
1. **Standard Service Annotations (`deploy/k8s/31-api-service.yaml` & `deploy/helm/tracescope/templates/api-service.yaml`)**:
   ```yaml
   annotations:
     prometheus.io/scrape: "true"
     prometheus.io/port: "30102"
     prometheus.io/path: "/metrics"
   ```
2. **Prometheus Operator ServiceMonitor (`deploy/k8s/35-prometheus-servicemonitor.example.yaml`)**:
   Ready for Prometheus Operator / `kube-prometheus-stack` scraping every 15s.
3. **Standalone Prometheus Scrape Job (`prometheus.yml`)**:
   ```yaml
   scrape_configs:
     - job_name: 'tracescope-web'
       scrape_interval: 15s
       metrics_path: '/metrics'
       static_configs:
         - targets: ['<host-or-node-ip>:30102']
   ```

### Worker Cadence Domain Metrics Update (Decoupled from HTTP Scrapes)
- **Problem Avoided**: Running heavy ClickHouse aggregations (`SELECT count() FROM traces`, `SELECT SUM(...) FROM metric_buckets`, `SELECT principal_name ...`) on every 15-second Prometheus scrape causes unnecessary CPU and I/O load on the database.
- **Worker Stage (`update_prometheus_metrics`)**:
  - `backend.worker` executes the heavy aggregations **strictly once per worker cycle** (e.g. every 60s or upon worker invocation).
  - Snapshot is written to ClickHouse checkpoint `checkpoints(source='worker_prometheus_metrics')` and cached to `/tmp/tracescope_worker_metrics.json`.
- **Fast HTTP Scrape (0 DB Load)**:
  - `GET /metrics` directly reads the cached worker snapshot in memory or from local cache in sub-millisecond time.
  - Zero heavy ClickHouse queries executed during Prometheus scraping.
  - In-memory web request metrics (`http_requests_total`, `http_request_duration_seconds`, `process_*`) update live with incoming HTTP traffic.
  - Exposes `tracescope_worker_last_run_timestamp_seconds` and `tracescope_worker_cycle_duration_seconds`.

### Verification & Testing
- `tests/test_prometheus_metrics.py`: 6/6 passed.
- Full pytest test suite: **178/178 passed** in 02:06.
- Worker end-to-end integration verified: `python -m backend.worker --once` successfully executed stage `update_prometheus_metrics`.
- Live verified on `http://127.0.0.1:30102/metrics` exposing `tracescope_worker_last_run_timestamp_seconds` and precomputed domain counters without database delay.

---

### Pure TPS & Historical Baseline Chart Refactor (Overview Dashboard)
- **Problem**:
  - The Overview series chart hardcoded `"baseline_rps": rps` in `backend/repository.py:dashboard_series`, causing the baseline line to be completely identical to the observed throughput.
  - The chart mixed TPS with 5xx error rate and dual Y-axes, confusing users looking strictly at traffic volume and historical expectations.
- **Backend Fix (`backend/repository.py`)**:
  - `dashboard_series` now queries `baseline_metrics` (`rps_median`) grouped by `(hour_of_day, day_of_week)` matching the active filter (service, account, operation, or system-wide sum across all services).
  - Each point's `baseline_rps` and `baseline_tps` reflect true historical median expectations with graceful fallback to historical medians.
  - `dashboard_summary` returns `baseline_rps` and `baseline_tps` for the aggregate window.
- **Frontend Refactor (`frontend/src/pages/Overview.tsx` & `i18n.tsx`)**:
  - Refactored panel to "Tốc độ Thông lượng Định danh & Chuẩn Lịch sử" (`Identity Traffic Velocity & Historical Baseline`).
  - Action header shows `TPS: {observed_tps} • Chuẩn Lịch sử: {baseline_tps}`.
  - Removed 5xx error rate line and secondary right Y-axis, rendering a clean, pure TPS area chart with purple dashed historical baseline.
  - Tooltip formatted strictly for TPS (`{val} tps`).
  - End-to-end verified with `curl_test_all_pages.sh` (48/48 passed, 0 JS errors).

---

### 7-Day & 30-Day Global Time Range Redesign & Multi-Grain Downsampling
- **Global Header Control (`frontend/src/App.tsx`)**:
  - Added `7d` (168h) and `30d` (720h) presets alongside `1h`, `3h`, `6h`, `24h`.
  - Added `Math.abs(rangeHours - hours) <= 1` active state check and hover title tooltips.
  - Dynamic Rollup Badge: shows `60s rollup` for $\le 36\text{h}$, `5m rollup` for $36\text{h} < \Delta \le 192\text{h}$, and `1h rollup` for $> 192\text{h}$.
- **User Topology Presets (`frontend/src/pages/user/UserTopologyTab.tsx`)**:
  - Added `7d` and `30d` filter buttons alongside `5m`, `1h`, `24h`, and `all`.
- **Backend Dynamic Downsampling (`backend/repository.py` & `backend/app/repositories/user_repository.py`)**:
  - Automatically downsamples `dashboard_series` into 5-minute buckets for 7d (giving ~627 points) and 1-hour buckets for 30d (giving ~275 points), avoiding 43,200-point payload transfers.
  - Automatically downsamples `user_repository:performance` into 5m or 1h buckets for multi-day queries.
- **Chart Date Formatting (`Overview.tsx`, `UserOverviewTab.tsx`, `UserActivityTab.tsx`)**:
  - XAxis displays `M/D HH:mm` when range $> 24\text{h}$ and Tooltip displays full locale date+time.
- **Verification**:
  - Vite build passed (`npm run build`).
  - 48/48 curl and JS safety tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - API responses for 7d and 30d verified working cleanly.

---

### Anomaly Detail Incident Time Horizon Line Graph Fix (2026-09-18)
- **Problem**:
  - Investigating finding URLs such as `http://129.150.59.233:30102/anomalies/6130971176347858?start=1789687202539&from=1789687202539&end=1789698062539&to=1789698062539&timezone=UTC&comparison=previous` rendered a completely blank/empty chart in "Incident Time Horizon: Actual vs Expected Baseline".
- **Root Causes**:
  1. **Series Timestamps**: Backend returned raw seconds `bucket_start` (~1.789e9) whereas Recharts XAxis and `ReferenceArea` expected milliseconds (~1.789e12).
  2. **Series Data Keys**: Backend raw series provided `{requests, errors, error_rate, latency_avg, latency_p95}` with no `rps` or `actual` keys. The frontend was doing `<Area dataKey={metric} />` where `metric = "rps"`, causing all points to evaluate to `undefined` Y-values.
  3. **Time Range Filter Disconnect**: Backend ignored incoming query parameters (`start`, `end`, `from`, `to`) and only queried a default 1-hour window around the initial anomaly record, returning fewer or misaligned buckets for user-selected ranges.
- **Remediation**:
  1. **Backend (`backend/app/api/anomalies.py`)**:
     - Added query parameters `from`, `to`, `start`, `end` to `GET /api/v1/anomalies/{anomaly_id}` using `_parse_time_ms`.
     - Enriched each series point with:
       - `timestamp_ms`: Canonical millisecond epoch (`bucket_start * 1000`).
       - `rps` & `tps`: Normalized throughput (`requests / 60.0`).
       - `actual`: Metric-type aligned value (latency p95 for latency anomalies, error rate % for error anomalies, rps/tps for volume anomalies).
       - `expected`: Baseline value (`item.baseline_value` or 0.0).
  2. **Frontend (`frontend/src/pages/Anomalies.tsx`)**:
     - Hooked `useFilters()` into `AnomalyDetailPage` and appended `?${queryString(filters)}` to the query URL.
     - Added robust normalization map across `chartData`:
       - Automatically converts seconds to milliseconds if timestamp $< 10^{10}$.
       - Derives fallback `rps`, `p95_ms`, `http_5xx_rate`, `actual`, and `expected` baseline.
       - Configured `metric` to accurately track `"p95_ms"`, `"http_5xx_rate"`, or `"rps"`.
- **Verification**:
  - `curl -s "http://127.0.0.1:30102/api/v1/anomalies/6130971176347858?start=1789687202539..."` returns 35 series points with full `timestamp_ms`, `rps`, `actual`, and `expected`.
  - Frontend built cleanly without warnings (`tsc -b && vite build`).
  - Pytest API and analytics tests passed (16/16 passed).
- Port 30102 live and verified.

### Interactive Service Topology (implemented 2026-09-18)
- Added migration `backend/clickhouse_migrations/008_interactive_topology.sql` with bounded five-minute service, API, principal, principal/IP, and current topology tables. The migration also persists normalized source-IP/attribution and request/response byte fields on sanitized trace rows.
- The analytics worker materializes only the bounded event-time slice in ClickHouse mode. Elasticsearch/ELK mode uses the interactive topology repository's server-side composite/runtime aggregations and does not write application traces into ClickHouse for topology reads.
- Added interactive topology contracts under `/api/v1/topology/services`, service API expansion, API principal expansion, service/API/principal metrics, and cursor-paginated principal IPs. Responses include direct/inferred evidence, confidence, operational metrics, anonymous attribution, and previous-window change indicators.
- Added the React `Service Topology` route at `/topology`: service-only initial graph, explicit lazy branch expansion, stable parent-relative positioning, separate node/edge inspection, and paginated principal IP context in the side panel.
- Task verification: focused topology tests **5/5**, existing analytics/API/LB/user-IP slice **43/43**, frontend `npm run lint`, and frontend `npm run build` passed. A build-size advisory remains from the pre-existing single-bundle frontend shape.

### Full-Canvas Topology Interaction Redesign (2026-09-18)
- `/topology` is an edge-to-edge route canvas with floating time, graph legend, change, and attribution controls.
- The object detail window is absent by default and floats on the right only after node/edge selection.
- Navigation: wheel or `+`/`-` zoom (50%-250%), drag blank canvas to pan, click the percentage or double-click blank canvas to reset.
- Service, API, and principal node statistics are vertically stacked inside each graph card.
- Node cards are independently draggable without coordinate boundaries; edges follow their new positions, and the grid remains visible throughout extended panning.
- Node inspectors render a TPS time-series chart from ClickHouse or Elasticsearch detail buckets.
- TPS detail charts render a smooth curve over fixed five-minute buckets regardless of the selected observation-window length.
- Topology time selection is now a seven-day slider with 2,016 five-minute steps; range preset buttons are no longer used on the topology page.
- Sidebar transitions leaving `/topology` use a full route load, eliminating the stale-canvas state where the URL changed but React Router continued rendering topology; verified with the inspector open.
- Canvas z-indexes are isolated below the fixed sidebar, preserving navigation to all other routes while the graph or inspector is active.
- Vietnamese canvas labels and accessibility names are included.
- Verified with frontend lint/build, HTTP 200 route/API checks, and **18/18** Playwright pages. The topology browser assertion covers zoom/reset, inspector open timing, and sidebar navigation from `/topology` to `/services`.
## Topology API connection focus (2026-09-18)

- The full-page topology canvas shows service-to-service relationships by default.
- Clicking an expanded API card queries and overlays its exact observed caller-service connections for the selected five-minute window.
- Contextual API wires disappear when the API is no longer selected; no service-wide relationship is inferred as API-specific.
- Endpoint: `GET /api/v1/topology/services/{service}/api-connections?api=<api>&window=5m` (also accepts bounded `from`/`to`).

## Topology fast-travel search (2026-09-18)

- The topology title panel includes a type-ahead search for services, APIs, and users.
- Search covers the full seven-day slider horizon through `GET /api/v1/topology/search?q=...&window=7d`.
- Selecting a result jumps to its latest observed five-minute slice, expands the required service/API path, centers the result card, and opens its floating detail inspector.
- Selected cards use the highest node z-layer, and selected relationship wires are rendered last within the SVG relationship layer.

## Canonical Service/API/User/IP paths (2026-09-19)

- The operational hierarchy is now explicitly `Service -> API -> User -> IP`, with the symmetric identity investigation path `User -> Service -> API -> IP`; there is no System entity layer.
- Added principal-first topology APIs:
  - `GET /api/v1/topology/principals/{principal}/services`
  - `GET /api/v1/topology/principals/{principal}/services/{service}/apis`
  - Existing `GET /api/v1/topology/principals/{principal}/ips?service=...&api=...` supplies the final IP evidence step.
- The User topology page now uses an IP-first progressive drilldown: `IP → User → Service → API`. The selected IP reveals the User, then scoped Service and API lists, followed by the exact relationship details and operational metrics.
- No duplicate `user_service`/`service_user` tables were added. Both directions query the existing `topology_principal_edges_5m` and `topology_principal_ip_5m` rollups.
- The sidebar taxonomy no longer labels the primary group as a System level; it is presented as Operational Views.
- Focused topology repository/API contract tests pass **5/5**, and frontend TypeScript validation passes.

## Persistent light theme (2026-09-19)

- Added a global light/dark toggle to the header. Dark remains the default for existing installations.
- Preference persists in browser `localStorage` as `tracescope-theme`; switching updates the document theme, browser color-scheme, and theme-color metadata.
- Existing pages inherit a light palette through root CSS remapping, including surfaces, typography, controls, borders, tables, scrollbars, and chart grid/axis styling.

## Operational dashboard refresh (2026-09-19)

- Rebuilt `/` and `/dashboard` as a four-card operational dashboard: Total TPS, Total Users, Total Services plus unhealthy count, and Abnormal Changes.
- Added three chart regions: five-minute TPS line, five-minute HTTP 5xx percentage line, and horizontal stacked abnormal-score groups.
- Bandwidth is a visible placeholder because the existing `/api/v1/dashboard/series` payload has no byte fields. Backend/API changes were intentionally skipped per request.
- Removed global 1h/3h/6h/24h/7d/30d selectors; the frontend defaults to a seven-day window represented in five-minute buckets. Anomaly detail and user topology selectors were fixed to the same seven-day view.

## Service detail chart fix (2026-09-19)

- Fixed `/services/:name` trend charts, including `/services/apex-edge-gateway`, by adapting the existing rollup response fields (`bucket_start`, `requests`, `errors`, `latency_p95`) to the frontend chart series fields.
- Added numeric timestamp handling, TPS/error fallbacks, and a visible empty-window state. No backend/API changes were required.
- Frontend production build passed after the fix.

## Separate service trend charts (2026-09-19)

- `/services/:name` now shows two independent line charts: service TPS and p95 latency. Independent charts prevent the latency scale from flattening the TPS signal.
- The existing normalized series and API contract remain unchanged; this is a frontend-only presentation change.
- Frontend lint and production build passed.

## Card row layout (2026-09-19)

- Standardized larger panel/card grids across frontend pages to display at most two cards per row, with additional cards wrapping below.
- Compact KPI/info cards use four cards per desktop row, including the dashboard's Total TPS card and its three companion cards.
- Updated service inventory, unknown-user attribution, topology IP cards, user intelligence summaries, agent stats, traces, anomalies, and user workspace metric ribbons; functional topology/table layouts remain intact.
- Frontend lint and production build passed.

## Monitoring UI Refactor (2026-09-19)

- The primary `/` route now redirects to `/dashboard`; sidebar navigation is organized as Dashboard, Services, Users, Topology, Changes, Traces, and Agent Fleet. The legacy `/unknown-users` route remains available but is no longer a primary navigation item.
- The default dashboard is organized around status and change investigation: KPI summary, important changes, five-minute TPS/error/p95 trends over seven-day history, service/user hotspots, and secondary abnormal-score distribution. The unavailable bandwidth series was not fabricated and no backend/API contract was changed.
- Services use an operational table and service detail surfaces prioritized operations. A subordinate API drilldown route (`/services/:service/apis/:api`) reuses existing topology metrics, principal, and caller APIs and keeps the Service → API → User path intact.
- User workspace headers and tabs are compacted; important changes and new relationships are surfaced before detailed charts. Topology node cards and history controls are less dense while preserving lazy expansion and the inspector.
- The grouped anomaly view now leads with eight operational columns (severity, what changed, identity, service/API, current vs baseline, since/duration, status, actions), while raw findings and expandable incident slices remain available.
- Visible terminology uses “Unattributed Traffic” / “Identity Attribution” for unknown identity observations without changing backend semantics; explicit 401/403 authentication failures remain distinct.
- Changes are frontend-only. Validation completed with `npm run lint`, `npm run build`, and `git diff --check`; unrelated backend, test, and report files remain unstaged.

## Service/API/User Bandwidth Backend (2026-09-19)

- Service, API, and principal topology metrics now expose cumulative `request_bytes`, `response_bytes`, and `total_bytes`, plus explicit rates: `request_bytes_per_second`, `response_bytes_per_second`, `bandwidth_bytes_per_second`, and `bandwidth_bits_per_second`.
- Five-minute transaction series expose the same bandwidth fields for line-chart use. Both ClickHouse and Elasticsearch worker paths write and read these fields through `metric_buckets`.
- `GET /api/v1/services/{service}/bandwidth` provides a dedicated service bandwidth response with window totals and five-minute series. Existing service detail health includes the bandwidth totals/rates and a nested `bandwidth` payload.
- `GET /api/v1/users/{principal}/performance` now includes bandwidth fields per bucket, a top-level bandwidth summary, current/baseline five-minute bandwidth KPIs, and `bandwidth_pct` delta. API drilldowns receive the same fields through the existing topology API metrics response.
- Units are explicit: byte totals are bytes, `*_bytes_per_second` values are bytes/second, and `bandwidth_bits_per_second` is bits/second. Missing byte telemetry remains zero and is never inferred from request counts.
- Verification: focused interactive topology/bandwidth tests passed **5/5**; API and behavioral regressions passed **19/19**; Python compilation and `git diff --check` passed.

## Anomaly detail ID namespace fix (2026-09-22)

- Root cause of `/anomalies/6739330567467241` returning `Anomaly not found`: the ID is a `principal_change_events` record (`CALLER_PRINCIPAL_SWITCH` for `partner_sales_broker`), not an `anomaly_events` record.
- Added `GET /api/v1/user-changes/{change_id}` and `UserRepository.get_change()` for exact behavioral-change lookup.
- Overview change cards now open `/changes/chg-<id>`; legacy direct anomaly links fall back to the same Change detail after resolving the change ID.
- Frontend type-check/build, backend Python compilation, and `git diff --check` passed. The public API was checked read-only: health is `200`, the supplied anomaly URL is `404`, and a current anomaly detail URL returns `200`.

## Changes episode adapter and UI (2026-09-22)

- Added `backend/app/api/changes.py`, a compatibility adapter that combines existing service anomaly rows and principal behavioral-change rows into operator-facing episodes without changing detector storage or algorithms.
- New API routes: `GET /api/v1/changes` and `GET /api/v1/changes/{episode_id}`. Episode IDs preserve source identity with `chg-<principal_change_events.id>` and `anm-<anomaly_events.id>`.
- Episode presentation is intentionally simplified to `subject`, `summary`, `state`, `status`, metric/categorical `highlights`, relationship `context`, evidence, and timeline. Detector scores and baseline mechanics remain in the detail debug/evidence surface.
- Added `frontend/src/pages/Changes.tsx` with the `/changes` list/detail routes, Now/Earlier episode grouping, Users/Services filters, state filter, search, evidence panel, timeline, relationship path, and links into User/Service/Trace views.
- `/anomalies` now redirects to `/changes` as the compatibility entrypoint; `/anomalies/:id` remains for old anomaly URLs.
- The primary User workspace now exposes three views: Overview, combined Activity (performance + patterns + IP-first topology), and Changes. Former `topology`, `patterns`, and `investigations` URLs remain compatibility redirects; the UserLayout TPS graph still renders before the selected view.
- Verification completed: frontend lint/build, backend compilation, `git diff --check`, isolated FastAPI Changes endpoint smoke test, and application OpenAPI route registration. Storage-backed API tests were not runnable because local ClickHouse `127.0.0.1:8123` refused connections.

## Public Changes deployment and browser verification (2026-09-22)

- Installed Playwright `1.63.0` and Chromium in `.venv`.
- Restarted the active `tracescope-30102` and `tracescope-worker` sessions so the `/api/v1/changes` router and built frontend are live on port `30102`.
- Public checks now pass: `/api/v1/changes` returns HTTP 200 with grouped episodes, `/changes` renders HTTP 200, and `/changes/anm-1886229056538689` renders HTTP 200 with zero Chromium console/page errors.
- The previously failing behavioral ID is now available through `/api/v1/changes/chg-6739330567467241` with HTTP 200 and subject `partner_sales_broker`.

## Episode-based User Changes and Investigations redesign (2026-09-22)

- Replaced the former detector-family `UserChangesTab` with an operator-facing episode workflow driven by `GET /api/v1/changes?principal=<name>`. The page now presents Changes, Need attention, and Last change summary metrics; Current behavior; All/Needs attention/Reviewed filters; operational Access/Traffic/Performance/Errors/Authentication/Network type filters; human-readable episode cards; and a dedicated `/users/:principal/changes/:episodeId` detail route.
- Added shared `frontend/src/components/EpisodePrimitives.tsx` components for episode status, readable title, relationship path, metric diff table, timeline, evidence, baseline context, source finding reference, and episode cards. Detector names are secondary technical evidence instead of primary card titles.
- Reintroduced `/users/:principal/investigations` as a real four-tab workspace view rather than a redirect. It uses the same episode objects and provides an Open/Monitoring/Resolved queue, Summary, Evidence, Traces, AI analysis, History, and explicit Expected behavior / Keep monitoring / Resolve decisions. Removed the previous invented fallback topology chain.
- The AI analysis entry point is now visible on the investigation workspace and opens the existing source-versioned `InvestigationPanel` using the episode's `anomaly_event` or `principal_change_event` reference. The active deployment currently has `OTEL_LLM_INVESTIGATION_ENABLED=false`, so investigation API calls intentionally report the disabled state until an LLM provider is configured.
- Playwright 1.63.0 Chromium checks passed with zero browser errors for `/users/telecom_sync_svc/changes`, `/users/telecom_sync_svc/investigations` including opening the AI panel, and `/users/fefsf/changes/chg-5427563056243275`. Frontend `npm run lint` and `npm run build` passed; active port `30102` was restarted with the new built output.

## Unified Change and Abnormality evaluation (2026-09-22)

- `Change` is now the observed fact and `abnormality` is a separate deterministic episode evaluation. The API returns `EXPECTED`, `CHANGED`, `NEEDS ATTENTION`, or `CRITICAL` plus `is_abnormal`, evidence domains, correlation status, infrastructure-only attribution, reasons, and evaluator version.
- Known/low-confidence F5, load-balancer, reverse-proxy, NAT, or ingress source-IP-only episodes remain `CHANGED` even if a source detector assigned high severity. Correlated access, Traffic, Performance, Error, or Authentication evidence can promote an episode; detector score remains secondary evidence.
- `GET /api/v1/changes/{id}` now reconstructs the related 15-minute episode around a source signal and accepts legacy unprefixed numeric IDs. Both `/anomalies` and `/anomalies/:id` redirect to the unified Changes UI.
- Dashboard, global Changes, User Changes, User header state, and User Investigations consume the same episode contract. Score-bucket UI was removed. Global detail shows the abnormality rationale and the LLM investigation panel; the investigation queue defaults to promoted/reviewed episodes rather than every informational change.
- Operator decisions distinguish `Expected behavior` from `Resolve`: expected principal behavior is added to the scoped baseline; resolved behavior closes workflow without teaching it as expected. Anomaly expected actions use suppression, while resolved remains resolved.
- Added focused evaluator tests covering expected review, known load-balancer IP, correlated access/rate changes, and critical error correlation.
- Validation: focused evaluator plus behavioral API tests passed **20/20**; frontend TypeScript lint and production build passed; live API and Chromium checks passed for Dashboard, Changes, Change detail with LLM panel, User Changes, User Investigations with AI panel, `/anomalies` compatibility redirect, and legacy numeric change-ID redirect. The full backend suite reached **196 passed / 1 failed**; the only failure was the pre-existing infrastructure retention test because ClickHouse rejected a `system.metric_log` TTL mutation at its 3.60 GiB memory ceiling (`MEMORY_LIMIT_EXCEEDED`), unrelated to Change evaluation logic.

## User Overview TPS and Bandwidth layout (2026-09-22)

- Final arrangement: first operational row is TPS vs Baseline plus the 2×2 KPI grid; unified Change episodes follow, then paired Error/Latency charts, Bandwidth history, and a source-IP evidence table. Removed decorative intent banners, unused hidden markup, and the legacy score chart. Missing KPI values render as unavailable; Bandwidth automatically uses B/s, KiB/s, or MiB/s.

- `/users/:principal/overview` omits the shared standalone TPS panel and places the `TPS vs Baseline` chart on the left of the first Overview content row. Other User workspace routes retain the single scoped TPS panel.
- The Overview 2×2 KPI grid now contains `Requests`, `Bandwidth`, `Error Rate`, and `P95 Latency`; the former TPS KPI was replaced with `bandwidth_bytes_per_second` formatted as MiB/s and compared using `bandwidth_pct`.
- Added browser assertions for the two-column TPS-vs-Baseline/KPI row and one Bandwidth KPI. Frontend lint/build passed and the deployed Playwright check for `/users/telecom_sync_svc/overview` passed with zero JavaScript errors.

## Changes usability and workflow consistency (2026-09-22)

- Global Changes and User Changes now share the same `Needs attention`, `All`, and `Reviewed` predicates. Attention excludes resolved episodes; Reviewed means explicitly expected behavior or a resolved workflow.
- Removed the User Changes “Current behavior” hero, which previously treated the newest unresolved result as the most important/current event and could imply normal behavior before query completion.
- Episode cards now separate evaluation state from workflow state, use “Last observed” instead of inferring ongoing activity, render one relationship path, show only two primary comparisons, and treat missing values as unavailable rather than `NEW`.
- Delta color is neutral because a positive or negative change is not universally good or bad. Evidence markers no longer imply confirmation strength that the API does not provide.
- Global and User detail pages preserve time/filter context, use the selected dashboard timezone, expose the same review controls, and identify that decisions currently apply to the episode's representative source finding.
- The User “Investigate with AI” action opens the AI tab directly. Investigation search uses operator-visible fields instead of serialized internal JSON, and unavailable source findings render an explicit AI empty state.
- Only explicit principal-change acceptance is classified as expected behavior. Suppressed/ignored findings remain workflow outcomes and are not taught as behavioral truth.
- Offline verification completed while the live API was unavailable for a data update: focused Change evaluator tests passed **5/5**, frontend TypeScript lint passed, and the production frontend build passed. Live API and browser verification were intentionally deferred.
- Global `/changes` episode cards now expose the same `Investigate` action as User Changes. It opens `/changes/:id#ai-investigation`, and the detail page scrolls to the LLM panel after asynchronous episode loading. A persistent `Investigate with AI` header action provides the same shortcut from the detail page. Frontend lint and production build passed; live verification remains deferred during the data update.

## User Investigation consolidation (2026-09-22)

- Removed the separate User Investigations navigation tab and deleted its queue/tab workspace. It duplicated the selected Change episode across Summary, Evidence, Traces, AI analysis, and History tabs and introduced a second mental model for the same workflow.
- User Change Detail is now the single investigation page. It presents What changed, evaluation reasons, Before vs now, Timeline, Evidence, related Traces, inline LLM investigation, and operator decisions as one vertical operational flow.
- User Change cards and the detail header both expose `Investigate`; they open or scroll directly to `#ai-investigation`. The LLM panel remains visible when disabled and reports its availability state rather than disappearing.
- `/users/:principal/investigations` remains as a compatibility redirect. With `episode_id`, it redirects to the corresponding User Change detail and AI section; without an episode it redirects to User Changes.
- Updated the Playwright route contract to verify the compatibility redirect and the inline LLM panel on User Change detail. Frontend lint and production build passed; live browser/API checks remain deferred while the API data update is in progress.

## Entity identity colors (2026-09-22)

- Added stable entity accents to relationship UI: User lavender (`#b877d9`), Service blue (`#5794f2`), API teal (`#56b9a8`), and IP neutral gray (`#a7a9ab`).
- Episode relationship paths now render typed tokens instead of one generic gray token. User topology columns and relationship detail use the same mapping, while IP remains supporting neutral context.
- Interactive topology nodes and search results now color the node icon/name and add a typed entity label. Operational state colors remain independent for new/changed/error conditions.
- Frontend lint and production build passed; live browser/API checks were not run because the API data update is still in progress.
- Relationship paths now include explicit role labels above every value. Full detail paths explain that the relationship is logical telemetry and that related Trace evidence is required to confirm exact request causality.
- User topology now names the Service column as Target Service, with source IP retained as supporting metadata.

## Service-first credential relationship semantics (2026-09-22)

- Corrected the relationship model so non-human principals are not portrayed as people actively calling a Service. The primary operational path is now `Caller Service → Target Service → API / Operation`.
- An observed service/system/shared/integration principal is rendered separately as `Credential observed on this call`, visually attached to the service call rather than inserted as the first causal node.
- Confirmed `principal_type=human` identities retain User wording and the User icon. Unknown identities use `Observed Principal`; non-human identities use `Observed Credential` and a key icon throughout the User workspace header and topology.
- User topology keeps the already-selected principal visible before any IP selection. Selecting an IP only scopes where that principal was observed; it does not replace the principal as the workspace subject.
- Topology observed-path rows now lead with `Caller Service → Target Service → API` and show `Credential: <principal> · IP: <address>` as supporting context. Relationship detail follows the same semantic order.
- Episode cards and detail paths use the same service-first visualization and state explicitly that related Trace evidence is required to prove exact request causality or credential forwarding.
- Frontend TypeScript lint and production build passed. Live API and browser verification remain deferred while the data update is in progress.

## User Activity workspace redesign (2026-09-22)

- Replaced the long stacked Activity workspace with an internal `Performance | Normal Pattern | Access` segmented control. No router-level tabs or routes were added; `/topology` and `/patterns` remain compatibility redirects to Activity.
- Performance is the default segment and preserves TPS-first behavior without the duplicate parent TPS panel. TPS vs Baseline sits beside a current 2×2 TPS/Error/P95/Bandwidth summary, followed by paired Error Rate/HTTP Status charts and a full-width p50/p95/p99 chart.
- Normal Pattern contains only historical/baseline evidence: the real 24×7 active-hour heatmap, baseline-vs-current footprint, normal Target Services, normal APIs, established Caller Services, and known Source IPs. No synthetic activity is generated when history is absent.
- Access now uses a progressive four-column board: `Selected IP → User/Credential → Service → API`. The route-selected identity is always visible before an IP is selected. Choosing an IP reveals its observed Target Services; choosing a Service reveals APIs.
- The selected Access relationship shows TPS, Requests, Error rate, P95, Bandwidth, first/last seen, and a separate Caller Service table. This avoids presenting a non-human credential as the network caller while preserving the requested IP/User/Service/API exploration path.
- Related Trace and API links are available from the selected relationship. Copy states that Caller Service is observed telemetry and that Trace evidence is required to confirm the exact request chain or credential propagation.
- HTTP status retains count/percentage switching. Missing byte telemetry displays Bandwidth as unavailable rather than a synthetic zero.
- Frontend TypeScript lint and production build passed. Live API and browser verification remain deferred while the API data update is in progress.

## Grafana-style Activity Performance refinement (2026-09-22)

- Reworked the default Performance segment into a compact observability layout: four Stat panels with mini sparklines for TPS, Error rate, P95 latency, and Bandwidth; the largest panel is observed TPS versus Baseline with an optional normal range, selected bucket, and change markers.
- Replaced the former status-code-heavy visualization with a default 100% stacked status chart grouped into 2xx, 3xx, 4xx, 5xx, and timeout classes. Count/percentage switching remains available, and selecting a bucket reveals class percentages, counts, and top status codes.
- Added paired percentile latency (p50/p95/p99) and Request/Response bandwidth area charts. Missing byte telemetry stays explicitly unavailable instead of being presented as a fabricated zero.
- Updated `user_repository.performance()` to return 3xx counts and to keep 4xx, 5xx, and timeout classes mutually exclusive for the grouped status chart; overall error-rate semantics remain unchanged.
- Validation passed: frontend TypeScript lint, Vite production build, and Python syntax compilation for `user_repository.py`. Live API/browser verification remains deferred while the data update is in progress.

## User Overview consolidation (2026-09-22)

- Removed Overview from the active User workspace navigation. The workspace now has two operator-facing tabs: `Activity` and `Changes`.
- `/users/:principal` now opens Activity directly. `/users/:principal/overview` remains a compatibility redirect to Activity so saved links continue to work.
- Global search, User Directory rows, Dashboard user links, Service user tables, API user tables, and Change actions now link directly to `/users/:principal/activity` instead of passing through the compatibility redirect.
- The persistent identity header retains the compact identity type, status, baseline state, behavior state, request count, target/caller/API/IP counts, and active window that previously justified a separate summary page.
- Updated the Playwright route contract to verify the Overview compatibility redirect and the Activity segmented control rather than the removed Overview card layout.
- The modified `UserOverviewTab.tsx` file remains in the repository as inactive legacy source because the working tree already contained unrelated edits to it; no active route imports or renders it.

## Dense Dashboard & User Activity Layout Refactor (2026-09-22)

- **Dashboard (`Overview.tsx`) Density**:
  - Expanded first KPI row from 5 to 6 compact metric cards: **TPS | Error rate | P95 latency | Active users | Services | Needs attention** (`abnormalCount` from change episodes).
  - Consolidated Row 2: Total TPS chart beside consolidated **Important changes** panel with inline filter badges for `Critical`, `Attention`, and `Changed` counts and top 5 recent episodes.
  - Eliminated redundant separate bottom `Recent Changes` and `Change evaluation` panels completely.
  - Retained Row 3 for Top Services and Top Users tables with direct links into drill-down pages.
- **User Workspace Header (`UserLayout.tsx`) Compression**:
  - Compressed the former multi-tier header (breadcrumbs, large identity card, 6-box ribbon, and tabs) into a dense 2-row Grafana-style banner.
  - Saves 100–150px of vertical height above the fold before the first chart.
  - Row 1: Back link to Users, principal name in bold monospace, principal type dropdown, environment tag, status badges (Active, Baseline status, Behavior state with score), and quick `Switch ▾` account dropdown.
  - Row 2: Single-line inline metrics ribbon (`Requests`, `Services`, `APIs`, `Callers`, `IPs`, `Window`) paired with embedded `Activity` and `Changes` navigation tabs.
- **User Activity Workspace (`UserActivityWorkspace.tsx`) Density**:
  - **Performance View**:
    - Enriched 4 KPI StatCards with secondary operational telemetry: TPS (observed + baseline delta, `avg · peak`), Error rate (observed + baseline pp delta, `5xx · timeout`), P95 (`p50 · p99`), Bandwidth (`req · resp` breakdown).
    - Compact StatCard height (75–80px).
    - Compressed main TPS vs baseline chart height from `340px` to `230px`.
    - Compressed secondary charts (Error rate & HTTP status) from `224px` to `185px`.
    - Compacted HTTP status bucket drilldown into a single-line horizontal strip (`14:32 | 2xx 94.2%  4xx 3.4%  5xx 2.1%  timeout .3%`) instead of 5 column boxes.
    - Compressed Latency and Bandwidth charts from `240px` to `195px`.
    - Eliminated dead `{false && activeView === "performance" && ...}` block and unused states.
  - **Normal Pattern View**:
    - Packed Active-hour heatmap and Baseline-vs-current footprint side-by-side on wide displays (`xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]`), saving an entire full-width row above the 4 distribution lists.
  - **Access View**:
    - Streamlined to 3 columns: `Selected IP (25%) → Service (35%) → API (40%)`.
    - Removed redundant static User/Credential column since the identity is already established and prominent in the panel title (`Access for {principal}`).
- **Legacy Cleanup**:
  - Cleaned up unreferenced legacy tab files: `UserActivityTab.tsx`, `UserPatternsTab.tsx`, `UserTopologyTab.tsx`, `UserOverviewTab.tsx`.
- **Validation**:
  - Production Vite build and TypeScript compilation succeeded without errors (`dist/index.html`, `dist/assets/index-BZrMY-LF.css`, `dist/assets/index-5ljkTHYt.js`).

## User Activity horizontal density redesign (2026-09-22)

- Reduced the Activity internal navigation to `Behavior | Access`. Behavior now combines current telemetry, baseline context, and normal-pattern evidence without restoring the legacy standalone pages or changing the User workspace’s separate `Activity | Changes` navigation.
- Reorganized Behavior into paired desktop panels: TPS vs Baseline beside the real active-hour heatmap; Error Rate beside HTTP Status; p50/p95/p99 Latency beside Request/Response Bandwidth; and Baseline vs Current beside a compact Normal Footprint selector for Services, APIs, Callers, and Source IPs.
- Preserved existing chart heights, data/query semantics, status percentage/count interaction, missing-profile empty state, and measured-only baseline data. No stability score, privilege heuristic, or synthetic heatmap fallback was introduced.
- Access remains separate and uses the compact `Source IP → Service → API` board while keeping the selected principal visible in the Access context. Changes remains a separate User workspace tab.
- Updated `backend/scripts/test_pages_playwright.py` to verify the two Activity modes, Behavior-first rendering, required paired panels, and Access board presence. Live browser execution remains deferred while the API data update is unavailable.

## Shared dashboard sparkline readability (2026-09-22)

- Replaced the dashboard’s dense custom SVG sparklines with the same fixed-height Recharts line treatment used by User Activity StatCards.
- Shared sparklines now normalize invalid values, cap long histories to 48 representative points, disable animation, and keep a simple line-only presentation so narrow KPI cards remain readable.
- User Activity StatCards now consume the shared `Sparkline` component, keeping dashboard and user-level KPI visual behavior consistent.

## User Activity KPI overlay and panel layout (2026-09-23)

- Behavior keeps TPS and its baseline visible in the main chart. Clicking an Error rate, P95 latency, or Bandwidth KPI card overlays the selected metric lines on a labeled right axis; clicking TPS returns to the default view. The four cards retain compact sparklines. Chart animations are disabled for immediate switching.
- The 100% HTTP status chart occupies the panel beside the main chart on wide screens. The responsive 24-hour active-hour heatmap is below that row. Baseline-vs-current and Normal Footprint panels and their unused display code were removed.
- Hovering either chart updates the selected time bucket's metrics and HTTP status percentages/counts. The frontend production build passed. A Chromium render with mocked telemetry at 1440×900 showed 2 TPS lines by default, 4 lines with Error rate, 5 with Latency, and 4 with Bandwidth; the main and status panels were both 357px tall. At 390px width there was no horizontal overflow, and no page errors occurred.
- Follow-up: the main chart now uses a typed variable configuration (series, colors, formatter, availability, and scale) so another KPI can be added without branching its chart rendering. A 78px right-axis slot and fixed-height legend remain mounted for every selection; right-side labels show TPS by default or when bandwidth bytes are unavailable, and switch units with the selected overlay. The extra byte-measurement warning was removed. The TPS axis is exactly 0 to the peak of observed/baseline TPS, without 10% headroom.
- A Chromium check using 48 mocked buckets, both with and without byte telemetry, confirmed the plot box and TPS SVG path are identical across all four KPI selections, the right-side values remain visible, all selected lines render when available, and no page errors occur. The frontend production build passed.
- Fractional-TPS correction: removed the 1 TPS minimum from the primary axis when traffic is positive. The axis maximum is the exact observed/baseline peak, and tick formatting gains decimal precision as peaks shrink; the 1 TPS fallback applies only to all-zero series. Browser checks with 0.1, 0.02, 0, and 31 TPS peaks confirmed matching top-axis labels and that positive peak lines reach the top gridline, with no page errors. The frontend production build passed.
- The shared TPS chart used in the service catalog and service detail now styles its latest-value label with the same font, size, and muted gray as the left-axis labels.

## Service Detail interactive performance chart (2026-09-23)

- Service Detail reuses the User Activity interactive KPI card component, with TPS, Requests, Error rate, P95 latency, and Bandwidth cards above the main chart.
- The chart keeps observed TPS (and a baseline when the API supplies it) visible. A typed metric configuration maps Requests/minute, Error rate, P95 latency, and measured bandwidth series to the right axis; missing bandwidth series falls back to the TPS scale.
- The service and user workspaces now share the same selected card treatment. Service bandwidth continues to use its reported five-minute buckets; the chart joins those by timestamp without fabricating per-minute byte values.
- TypeScript and the frontend production build passed after this update.

## Dashboard Important Changes scroll area (2026-09-23)

- Increased the dashboard-only Total TPS chart from `h-44` to `h-60` and expanded the Important Changes list by the same 64px (284px on smaller screens, 196px at desktop widths) to keep the two panels aligned. Other uses of the shared TPS chart retain their existing height.
- Replaced the dashboard Needs attention KPI with Bandwidth in the third position. `GET /api/v1/topology/bandwidth` uses byte-aware ClickHouse topology rollups or Elasticsearch aggregations and honors the dashboard's service, operation, account, and time filters. The card formats current, average, and peak rates as B/s, KiB/s, or MiB/s and shows an em dash if the request fails.
- The Important Changes list remains keyboard-focusable and scrollable, showing all six ranked changes. The frontend production build and focused byte-rollup/API-surface tests passed.

## Worker metric-bucket bandwidth (2026-09-23)

- The existing Elasticsearch metrics stage writes grouped transaction counts, latency summaries, byte totals, and byte sample counts into `metric_buckets` at both 60-second and 300-second grain. It uses the existing `worker_elasticsearch_sync` checkpoint; in agent-only mode it does not copy application traces into ClickHouse.
- Adding byte columns triggers a one-time rebackfill of the retained Elasticsearch window, even when earlier metric checkpoints were already marked live. No separate bandwidth worker, index, or checkpoint remains.
- `/api/v1/topology/bandwidth`, Overview, Service, API, and User Activity bandwidth values all read from `metric_buckets`. Missing byte fields remain unavailable and are not inferred from request counts.

## TPS chart render density (2026-09-23)

- Added render-only min/max sampling for TPS charts. The shared TPS chart and User Activity TPS vs Baseline keep up to 450 representative source points; per-group minima/maxima and the first/last points are selected, preserving observed spikes without averaging.
- The underlying five-minute series remains unchanged for calculations and other UI logic. Hover payloads map sampled chart points back to their original source indices. Line interpolation is linear and animation is disabled.

## Thin time-series lines (2026-09-23)

- All Recharts line and area curves, plus the custom topology-inspector TPS curve, use the shared `--chart-line-width: 1.25px` CSS token to reveal narrow spikes more clearly. Connection edges, grids, and hover dots are unaffected.

## User Activity missing TPS line (2026-09-23)

- Root cause on `/users/billing_reconcile_job/activity`: the performance response included historical anomaly rows with zero requests and rounded its lone surviving one-request bucket to `0.0` RPS. The separate Elasticsearch bandwidth rollup had 1,250 five-minute buckets and 63,152 measured requests, but the frontend previously discarded those buckets whenever any performance row existed.
- User Activity now computes exact TPS from worker metric-bucket request counts and shows enough decimal places for sparse nonzero TPS. Its current latency values also come from those buckets.
- The frontend production build passed. Chromium loaded the public page with HTTP 200, rendered a main TPS path with 382 line segments, showed `0.0033` TPS for the latest sparse bucket, and reported zero page errors. No backend restart was required because FastAPI serves the rebuilt `frontend/dist` assets.

## User Activity TPS rollup correction (2026-09-23)

- The worker computes `metric_buckets` from its configured telemetry source. User Activity queries `/api/v1/principals/{principal}/metrics?bucket=300` for transaction counts, latency, and measured bytes. Five-minute buckets are grouped into one-hour points for windows longer than eight days.
- On the public `billing_reconcile_job` page, the principal metrics API returned 1,741 five-minute buckets totaling 119,605 requests over the selected seven days. The rebuilt frontend passed TypeScript/Vite build; Chromium confirmed HTTP 200 from the metrics API, a main TPS path with 428 segments, and zero page errors.

## Line-chart worker-rollup source audit (2026-09-23)

- User Activity takes TPS, error rate, p50/p95/p99 latency, bandwidth, card sparklines, heatmap, and request outcomes from worker `metric_buckets`. The TPS baseline comes from worker baseline rollups through `/api/v1/dashboard/series`. The Changes tab header TPS also reads principal metric buckets. No User Activity request uses the raw-trace performance API.
- API/topology detail series and bandwidth values come strictly from `metric_buckets` in both storage modes. The separate Elasticsearch bandwidth index and its reader were removed. User Activity no longer makes a second bandwidth request or falls back to another store for TPS or bytes.
- Unknown Users' area chart reads anonymous `metric_buckets`; because those buckets contain request/error counts but no status classes, its plotted categories are accurately labeled non-error and failed requests. The page's other summaries and trace evidence remain trace-backed.
- Agent Fleet time series stays on dedicated `agent_stats_history`; transaction bandwidth lines use worker `metric_buckets`.
- The User workspace header profile reads `/api/v1/users/{principal}` from derived principal summary and relationship tables; activity charts remain backed by worker `metric_buckets`. This avoids treating an empty selected-window metric series as a missing principal. The HTTP status chart is labeled non-error/failed-request because exact status classes are absent from `metric_buckets`. Access reads worker principal-IP rollups, including in Elasticsearch mode, and can be empty if those rollups have not been materialized.
- Verification: focused topology/bandwidth tests passed 10/10, frontend TypeScript/Vite build passed, and live health, principal metrics, topology principal metrics, and Unknown Users APIs returned HTTP 200 after the dashboard/worker restart on port 30102.

## No raw trace reads in User Activity (2026-09-23)

- User Activity no longer requests `/api/v1/users/{principal}/performance`; its activity header data, heatmap, and non-error/failed request outcome chart use worker `metric_buckets`. The shared User workspace header reads the identity profile from `/api/v1/users/{principal}`, which uses derived principal summaries. The quick switcher uses the principal inventory endpoint. The Access view reads worker `topology_principal_ip_5m` rollups, including in Elasticsearch mode, and shows no relationships if those rollups are absent.
- `PrincipalRepository` no longer falls back to `traces` when metric buckets are empty. Missing worker aggregates result in an empty chart or 404 profile instead of a trace-backed reconstruction.
- In agent-only Elasticsearch mode, the worker now runs bounded server-side transaction aggregations for 60s and 300s `metric_buckets`, refreshes the latest ten minutes, and backfills the Elasticsearch seven-day retention window. It transfers only aggregate dimensions/counts/latency summaries into ClickHouse. Elasticsearch percentile aggregation is approximate; native ClickHouse trace aggregation remains exact.
- The current worker cycle completed with `elasticsearch_read=0`, `elasticsearch_inserted=0`, and 930 aggregate metric buckets written for its latest six-hour window. The former `billing_reconcile_job` principal currently has no retained metric buckets in the selected window, so that specific chart stays empty. A different retained principal, `svc_checkout_gateway`, rendered six nonempty line curves in Chromium; the Activity view made no `/api/v1/users/{principal}/performance` request and reported zero page errors.
- Verification: 16 focused backend tests passed, including a guard that a principal with raw traces but no metric buckets is absent from aggregate APIs. The frontend TypeScript/Vite build passed, the live Elasticsearch server-side aggregate query returned HTTP 200, and the active worker completed its metric stage in 10.5 seconds.

## Raw-trace API boundary and service-only topology (2026-09-24)

- User-facing ClickHouse reads were moved from raw `traces` to `metric_buckets`, existing service aggregates, topology relationship rollups, and precomputed change/anomaly data. Worker aggregation, ingestion/deduplication, and internal behavioral/anomaly processing retain their required raw reads. Trace Explorer is the explicit temporary exception: it reads the configured trace store, including ClickHouse `traces` in ClickHouse mode; ELK mode reads Elasticsearch.
- Added topology rollup support for authentication-failure and service-instance metrics, plus API/worker/owner ClickHouse role selection and deployment wiring. Role-specific usernames/passwords fall back to the existing connection credentials until separately provisioned; this repository does not create ClickHouse users or grants.
- Topology APIs provide service graph, lazy service API/user lists, searchable user directory, user services/APIs, and paginated IP context using rollups and stable service-edge IDs. Lists are bounded and keyset paginated.
- The topology canvas renders only service nodes and service edges, with faint blue context edges and centralized yellow selection highlights. Service-first and user-first flows use scrollable DOM panels, lazy requests, and preserve graph coordinates through selection and refresh.
- Selected services now highlight connected service edges in yellow, with highlighted lines and arrowheads above blue context edges. Clicking outside the scrollable relationship panels dismisses them; each panel has a close button, and the User directory has a reopen button.
- API/User selections now use scoped connection rollups: selected API calls use `/api/v1/topology/services/{service}/api-connections`, while selected Users and User → Service → API paths use `/api/v1/topology/principals/{principal}/connections` with optional Service/API filters. Yellow edge membership and TPS labels come from the same filtered response.
- The topology floating UI was compacted: the title/search/mode card uses a 300px footprint with its explanatory text available to screen readers; relationship lists are capped at 240px by 220px; history opens as a small popup; zoom and bottom status controls use less canvas space.
- Prometheus `/metrics` now reads only the worker snapshot/checkpoint and returns zeroed worker-domain values until a first snapshot exists; it cannot invoke worker aggregation on the scrape path.
- Added the API raw-query boundary regression tests and `docs/topology-read-model.md`. Focused topology, Prometheus, and boundary tests passed 17/17. The final full backend suite passed 207 tests with one failure: the existing unusual-access reason-priority assertion expected “failure burst” while the detector returned the established-IP new-endpoint reason. Frontend lint/build and Python compilation passed. `git diff --check` reports three trailing-whitespace lines in the pre-existing dirty `generate_30day_demo_dataset.py`; no such issue remains in the implementation files.

## User Intelligence profile missing for selected window (2026-09-24)

- Root cause: `UserLayout` requested `/api/v1/principals/{principal}` for its profile. That endpoint reads 60-second metric buckets inside the selected window and returns 404 when there are no buckets. For `mobile_banking_gateway`, the selected seven-day range started at 2026-09-17 02:16 UTC, while its 300-second metric series ended at 2026-09-17 01:50 UTC; its principal summary still recorded activity through 2026-09-23. The profile endpoint therefore treated an existing user as missing, and the metric-bucket fallback was empty for the selected range.
- Switched the shared workspace header to `/api/v1/users/{principal}`, which reads derived identity summaries and returned HTTP 200 for the same principal and filters. The activity charts continue to use worker metric buckets and can remain empty when the selected window has no rollups.
- Verified the live `/api/v1/principals/{principal}` request returned 404 for the selected range, its five-minute metric request returned an empty list, and `/api/v1/users/{principal}` returned HTTP 200 with the same range. Frontend TypeScript/Vite production build passed.

## Live ELK aggregation and Trace Explorer repair (2026-09-24)

- The active worker's Elasticsearch metric query failed with HTTP 400 after commit `2a88bc0` added `topology.metric_operation` normalization. Elasticsearch 7.17 Painless rejected string regex arguments passed to `replaceAll` (`String` cannot cast to `Pattern`). The replacement uses regex literals and replacement lambdas; a live read-only aggregation returned HTTP 200 and seven populated buckets before deployment.
- Restarted the managed API and worker with `./run_server.sh restart`. The active host worker's `process_elasticsearch` stage completes successfully, with subsequent cycles materializing 222, 756, and more metric buckets. Retained-window backfill continues on the 60-second worker cadence.
- `run_server.sh` now defaults analytics to `OTEL_STORAGE_BACKEND=clickhouse` and raw trace reads to `OTEL_TRACE_STORAGE_BACKEND=elasticsearch`, because live APM traces are stored in ELK and are not copied into ClickHouse in agent-only mode. The active `/api/v1/health` reports both values. Trace ID `2fed16bb627eb937602ba972d48c456c`, which was previously present only in ELK and returned empty/404 from `:30102`, now returns one list item and a one-span waterfall from the live API. The topology graph remains on its existing ClickHouse read model; a broad ELK backend switch exposed an unrelated SQL 503, so only the raw trace read path was switched.
- Read-only validation covered the ELK transaction query, worker job status, recent ClickHouse 60-second/300-second buckets, API health, trace list/detail, and `run_server.sh` shell syntax. No `kubectl` command was used.
- Six focused Elasticsearch trace and metric tests passed. After the final split configuration, `/api/v1/topology/services` returned HTTP 200, and Trace Explorer returned a fresh Sep 24 APM trace from Elasticsearch. An older cluster worker at `10.244.1.196` writes `Name or service not known` failures to the same `jobs` table; the active host worker's successful cycles appear from `10.244.0.1` in ClickHouse query logs. Therefore `/api/v1/ingestion/status.jobs` may alternate between success and failure until the older deployment is updated separately.
