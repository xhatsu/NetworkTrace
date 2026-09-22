# TraceScope & Testbed Cluster Services — STATE.md

## 1. Active Cluster Services & Telemetry Ingestion

### Kubernetes Testbed Services
- **Elasticsearch Datastore (`tmp-elk-svc`)**:
  - Service Type: `NodePort` (previously `ClusterIP`)
  - Cluster IP: `10.97.180.119:9200`
  - NodePort: `32073` (`http://127.0.0.1:32073` or `http://<NODE_IP>:32073`)
  - Status: Healthy, open, serving cluster `tracescope-elk-testbed` (version 7.17.24).
  - Indices:
    - `apm-*-transaction-*`: Ingested APM transaction traces across `networktracing`, `order-service`, `payment-service`.
    - `apm-*-metric-*`: System and runtime metrics.
    - `apm-*-span-*`: Distributed span hierarchy.
    - `apm-*-error-*`: Unhandled exceptions and error envelopes.

- **Elastic APM Server Ingestion Gateway (`apm-server`)**:
  - Service Type: `NodePort`
  - Cluster IP: `10.99.87.70:8200`
  - NodePort: `32765` (`http://127.0.0.1:32765` or `http://<NODE_IP>:32765`)
  - Role: Stateless ingestion pipeline validating OTLP / APM agent payloads and buffering them into Elasticsearch (`tmp-elk-svc`).

- **ClickHouse Cluster Datastore (`tracescope-clickhouse`)**:
  - Service Type: `ClusterIP`
  - Cluster IP: `10.105.101.253:8123` (auto-detected by `backend/config.py:_detect_clickhouse_host`)
  - Status: Healthy, open, serving ClickHouse 24.8.14.39.
    - `tracescope` (Application database): **2,000,000 traces, 43,616 1m buckets, 14,538 5m buckets, 1,304 baselines, 915 anomaly events, 399 principal behavioral change events, 11 enterprise system accounts + unauthenticated traffic** (Populated via `backend/scripts/generate_2m_enterprise_dataset.py` with authentic telecom/enterprise system accounts: `telecom_sync_svc`, `vtp_express_dispatch`, `pos_checkout_terminal`, `billing_reconcile_job`, `interbank_settlement_gw`, `partner_sales_broker`, `enterprise_b2b_gateway`, `secops_monitor_agent`, `sysadmin_deploy_agent`, `mobile_miniapp_gateway`, `audit_compliance_worker`, and `unknown` / unauthenticated public traffic across `apex-*` microservices).
    - **2,000,000 Trace Storage Benchmark & ClickHouse Trace Cleanup**:
      - ClickHouse `tracescope.traces`: **Truncated & cleaned to 0 rows / 0 bytes** (Freed ~388 MiB of redundant disk storage; active application database size dropped from 413.5 MiB to **25.8 MiB**).
      - Derived Aggregates Retained: All 1m & 5m `metric_buckets` (488k rows), `topology_*` (274k rows), `principals`, `baseline_metrics`, `anomaly_events`, and `incidents` remain 100% intact and serving all dashboards.
      - Elasticsearch Datastore (`tmp-elk-svc` on `:32073`): **542.79 MiB**, 2,014,679 transaction documents retained permanently as the primary system of record for distributed waterfall traces and deep audits.
      - Storage Invariant: ClickHouse only needs raw trace data during the worker aggregation stage to produce compact rollups, topology edges, and baselines; once processed, ClickHouse does not require past raw traces, as trace search and span waterfall queries resolve transparently against Elasticsearch via `ElasticsearchTraceRepository`.
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
  - `OTEL_STORAGE_BACKEND="clickhouse"` (with transparent Elasticsearch query bridge)
- **Lifecycle Integration (`run_server.sh`)**:
  - Default `ELASTICSEARCH_NODEPORT="32073"`
  - Automatically exports `OTEL_ES_URL` and `OTEL_ES_INDEX` to both `tracescope-30102` and `tracescope-worker` tmux sessions.
  - `run_server.sh status` verifies connectivity directly to NodePort 32073.
- **Worker Stages (`backend/worker.py`)**:
  1. `sync_elasticsearch`: Incremental trace reader (`ElasticsearchReader`) pulls APM transaction hits from NodePort 32073, normalizes them via `normalize_otel_record`, and persists them into ClickHouse `traces` table with checkpoint deduplication.
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
- Five-minute topology series expose the same bandwidth fields for line-chart use. ClickHouse reads the existing bounded topology byte rollups; Elasticsearch uses runtime byte extraction and server-side sum aggregations without copying application traces into ClickHouse.
- `GET /api/v1/services/{service}/bandwidth` provides a dedicated service bandwidth response with window totals and five-minute series. Existing service detail health includes the bandwidth totals/rates and a nested `bandwidth` payload.
- `GET /api/v1/users/{principal}/performance` now includes bandwidth fields per bucket, a top-level bandwidth summary, current/baseline five-minute bandwidth KPIs, and `bandwidth_pct` delta. API drilldowns receive the same fields through the existing topology API metrics response.
- Units are explicit: byte totals are bytes, `*_bytes_per_second` values are bytes/second, and `bandwidth_bits_per_second` is bits/second. Missing byte telemetry remains zero and is never inferred from request counts.
- Verification: focused interactive topology/bandwidth tests passed **5/5**; API and behavioral regressions passed **19/19**; Python compilation and `git diff --check` passed.

## Anomaly detail ID namespace fix (2026-09-22)

- Root cause of `/anomalies/6739330567467241` returning `Anomaly not found`: the ID is a `principal_change_events` record (`CALLER_PRINCIPAL_SWITCH` for `partner_sales_broker`), not an `anomaly_events` record.
- Added `GET /api/v1/user-changes/{change_id}` and `UserRepository.get_change()` for exact behavioral-change lookup.
- Overview change cards now open `/users/{principal}/changes?change_id=...`; legacy direct anomaly links fall back to that User Changes tab after resolving the change ID.
- Frontend type-check/build, backend Python compilation, and `git diff --check` passed. The public API was checked read-only: health is `200`, the supplied anomaly URL is `404`, and a current anomaly detail URL returns `200`.
