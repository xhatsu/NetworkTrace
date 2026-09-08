> **Port migration:** The active hub is OTelTrace on `0.0.0.0:30102`. The former NetworkTracing hub on `:31115` is legacy and is not used.

# TraceScope Project State (STATE.md)

This file tracks the current state, accessibility, conveniences, and guides for the TraceScope codebase.

## 1. Access & Endpoints
- **Working Directory**: `/home/ubuntu/Viettel/OtelTrace`
- **Dashboard URL**: `http://0.0.0.0:30102` (lifecycle-script default and current listener)
- **NetworkTracing Hub URL**: `http://0.0.0.0:30102` (OTLP / Ingest Hub)
- **UI Design System**: Redesigned following the Behavioral Observability specification:
  - Aesthetics: Linear & Sentry developer tooling palette (`#08090a` canvas, `#0e1116` panels, whisper-thin borders `rgba(255,255,255,0.07)`)
  - Typography: `Inter` (`cv01`, `ss03`) + `JetBrains Mono` for tabular metrics and percentiles
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
  - Ingestion: `POST /api/v1/ingest` (canonical), `POST /api/v1/ingest/traces` (compatibility alias), and `POST /api/ingest` (exact NetworkTracing old-kernel shipper path). All accept OTEL/ELK records and the NetworkTracing old-kernel `{"node": "...", "events": [...]}` envelope; file import also unwraps the envelope, and missing legacy event fields are optional and safely defaulted.
  - Ingestion Status: `GET /api/v1/ingestion/status`
  - User Inventory/Profile: `GET /api/v1/users`, `GET /api/v1/users/summary`, `GET /api/v1/users/{principal}` and its `summary`, `callers`, `sources`, `targets`, `operations`, `timeline`, and `changes` subresources
  - User Changes: `GET /api/v1/user-changes`, `PATCH /api/v1/user-changes/{id}`
  - User Graph/Analytics: `GET /api/v1/user-graph`, `GET /api/v1/user-graph/{principal}`, `GET /api/v1/user-analytics`
  - Cross-links: `GET /api/v1/services/{service}/users`, `GET /api/v1/anomalies/{id}/users`
  - OpenAPI Documentation: `http://0.0.0.0:30102/api/docs`
- **Lifecycle Control**:
  - Script: `./run_server.sh {start|stop|restart|status}`
  - Persistent tmux sessions: `tracescope-30102` (FastAPI backend + built static UI) and `tracescope-worker` (unified `traces`/`metric_buckets` rollup, baseline, and detector worker)
  - Uses `.venv/bin/python` automatically when available. Set `OTEL_API_KEY` to require `X-API-Key` for mutations.

---

## 2. Tested & Verified Features
- **Database Schema**:
  - SQLite database in WAL mode at `data/tracescope.db`, passing `PRAGMA quick_check` (`ok`).
  - Currently in a **clean, completely wiped state** with 0 traces across all 29 schema tables, ready for fresh dataset ingestion.
  - Processing uses a stable incremental trace cursor. The initial configurable historical bootstrap uses the oldest 75% as baseline and evaluates the newest 25%.
  - Migrations `001_initial.sql` through `007_user_intelligence.sql` applied cleanly.
- **In-Memory Credential Sanitization & Identity Extraction**:
  - Focus: Currently restricted strictly to **header-derived accounts** (`Authorization: Basic <base64>`).
  - Passwords and sensitive tokens are decoded and scrubbed in-memory, retaining only the authenticated username.
  - Non-header identity sources (OTel `enduser.id`, ECS `user.name`/`user.id`, `account.username`) are commented out for future implementation.
  - Unauthenticated transactions safely default to `unknown`.
- **Aggregations & Baselines**:
  - Rollups: 55,321 1-minute buckets, 24,620 5-minute buckets, 42 service edges, 504 principal edges, 465 baselines computed using rolling medians and MAD.
  - Five-minute p50/p95/p99 values use raw samples from complete affected windows, including incremental ingestion updates.
- **Anomaly Detection (Milestones 1-8)**:
  - Detectors 1–8 evaluated across dataset: 2,415 anomaly events persisted after the corrected rebuild, with window-based deduplication for subsequent worker cycles.
- **Frontend SPA & Real Browser Playwright Verification**:
  - Built with Vite + React 19 + TypeScript + Tailwind CSS (`tsc -b && vite build` passed).
  - Executed headless Chromium Playwright across all 15 SPA routes, including all five User Intelligence routes.
  - 15/15 pages passed in real browser with 0 unhandled `pageerror` exceptions, 0 React render crash boundaries, and full TanStack Query hydration.
  - Resolved `Uncaught TypeError: Cannot read properties of undefined (reading 'toFixed')` on `/anomalies` by hardening null-checks and synchronizing data schemas across backend and frontend.
  - Resolved `Uncaught TypeError: Cannot read properties of undefined (reading 'length')` on `/anomalies/:id` by adding defensive optional chaining on `contributors`, `limitations`, `trace_ids`, and timestamp windows.
  - Resolved `TypeError: Cannot read properties of undefined (reading 'map')` on `/services/:name` and `/principals/:name` by adding safe fallback arrays and enriching backend responses with complete operational percentiles and dependency relationships.
- **Automated Test Suite**:
  - 49/49 tests passed via `.venv/bin/python -m pytest -q` using isolated temporary databases; tests never mutate `data/tracescope.db`. Coverage includes the exact old-kernel `/api/ingest` route, complete NetworkTracing field mapping, sparse events with omitted optional fields, and WSSE UsernameToken attribution and secret hygiene.
  - Anomaly time filters, charts, blast radius, related users, trace evidence, sample counts, MAD ranges, and principal metadata filters are verified against telemetry observation windows rather than worker execution time.
  - User behavior scores count each evidence category once; repeated relationship events no longer saturate the score. Accounts without a historical fingerprint are explicitly marked as learning.
  - Frontend lint/type check and production build passed.
  - 37/37 end-to-end curl contract tests passed via `sh backend/scripts/curl_test_all_pages.sh`.
  - 15/15 real browser Playwright tests passed via `python3 backend/scripts/test_pages_playwright.py`.
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
      - `--mode <http|direct>`: Ingestion mode (`http` streams batched POST to `/api/v1/ingest`; `direct` performs batch SQLite write, auto-tuned to 5,000 batch size).
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
