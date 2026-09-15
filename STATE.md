> **Port migration:** The active hub is OTelTrace on `0.0.0.0:30102`. The former NetworkTracing hub on `:31115` is legacy and is not used.

# TraceScope Project State (STATE.md)

This file tracks the current state, accessibility, conveniences, and guides for the TraceScope codebase.

## 1. Access & Endpoints
- **Working Directory**: `/home/ubuntu/Viettel/OtelTrace`
- **Dashboard URL**: `http://0.0.0.0:30102` (lifecycle-script default and current listener)
- **NetworkTracing Hub URL**: `http://0.0.0.0:30102` (OTLP / Ingest Hub)
- **Ingest NodePort**: `http://<node-ip>:30103/api/ingest` (Plain HTTP / non-SSL NodePort entrypoint for legacy C++ shippers such as `nt-ship-cpp` / `nt-sniff-cpp` without TLS compiled in; verified live on node `129.150.59.233:30103`)
- **Ingress HTTP NodePort**: `http://<node-ip>:31561` (Cluster Ingress-Nginx NodePort for plain HTTP routing across `/api/ingest`, `/api/agent/stats`, `/api`, and `/`; verified live on node `129.150.59.233:31561`)
- **Cluster Node IPs**: Internal `10.0.0.35`, Public `129.150.59.233` (both ports `31561` and `30103` accessible)
- **Agent Ingestion Authentication**: `apiKey: ""` is active on the cluster; unauthenticated `POST /api/ingest` and `POST /api/agent/stats` verified returning HTTP 200 on both NodePorts (`:31561`, `:30103`) and FQDN (`https://trace.n2d.id.vn/api/ingest`).
- **UI Design System**: Redesigned following the Behavioral Observability specification:
  - Typography: `Inter` (`cv01`, `ss03`) + `JetBrains Mono` for tabular metrics and percentiles, with application-wide 120% base font scaling (`html { font-size: 120%; }`, 13px chart ticks, scaled canvas labels, and proportional pixel utility adjustments).
  - Aesthetics: Linear & Sentry developer tooling palette (`#08090a` canvas, `#0e1116` panels, whisper-thin borders `rgba(255,255,255,0.07)`)
  - Primary Sidebar Navigation:
    1. **Overview** (`/`): Health KPIs, comparative series, top services, top principals, open incidents
    2. **Topology** (`/topology`): Interactive canvas call graph with edge inspector drawer (caller -> target, top principals, top operations)
    3. **Anomalies** (`/anomalies`, `/anomalies/:id`): Incident list and Anomaly Detail with "WHAT CHANGED COMPARED WITH NORMAL?" explainability card, probable root cause, and blast radius
    4. **Services** (`/services`, `/services/:name`): Service catalog, operations breakdown, caller dependencies, instances
    5. **Principals** (`/principals`, `/principals/:name`): Identity behavioral explorer, target services, operations, and hourly activity cycles
    6. **Traces** (`/traces`, `/traces/:id`): Filterable trace list and multi-tier interactive span waterfall visualizer
    7. **Users** (`/users`, `/users/:principal`): Searchable principal inventory and evidence-rich credential profile
    8. **User Changes** (`/user-changes`): Explainable identity behavior-change feed with lifecycle actions
    9. **User Graph** (`/user-graph`): Caller -> principal -> target Canvas graph
    10. **User Analytics** (`/user-analytics`): Active, changed, shared, source-diverse, and broad-access accounts
    11. **Agent Fleet** (`/agent-stats`): Real-time inventory of reporting oldkernel capture agents with status badges, throughput, and buffer queue metrics
    12. **Agent Time-Series Drilldown** (`/agent-stats/:node`): Dedicated node time-series performance dashboards across shipping throughput (kbps & ev/s), kernel/ship drop rates, pinned CPU core & RSS memory, queue backpressure, and process safety limits
  - Global Search Bar in header for instant navigation across services, principals, and trace IDs.
- **REST API Endpoints (TraceScope :30102)**:
  - System Health: `GET /api/v1/health`
  - Overview: `GET /api/v1/overview`
  - Services: `GET /api/v1/services`, `GET /api/v1/services/{service}`, `GET /api/v1/services/{service}/metrics`, `GET /api/v1/services/{service}/dependencies`
  - Principals: `GET /api/v1/principals`, `GET /api/v1/principals/{principal}`, `GET /api/v1/principals/{principal}/metrics`
  - Topology: `GET /api/v1/topology`, `GET /api/v1/topology/service/{service}`
  - Anomalies: `GET /api/v1/anomalies`, `GET /api/v1/anomalies/{id}`, `PATCH /api/v1/anomalies/{id}`
  - Traces: `GET /api/v1/traces`, `GET /api/v1/traces/{trace_id}`
  - Blast Radius: `GET /api/v1/blast-radius/{service}`
  - Ingestion: `POST /api/v1/ingest` (canonical), `POST /api/v1/ingest/traces` (compatibility alias), and `POST /api/ingest` (exact NetworkTracing old-kernel shipper path). All accept OTEL/ELK records and the NetworkTracing old-kernel `{"node": "...", "events": [...]}` envelope; file import also unwraps the envelope, and missing legacy event fields are optional and safely defaulted. Fully supports `Content-Encoding: gzip` / magic-byte payload decompression, rejects corrupted gzip with HTTP 400 Bad Request, and enforces transaction-atomic `X-Batch-Id` deduplication (HTTP 200 `{"ok": true, "duplicate": true}` on replay, preventing duplicate trace writes on shipper retries).
  - High-TPS Admission & Commit: all HTTP trace receivers use `backend/app/services/ingest_writer.py`. The process-local writer has a 256-request bounded queue and coalesces uploads arriving within 5 ms up to 50,000 records into batched ClickHouse INSERTs. Queue saturation returns HTTP 429 with `Retry-After: 1`; commit timeout returns HTTP 503 with the same retry header. A success response is returned only after commit. Trace rows and `X-Batch-Id` are committed atomically.
  - Analytics Freshness: ingestion no longer starts rollup and principal-intelligence rebuilds per HTTP request. The dedicated `tracescope-worker` consumes newly committed traces on its normal 60-second cadence, preventing an analytics write stampede during fleet bursts.
  - High-TPS Tuning: `OTEL_INGEST_QUEUE_CAPACITY` (default `256` requests), `OTEL_INGEST_COALESCE_MS` (default `5`), `OTEL_INGEST_TRANSACTION_RECORDS` (default `50000`), and `OTEL_INGEST_COMMIT_TIMEOUT_SECONDS` (default `65`). Uploaders should always send stable `X-Batch-Id` values and retry HTTP 429/503 using exponential backoff while honoring `Retry-After`.
  - Ingestion Batch Tracking: `ingest_batches` ClickHouse table (managed via `IngestBatchRepository` in `backend/app/repositories/ingest_batch_repository.py`) with thread-safe in-memory LRU cache and automatic 7-day TTL pruning.
  - Ingestion Status: `GET /api/v1/ingestion/status`; the `ingest_writer` object reports queue depth/capacity, writer liveness, accepted/rejected/committed/duplicate/failed request counters, committed records, and coalesced write transaction count.
  - Agent Statistics Protocol v1: `POST /api/agent/stats` (sample ingestion with 16 KiB ceiling and bounded reason enums), `GET /api/agent/stats` (fleet latest summary), `GET /api/agent/stats/{node}[?instance_id=<id>]` (node latest status and instance list), `GET /api/agent/stats/{node}/history[?instance_id=<id>]` (chronological metric samples with unwrapped time-series points), and `DELETE /api/agent/stats/{node}[?instance_id=<id>]` / `DELETE /api/agent/stats/{node}/{instance_id}` (purges specific instance or whole node)
  - User Inventory/Profile: `GET /api/v1/users`, `GET /api/v1/users/summary`, `GET /api/v1/users/{principal}` and its `summary`, `callers`, `sources`, `targets`, `operations`, `timeline`, and `changes` subresources
  - User Changes & Review: `GET /api/v1/user-changes`, `PATCH /api/v1/user-changes/{id}`, `POST /api/v1/user-changes/{id}/review` (operator overrides with scope and optional expiry)
  - Bounded Security Incidents: `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}` (15m windowing, 30m idle close, 24h cap, family-capped scoring)
  - User Graph/Analytics: `GET /api/v1/user-graph`, `GET /api/v1/user-graph/{principal}`, `GET /api/v1/user-analytics`
  - Cross-links: `GET /api/v1/services/{service}/users`, `GET /api/v1/anomalies/{id}/users`
  - OpenAPI Documentation: `http://0.0.0.0:30102/api/docs`
- **Lifecycle Control**:
  - Script: `./run_server.sh {start|stop|restart|status}`
  - Persistent tmux sessions: `tracescope-30102` (FastAPI backend + built static UI) and `tracescope-worker` (unified `traces`/`metric_buckets` rollup, baseline, and detector worker)
  - Uses `.venv/bin/python` automatically when available. Set `OTEL_API_KEY` to require `X-API-Key` for mutations.

---

## 2. Tested & Verified Features
- **Database Schema & Current Ingested Dataset**:
  - ClickHouse is the sole store (SQLite `data/tracescope.db` purged 2026-09-11 after parity verification).
  - Active dataset: 50,000 traces ingested from `/home/ubuntu/Viettel/Data/sample_abnormal_traces_50k.jsonl.gz` with ground-truth abnormal observability and behavioral change scenarios.
  - Processing uses a stable incremental trace cursor. The initial historical bootstrap uses the oldest 75% as baseline and evaluates the newest 25% for behavioral and statistical deviations.
  - Migrations `001_initial.sql` through `012_ingest_batch_dedup.sql` applied cleanly.
- **Identity Normalization & Realm Removal**:
  - `realm` (`principal_realm`) has been completely eradicated across models, normalization, behavioral engine, database inserts, and frontend UI.
  - Telemetry sources (PCAP, OTel APM) only emit bare usernames (e.g. `product`, `sale`, `vtp`, `guest_checkout_partner`).
  - Canonical `principal_id` format is streamlined to `{environment}:{principal_name}` (e.g. `production:product`).
- **In-Memory Credential Sanitization & Identity Extraction**:
  - Focus: Currently restricted strictly to **header-derived accounts** (`Authorization: Basic <base64>`) and namespaced **WSSE UsernameTokens** (`<wsse:Username>`).
  - Passwords and sensitive tokens are decoded and scrubbed in-memory, retaining only the authenticated username.
  - Unauthenticated transactions safely default to `unknown`.
- **Aggregations & Baselines**:
  - Rollups: 46,307 1-minute buckets, 36,562 5-minute buckets, 33 service edges, 232 principal edges.
  - Baselines: 3,860 rolling baselines computed using rolling medians and MAD across minute-of-week and hour-of-day.
  - Five-minute p50/p95/p99 values use raw samples from complete affected windows.
- **Anomaly Detection & User Intelligence Results**:
  - Detectors 1–8 evaluated across windows: 1,654 core anomaly events persisted (latency shifts, unusual execution times, error rates, new principal edges).
  - User Behavioral Changes: 3,113 behavioral change events across `NEW_RELATIONSHIP` (3,018), `NEW_SOURCE_IP` (42), `NEW_OPERATION` (28), `NEW_CALLER` (12), `NEW_PRINCIPAL_ON_SOURCE` (12), `NEW_TARGET` (9), and `USERNAME_FIRST_SEEN` (2).
  - Bounded Security Incidents: 41 incidents generated with strict family caps (origin 35, access 40, activity 35, identity mapping 30, auth 45).
- **Frontend SPA & Real Browser Playwright Verification**:
  - Built with Vite + React 19 + TypeScript + Tailwind CSS (`tsc -b && vite build` passed).
  - Executed headless Chromium Playwright across all 15 SPA routes, including all five User Intelligence routes.
  - 15/15 pages passed in real browser with 0 unhandled `pageerror` exceptions, 0 React render crash boundaries, and full TanStack Query hydration.
  - Resolved `Uncaught TypeError: Cannot read properties of undefined (reading 'toFixed')` on `/anomalies` by hardening null-checks and synchronizing data schemas across backend and frontend.
  - Resolved `Uncaught TypeError: Cannot read properties of undefined (reading 'length')` on `/anomalies/:id` by adding defensive optional chaining on `contributors`, `limitations`, `trace_ids`, and timestamp windows.
  - Resolved `TypeError: Cannot read properties of undefined (reading 'map')` on `/services/:name` and `/principals/:name` by adding safe fallback arrays and enriching backend responses with complete operational percentiles and dependency relationships.
- **Automated Test Suite**:
  - 139/139 tests passed via `.venv/bin/python -m pytest tests/` using isolated temporary ClickHouse databases with dynamic host discovery across local and Kubernetes pod networks.
  - High-TPS ingestion coverage in `tests/test_ingest_writer.py` verifies concurrent HTTP request coalescing, a bounded coalescing ClickHouse writer, transaction-atomic concurrent batch deduplication, bounded queue rejection, and HTTP 429/`Retry-After` behavior.
  - Storage Isolation (`tests/test_agent_traces_only.py`): Verifies the storage invariant where ClickHouse stores host/probe agent trace data while application OTel traces are acknowledged and bypassed to protect against duplicate storage expansion.
  - System Telemetry Retention (`tests/test_system_retention.py`): Enforces bounded TTL (3-day on system logs, 7-day on error logs) via migration `005_system_telemetry_retention.sql` and CLI maintenance commands.
  - Principal Readiness Summary (`tests/test_principal_readiness_summary.py`): Validates compact AggregatingMergeTree summary tables via migration `006_principal_readiness_summary.sql` to avoid full trace scans during detector readiness evaluations.
  - Application Edge Security: Middle-tier `/internal/*` routes enforce token-based access control and respond with HTTP 404 to unauthenticated callers, providing edge isolation without requiring ingress snippet annotations.
  - Comprehensive coverage across canonical identity normalization, batch deduplication (`tests/test_batch_dedup_and_gzip.py`), detector readiness, multi-layer candidate promotion, bounded incidents, capped family scoring, 7-question explainability cards, dedicated IP anomalies, and WSSE secret hygiene.
  - User behavior scores count each distinct evidence category once; repeated relationship events within a window deduplicate and contribute once. Bounded incidents enforce strict family caps (origin 35, access 40, activity 35, identity mapping 30, auth 45).
  - Frontend lint/type check and production build passed (`tsc -b && vite build` passed 100%).
  - 42/42 end-to-end curl contract tests passed via `sh backend/scripts/curl_test_all_pages.sh` across all 17 SPA routes (including `/agent-stats` and `/agent-stats/:node`) and 25 backing APIs.
  - 15/15 real browser Playwright tests passed via `python3 backend/scripts/test_pages_playwright.py`.
  - Lifecycle stack started successfully: `tracescope-30102` and `tracescope-worker` tmux sessions active; `0.0.0.0:30102` and bootstrap `0.0.0.0:30105` listening.
  - `GET /api/v1/ingestion/status` reports the high-TPS writer alive with queue depth/capacity, transaction, commit, duplicate, rejection, and failure counters.
  - A labeled `/api/ingest` self-test committed once; replay with the identical `X-Batch-Id` returned HTTP 200 with `duplicate=true`, `received=0`, and `inserted=0`.
  - Final verification: 74/74 isolated pytest cases passed in 10.02 seconds and all 42 live curl/JavaScript-safety checks passed.
- **PCAP Authentication & Identity Extraction Tooling**:
  - Scripts: [`backend/scripts/inspect_pcap_auth.py`](backend/scripts/inspect_pcap_auth.py) and [`~/Viettel/Data/inspect_pcap_auth.py`](file:///home/ubuntu/Viettel/Data/inspect_pcap_auth.py)
  - Pure Python 3 standard library (no pip packages needed).
  - Inspects PCAPs (Ethernet, Linux cooked SLL v1/v2, raw IP, compressed `.gz`).
  - Decodes and extracts usernames from:
    - HTTP Basic Auth: `Authorization: Basic <base64>` (extracts username, scrubs passwords in memory).
    - WSSE SOAP XML: `<wsse:Username>...</wsse:Username>` inside SOAP Security headers.
    - WSSE HTTP Headers: `X-WSSE: UsernameToken Username="..."`.
    - Bearer Tokens: Decodes JWT payload for `sub`, `username`, `preferred_username`.
  - CLI Options:
    - Standard tabular summary: `python3 inspect_pcap_auth.py <file.pcap>`
    - Detailed occurrence log: `python3 inspect_pcap_auth.py <file.pcap> --verbose`
    - Machine-readable JSON: `python3 inspect_pcap_auth.py <file.pcap> --json`
- **Active Hub WSSE UsernameToken Attribution**:
  - Both old-kernel compatibility `POST /api/ingest` and native `POST /v1/traces` can attribute a namespaced SOAP `UsernameToken` or an explicitly sanitized WSSE username attribute.
  - Supported `secext` namespaces: OASIS 2004, legacy 2002/07, legacy 2002/12, and legacy 2003/06.
  - Only the normalized username and `auth_scheme=wsse` are stored. SOAP bodies, passwords/password digests, nonces, and credential-bearing attributes are not persisted or logged.
  - Malformed XML, missing or unnamespaced usernames, DTD/entity documents, oversized bodies, invalid control characters, and usernames longer than 200 characters remain anonymous.
  - Live verification on `0.0.0.0:30102`: compatibility ingest returned HTTP 200 (`received=1`, `inserted=1`, `rejected=0`); legacy-2003-namespace trace `c3010200000000000000000020260909` stored/API-reported `e2e.wsse.legacy.20260908` with scheme `wsse` and no raw SOAP; health remained HTTP 200 after `run_server.sh restart`.
  - `/tmp/wsse-java-service` now uses a bounded, namespace-aware Java XML
    reader and a clearly labeled minimal/manual OTLP HTTP JSON exporter (no
    OpenTelemetry SDK jars/build dependencies are available). Its user service
    is configurable through `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`,
    `OTEL_SERVICE_NAME`, namespace/instance/environment variables, bind address,
    port, request bound, and exporter timeout. Only sanitized `wsse.username`
    reaches OTLP; raw SOAP and UsernameToken secrets never do.
  - Live veth verification trace `d3010200000000000000000020260908`
    is queryable and contains two spans: passive oldkernel capture plus its Java
    manual-OTLP child. Both store `e2e.oldkernel.wsse` with scheme `wsse`.
    Legacy 2002/07, 2002/12, and 2003/06 live traces each stored two matching
    spans as well. Database secret-marker count was zero; DTD and oversized
    Java requests returned HTTP 400 and 413, and service health remained 200.
  - Final active-hub verification: 49 pytest tests and all 37 curl/JavaScript
    safety checks passed. OTelTrace was not restarted because no active backend
    code changed; it remained healthy on `0.0.0.0:30102` throughout.
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
  - `generate_traces.py`:
    - Usage: `python3 /home/ubuntu/Viettel/Data/generate_traces.py [options]`
    - Flags:
      - `--count <N>`: Total traces to generate (default: 2,000,000).
      - `--hours <H>`: Time window in hours backwards from end time (default: 24.0).
      - `--days <D>`: Time window in days backwards from end time (e.g. `--days 15` overrides `--hours`).
      - `--anomalies <all|none|list>`: Comma-separated scenario names or 'all' or 'none'.
      - `--list-anomalies`: Display table of available scenarios and exit.
      - `--output <path>`: Destination compressed `.jsonl.gz` or `.jsonl` file.
      - `--preview <path>`: Preview JSON output destination (default: `otel_elk_sample_preview.json`).
  - `send_traces.py`:
    - Usage: `python3 /home/ubuntu/Viettel/Data/send_traces.py [options]`
    - Flags:
      - `--input <path>`: Source file (default: `otel_elk_traces_2m.jsonl.gz`).
      - `--mode <http|direct>`: Ingestion mode (`http` streams batched POST to `/api/v1/ingest`; `direct` performs batch ClickHouse write, auto-tuned to 5,000 batch size).
      - `--url <URL>`: API ingestion URL (default: `http://127.0.0.1:30102/api/v1/ingest`).
      - `--batch-size <N>`: Records per batch chunk (default: 500 for http, 5000 for direct).
      - `--limit <N>`: Maximum records to send (e.g. `--limit 10000` for testing).
- **15-Day 2,000,000 Data Point Production Dataset**:
  - File: `/home/ubuntu/Viettel/Data/otel_elk_traces_2m.jsonl.gz` (495.27 MB, 2,000,000 records).
  - Preview: `/home/ubuntu/Viettel/Data/otel_elk_sample_preview.json` (100 sample records).
  - Timespan: Exactly 15 days (360.0 hours) from `2026-08-24 07:29:10 UTC` to `2026-09-08 07:29:12 UTC` (ending today right now).
  - Baseline/Drift Partition: Oldest 75% (0.0h - 270.0h / 11.25 days) forms historical baseline; newest 25% (270.0h - 360.0h / 3.75 days) contains behavioral drifts and active incidents.
  - Injected Ground Truth:
    - `traffic_spike`: 5,366 tx across 3 windows (90-92h, 234-236h, 348-350h).
    - `traffic_drop`: 429 tx across 2 windows (162-163.5h, 354-355.5h).
    - `latency_blowout`: 772 tx across 2 windows (144-146h, 352-354h).
    - `cascading_failure`: 1,737 tx across 2 windows (216-218h, 356-358h).
    - `new_service_edge`: 3,369 tx (336h - 360h).
    - `new_operation`: 769 tx (340h - 360h).
    - `user_first_seen`: 95,027 tx (274.5h - 360h).
    - `user_new_caller`: 12,637 tx (279h - 360h).
    - `user_new_source_ip`: 13,143 tx (283.5h - 360h).
    - `user_new_target`: 3,299 tx (274.5h - 360h).
    - `user_new_operation`: 28,633 tx (279h - 360h).
    - `user_unusual_time`: 26,679 tx (270h - 360h, 02:00-04:30 UTC).
    - `user_dormant_reactivation`: 168,663 tx (292.5h - 360h).
    - `credential_abuse`: 4,872 tx (301.5h - 360h).
- **User Changes Page Display & Time Scope Resolution**:
  - Issue: The User Changes page (`/user-changes`) was showing 0 records because the global time filter in `App.tsx` defaulted to a rolling 3-hour window (`now - 3h` to `now`), whereas existing change events in `principal_change_events` were detected earlier in the historical dataset window.
  - Fix in `UserRepository.list_changes`: Added automatic graceful fallback. If the requested time window yields 0 events while changes exist in the database, `list_changes` returns recent events with `fallback_applied: True` and `total_unfiltered` count, preventing a blank screen.
  - Fix in `UserChangesPage` (`UserIntelligence.tsx`): Added a scope segmented toggle `[All Time ({count})] [Selected Window]`. Displays a banner notifying the user when the time window has no changes and offers a one-click switch to view all changes. Rebuilt frontend and verified with 15/15 Playwright browser tests.
- **Oldkernel Agent Package & Universal Bootstrap Server (Port 30105)**:
  - **Canonical Source of Truth**: The real `oldkernel` code (C++ sniffer, shipper, supervisor, scripts, Makefiles) canonically resides in `~/Viettel/NetworkTracing/oldkernel`. The deployment files reside in `~/Viettel/NetworkTracing/bundle`.
  - **Bootstrap Distribution Server**: Dedicated bootstrap and bundle distribution server resides in `~/Viettel/OtelTrace/bootstrap` (port 30105).
  - **Symlink Architecture**: `~/Viettel/OtelTrace/oldkernel -> ~/Viettel/NetworkTracing/oldkernel` and `~/Viettel/OtelTrace/bundle -> ~/Viettel/NetworkTracing/bundle` ensure single-source-of-truth integrity while packaging executes cleanly from `OtelTrace/bootstrap`.
  - **Universal Fleet Package (`bundle.tar.gz`)**: Packaged with both modern eBPF agents (`bin/`, `app/`) and real oldkernel agent code (`oldkernel/` containing `install-firstrun-el68.sh`, `nt-sniff-cpp`, `nt-ship-cpp`, `nt-sniff.py`, `nt-ship.py`, supervisor, and resource guards).
  - **Installer Auto-Delegation (`bundle/install.sh`)**: Automatically checks kernel floor (`uname -r`). On kernels < 5.5, it seamlessly delegates execution to the packaged `oldkernel/install-oldkernel.sh`. Also supports explicit `--oldkernel` and `--mode oldkernel` flags.
  - **Packaging Pipeline (`package-oldkernel.sh`)**: Compiles C++ binaries (`nt-sniff-cpp`, `nt-ship-cpp`) from canonical sources in `oldkernel`, rebuilds single-file firstrun bundle (`install-firstrun-el68.sh`, 472,641 bytes), syncs all 21 runtime files into `bundle/oldkernel`, and creates the 37,329,702 byte universal archive (`bundle.tar.gz`).
  - **Automated Verification (`verify-oldkernel-bootstrap.sh`)**: Exercises the live distribution server (:30105, PID 14422), verifying all endpoints (`/healthz`, `/bootstrap`, `/oldkernel/*`, `/bundle.tar.gz`), tarball integrity, installer dry-run preflight, and dynamic target IP injection.
  - Updated `run_server.sh` to automatically manage the bootstrap server lifecycle alongside TraceScope API (`:30102`) and background workers.
- **Kubernetes Workload Split & Role-Isolated Entrypoints (2026-09-11)**:
  - **Application roles**: `backend.app.application.create_app("all"|"ingest"|"agent-stats")`; `backend.main:app` retains the monolith-compatible public surface, while `backend.ingest_main:app` and `backend.agent_stats_main:app` expose isolated APIs.
  - **Horizontal edge scale**: the manifests start 3 ingestion replicas (HPA 3–12) and 2 agent lifecycle/reporting replicas (HPA 2–6). These pods mount no PVC and hold no local database.
  - **Single storage owner**: `tracescope-storage` is a one-replica StatefulSet containing the API/writer and analytics-worker sidecar. It is the only workload mounting `tracescope-data` (ReadWriteOnce) and the only SQLite lock domain.
  - **Internal boundary**: edge pods call authenticated `/internal/v1/*` endpoints at `http://tracescope-storage:8000`. Ingestion is normalized before forwarding; durable trace/batch commits remain coalesced and atomic. Agent latest/history/deletion operations and atomic sequence deduplication use the same boundary.
  - **Public compatibility**: the Ingress routes existing ingestion paths to `tracescope-ingest`, `/api/agent/stats*` to `tracescope-agent-stats`, and the SPA/query surface to `tracescope-api`. Existing URL contracts are unchanged; `/api/v1/health` adds `service_role`.
  - **Operations**: storage migrations run in one init container. Workloads have startup/readiness/liveness probes, requests/limits, non-root/read-only security contexts, PDBs, ConfigMap/Secret wiring, and immutable-image build targets in `deploy/docker/Dockerfile`.
  - **Validation**: `deploy/k8s/validate_manifests.py` performs local YAML/topology checks without cluster access. Role/storage integration coverage is in `tests/test_deployment_topology.py` and `tests/test_service_boundaries.py`.
  - **Runbook**: `deploy/k8s/README.md` documents image builds, secret creation, RWO block-storage requirements, backup/restore, migration, rollback, probes, HPA prerequisites, and the remaining single-owner SQLite throughput ceiling.
- **ClickHouse Persistence Migration (2026-09-11)**:
  - Primary database backend is ClickHouse (`http://127.0.0.1:8123`, database `tracescope`), driven by `clickhouse_connect` HTTP client with thread-local client caching.
  - All SQLite artifacts purged 2026-09-11 (`data/tracescope.db`, `data/benchmark-2m.db`, `backend/migrations/`, migration script) after the 351,936-row parity verification; ClickHouse backup/restore is the recovery path.
  - Compatibility adapter in `backend/app/repositories/db_context.py` handles:
    - Escaped `?` placeholder binding via `format_query_value` (no format collisions with `%`).
    - `ClickHouseRow` supporting mapping, tuple access, sequence slicing (`row[1:5]`), and table-alias stripping (`p.name` accessible as `name`).
    - Scalar `MAX(a, b)` / `MIN(a, b)` -> `greatest(a, b)` / `least(a, b)`.
    - `strftime` -> `formatDateTime(toDateTime(intDiv(ts, 1000)), fmt)`.
    - `GROUP_CONCAT` -> `arrayStringConcat(groupArray(toString(...)), ',')`.
    - Synchronous mutation execution: `ALTER TABLE ... UPDATE/DELETE ... SETTINGS mutations_sync = 1`.
    - `lastrowid` simulation via `SELECT max(id) FROM {table}` for autoincrement compatibility.
    - Column defaults: `id UInt64 DEFAULT toUnixTimestamp64Micro(now64(6))` for monotonic row IDs.
  - Full test suite passed: 98/98 tests passed across all 13 modules in `tests/`.
  - End-to-End Curl & Safety Suite: 42/42 checks passed (`sh backend/scripts/curl_test_all_pages.sh`), covering all 17 SPA routes and 25 backing API endpoints with 0 JavaScript crash vulnerabilities.
  - Manifest Validation: `python3 deploy/k8s/validate_manifests.py deploy/k8s` passed with 16 documents and 0 errors.

---

## 3. Kubernetes & ClickHouse Architecture

- **Current In-Flight Worktree State**:
  - The tree contains an active, large-scale ClickHouse cutover: all legacy SQLite migration scripts (`backend/migrations/*.sql`) and SQLite migration tooling have been removed from source control.
  - Persistence is consolidated in `backend/clickhouse_migrations/001_initial.sql` (35 tables) and managed through `ClickHouseRepository` / `db_context.py` using `clickhouse_connect`.
  - Application entrypoints are role-isolated via `backend/app/application.py` (`all`, `ingest`, `agent-stats`), backed by dedicated entrypoint modules `backend/main.py`, `backend/ingest_main.py`, and `backend/agent_stats_main.py`.
- **Async Batched ClickHouse Ingest Path (`backend/app/services/ingest_writer.py`)**:
  - Direct ClickHouse batch inserts via `db.client.insert("traces", ...)` and `db.client.insert("ingest_batches", ...)`.
  - Configurable coalescing window (`OTEL_INGEST_COALESCE_MS=5`) and batch size (`OTEL_INGEST_TRANSACTION_RECORDS=50000`).
  - Durable commit semantics: HTTP 200 returned only after ClickHouse writes synchronous block parts to disk.
  - Bounded admission queue (`OTEL_INGEST_QUEUE_CAPACITY=256`) returning HTTP 429 with `Retry-After: 1` on saturation.
  - Replay deduplication via `ingest_batches` ClickHouse table and in-memory LRU cache: repeated `X-Batch-Id` returns HTTP 200 `{"ok": true, "duplicate": true}` with zero database writes.
  - Agent stats telemetry (`backend/app/repositories/agent_stats_repository.py`) writes directly to `agent_stats_latest` and `agent_stats_history` with sequence deduplication and `FINAL` query semantics.
- **Edge Workload Decoupling**:
  - Edge pods (`tracescope-ingest` and `tracescope-agent-stats`) communicate directly with ClickHouse (`OTEL_CLICKHOUSE_HOST` / `OTEL_CLICKHOUSE_PORT`).
  - Storage-owner HTTP proxy forwarding (`OTEL_STORAGE_OWNER_URL`) is configured via `edge-config` ConfigMaps in Helm and Kubernetes manifests (`12-edge-configmap.yaml` and `edge-configmap.yaml`).
- **Kubernetes Architecture (`deploy/k8s/`)**:
  - **ClickHouse StatefulSet & Service** (`25-clickhouse-statefulset.yaml`, `26-clickhouse-service.yaml`): Runs `clickhouse/clickhouse-server:24.8` (1 replica), mounts RWO PVC `clickhouse-data` (5Gi test capacity, configurable), exposes HTTP 8123 and native 9000 ports.
  - **Application & Analytics StatefulSet** (`30-storage-statefulset.yaml`, `31-api-service.yaml`, `37-storage-service.yaml`): Named `tracescope-app` (pod `tracescope-app-0`). Consolidates `migrate` init container, `api` container (FastAPI + built-in React UI + Agent Stats on `:30102`), and `analytics-worker` sidecar into a single StatefulSet using image `xhatsu101/tracescope:app-0.2.0`.
  - **Horizontally Scalable Ingestion Pool** (`32-ingest-deployment.yaml`, `33-ingest-service.yaml`, `42-hpa.yaml`): High-performance ingest edge pool running `xhatsu101/tracescope:ingest-0.2.0` on `:30103`, auto-scaling from 3 to 12 replicas.
  - **Unified Ingress Routing** (`40-ingress.yaml`): Routes ingest traffic (`/api/v1/ingest`, `/api/ingest`, `/v1/traces`, `/api/v1/ingestion/status`) to `tracescope-ingest`, and all other traffic (`/`, `/assets`, `/api`, `/api/agent/stats`) directly to `tracescope-api`. Blocks `/internal/*` routes with HTTP 404 server-snippet.
  - **Manifest Validation & Topology Tests**: `python3 deploy/k8s/validate_manifests.py deploy/k8s` verifies all 17 documents and invariants cleanly with 0 errors. All deployment topology tests in `tests/test_deployment_topology.py` pass.
  - **Test Suite Status**: 111/111 tests passed in `.venv/bin/python -m pytest tests/ -q` (covering all 22 code review findings, streaming gzip limits, composite cursor paging, central mutation auth, and manifest invariants). Full details recorded in `FIX_REPORT.md`.

---

## 4. Helm Chart Design & Topology Modes (`deploy/helm/tracescope/`)

- **Production Helm Chart**:
  - Located at `deploy/helm/tracescope/` with `Chart.yaml` (v0.2.0), comprehensive `values.yaml`, and modular templates.
  - App pod named `tracescope-app-0` (StatefulSet `tracescope-app`), rendered with simplified `values.yaml` `app.image:` configuring `migrate`, `api`, and `analytics-worker` in one place.
  - Supports full **Distributed Mode** and **Consolidated / Merged Modes**:
    - **Default Managed Topology (3-Tier)**: `ui.enabled: false` (UI merged into API) and `agentStats.enabled: false` (agent telemetry merged into API). Reduces deployment overhead from 5 workloads (9–21 pods) down to 3 workloads (5 pods: ClickHouse, App API+UI+Worker, and Ingest HPA pool).
    - **Full Distributed Mode**: Enable `ui.enabled: true` and `agentStats.enabled: true` for independent scaling pools.
    - **External ClickHouse Mode**: `clickhouse.enabled: false` connects to external ClickHouse clusters via `clickhouse.host` and `clickhouse.password`.
    - **Snippet Directive Toggle**: `ingress.serverSnippet.enabled` (default `true`) controls `server-snippet` annotation rendering, allowing deployment on clusters where NGINX admission webhooks disable snippet directives (`--set ingress.serverSnippet.enabled=false`).
  - **Verification**: Verified via `helm lint` (0 errors) and `helm template` across all topology permutation cases. Tested `backend.main:app` with `TestClient` confirming HTTP 200 for `/`, `/api/v1/overview`, and `/api/agent/stats`.

---

## 5. 2-Image Architecture & Build/Push Pipeline

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
  - **Multi-Architecture / x86_64 Support**: Added `-p` / `--platform` flag (e.g. `--platform linux/amd64,linux/arm64` or `--platform linux/amd64`) leveraging Docker BuildKit / buildx. When built on an ARM64 host without `--platform`, images are `linux/arm64` only and will fail with `exec format error` on x86 nodes. Specifying `--platform linux/amd64,linux/arm64` creates a dual-architecture manifest list that works transparently on both x86_64 and ARM64 clusters.
  - Aligned with Helm chart (`deploy/helm/tracescope/values.yaml`): `agentStats.enabled: false` (consolidated into storage-0) and configured to use `xhatsu101/tracescope:app-0.2.0` if enabled.

---

## 6. Live Production User Data Push & End-to-End Verification (2026-09-12)

- **Production Target**: `https://trace.n2d.id.vn`
- **Ingestion Endpoint**: `POST /api/v1/ingest`
- **Shipper Script**: `/tmp/push_to_production.py`
  - Canonical OTLP JSON `resourceSpans` packaging with Gzip level 1 compression.
  - Bounded concurrency (3 threads), HTTP keep-alive, unique transaction-atomic `X-Batch-Id` headers.
  - Automatic exponential backoff on HTTP 429 and transient 5xx responses.
- **Dataset Ingested**: Exact first 250,000 spans of `/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz`.
  - Ingest performance: 250,000 spans acked (100% success, 0 rejected) in 56.19s at **4,449.3 spans/s** (8.9 batches/s).
  - Payload footprint: 228.49 MB uncompressed -> 24.58 MB transferred (9.3x compression ratio).
  - Rate limiting & Errors: 0 HTTP 429s, 2 transient HTTP 5xx errors smoothly retried and committed.
- **End-to-End User Intelligence Verification**:
  - **User Identity Extraction**: OpenTelemetry `enduser.id` semantic conventions correctly parsed by `otlp_parser.py` into canonical `principal_name` dimensions in ClickHouse.
  - **User Inventory (`/api/v1/users`)**: All 8 named identities present (`minh.ngoc`, `linh.pham`, `mai.tran`, `khanh.vu`, `duong.nguyen`, `quang.bui`, `hong.dang`, `thao.trang`).
  - **User Profiling (`/api/v1/users/minh.ngoc`)**: Target microservice request counts matched ground truth with 100% precision (`session-cache`: 6,186, `api-gateway`: 3,514, `notification-service`: 2,874, `catalog-service`: 1,925, `cart-service`: 1,335).
  - **User Interaction Graph (`/api/v1/user-graph`)**: 28 nodes (10 principals, 17 service targets) and 188 directed dual-layer access edges.
  - **User Analytics (`/api/v1/user-analytics`)**: All 10 ranking categories populated (`most_active`, `most_targets`, `most_operations`, `most_changed`, etc.).
  - **Behavioral Changes (`/api/v1/user-changes`)**: 625 change events across 4 detector families (`USERNAME_FIRST_SEEN`, `NEW_SOURCE_IP`, `NEW_TARGET`, `NEW_OPERATION`) complete with 7-question explainability cards.
  - **Security Incidents (`/api/v1/incidents`)**: 18 bounded security incidents with capped family scoring (Score 75 across all 8 named users).
  - **ClickHouse Trace Verification**: Direct lookups on multi-tier spans across all users returned HTTP 200 with waterfalls spanning up to 16 microservices.
- **Identified Production Infrastructure Limit**:
  - ClickHouse worker aggregation (`aggregate_traces`) during analytical cycles reached the container memory ceiling: `Code: 241. DB::Exception: Memory limit (total) exceeded: would use 1.81 GiB, maximum: 1.80 GiB`.
  - Recommendation: Increase ClickHouse container RAM limit to >= 4 GiB and implement bounded time-window chunking (max 24h slices) in `aggregate_traces`.
- **Comprehensive Report Deliverable**: Stored verbatim at `/home/ubuntu/Viettel/OtelTrace/USER_DATA_PUSH_TEST_REPORT.md`.

---

## 7. Release 0.2.2 Deployment Preparation & Preflight Fixes (2026-09-14)

- **Release Version**: `0.2.2`
  - Chart metadata: `deploy/helm/tracescope/Chart.yaml` bumped to `version: 0.2.2`, `appVersion: "0.2.2"`.
  - Application version: `backend/app/application.py` FastAPI `version="0.2.2"`.
  - Image tags: `xhatsu101/tracescope:app-0.2.2` and `xhatsu101/tracescope:ingest-0.2.2` built and pushed to Docker Hub.
    - App Digest: `sha256:721acd2ef5e7a35be9f1e3879c8daba5be728bc8bd57b481c624665da8052cbf`
    - Ingest Digest: `sha256:d03d3e20549bc44a43d8f2b3e993c07105c29f3760034bad27e1e0b38c0d05af`
- **Security & Secret Provisioning**:
  - Independent cryptographically random tokens (64 chars, urlsafe base64) generated and embedded into `deploy/helm/tracescope/values.yaml` under `secrets.internalApiToken` (`1Ioi...(64 chars)`) and `secrets.apiKey` (`XOyx...(64 chars)`).
  - Redaction strictly enforced across all logs, stdout, and reports.
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

## 8. Release 0.2.2 Commit & Secret Isolation (2026-09-14)

- **Secret Isolation**:
  - Real secrets (`secrets.internalApiToken` `1Ioi...(64 chars)` and `secrets.apiKey` `XOyx...(64 chars)`) moved from `deploy/helm/tracescope/values.yaml` into gitignored `deploy/helm/tracescope/values-secrets.yaml`.
  - Added `values-secrets.yaml` to `.gitignore`.
  - Stored empty strings with explanatory comments in `values.yaml`.
  - Updated operator runbook in `DEPLOY_FIX_REPORT.md` §4 and §5 to supply `-f deploy/helm/tracescope/values-secrets.yaml`.
  - Verified `helm template` passes with `-f values-secrets.yaml` and fails without it due to template validation guard.
- **Repository Cleanup**:
  - Confirmed database purge (ClickHouse sole datastore; no local SQLite/DuckDB files).
  - Cleaned untracked junk directories (`.agents`, `.codex`).
  - Flagged ambiguous task briefs for retention.
- **Verification**:
  - 123/123 tests passed cleanly (`123 passed in 260.88s`).
  - Verified 0 hits on secret leak scan across all Git history.

