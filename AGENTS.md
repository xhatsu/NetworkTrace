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
- **Current Database**: `data/tracescope.db` (SQLite in WAL mode; existing observability tables plus additive normalized principal relationship, activity, baseline, and change-event tables).
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
    - User Intelligence: `/api/v1/users` inventory/profile subresources, `/api/v1/user-changes`, `/api/v1/user-graph`, `/api/v1/user-analytics`, plus service/anomaly related-user endpoints.
    - `POST /api/v1/ingest`, compatibility alias `POST /api/v1/ingest/traces`, and old-kernel shipper alias `POST /api/ingest`: bounded OTEL/ELK or NetworkTracing `{node, events[]}` ingestion with credential sanitization and safe defaults for missing legacy fields.
    - Legacy aliases: `/api/v1/accounts`, `/api/v1/dashboard/summary`, `/api/v1/dashboard/series`, `/api/v1/events`, `/api/v1/ingestion/status`.
- **Domain Models** (`backend/app/models/`):
  - `trace.py`: `NormalizedTrace`.
  - `aggregate.py`: `MetricBucket`.
  - `baseline.py`: `BaselineMetric`.
  - `topology.py`: `ServiceEdge`, `PrincipalServiceEdge`, `TopologyNode`, `TopologyEdge`.
  - `anomaly.py`: `AnomalyEvent`, `AnomalyReason`.
- **Repository Layer** (`backend/app/repositories/`):
  - `db_context.py`: SQLite connection context with WAL mode and 5s busy timeout.
  - `trace_repository.py`: Normalized trace batch insert, query, and search.
  - `aggregate_repository.py`: Rollup storage, time-series query, KPI summaries.
  - `topology_repository.py`: Edge materialization, topology graph generation, caller/dependency traversal.
  - `baseline_repository.py`: Baseline storage and retrieval by hour-of-day/day-of-week.
  - `anomaly_repository.py`: Anomaly event querying, lifecycle patching (open, investigating, resolved, suppressed).
  - `principal_repository.py`: Principal rankings and comprehensive behavioral profiling.
  - `user_repository.py`: User inventory, fingerprint profiles, timelines, explainable changes, graph, analytics, and observability cross-links.
- **Analytics & Detection Services** (`backend/app/services/`):
  - `normalization.py`: Normalizes OTel / ELK payloads, focuses on header-derived accounts (`Authorization: Basic`), discards passwords in-memory (non-header fallbacks commented out for later).
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
- **Design System**: Linear/Sentry developer aesthetic.
  - Canvas: `#08090a`, `#0e1116` panels, whisper-thin borders `rgba(255,255,255,0.07)`.
  - Inter typography + JetBrains Mono for metrics and percentiles.
  - Semantic status tokens: Emerald (`#10b981`), Amber (`#f59e0b`), Rose (`#f43f5e`), Indigo (`#6366f1`).
- **Built Output**: `frontend/dist` served directly by FastAPI on port 30102.
- **Navigation & Pages**:
  - `Overview` (`/`): Estate health KPIs, comparative traffic & latency series, open anomalies list, top services & principals.
  - `Topology` (`/topology`): Interactive canvas graph with Edge Inspector drawer (showing top principals and top operations per edge).
  - `Anomalies` (`/anomalies`, `/anomalies/:id`): Incident list and Anomaly Detail with "WHAT CHANGED COMPARED WITH NORMAL?" explainability card, probable root cause, blast radius, and lifecycle action controls.
  - `Services` (`/services`, `/services/:name`): Service catalog, operation percentiles, caller graphs, instances.
  - `Principals` (`/principals`, `/principals/:name`): Identity behavior explorer, target services, operations, callers, and hourly activity profiles.
  - `Traces` (`/traces`, `/traces/:id`): Trace explorer with filters and multi-tier interactive waterfall visualization.
  - `User Intelligence`: `Users` (`/users`, `/users/:principal`), `User Changes` (`/user-changes`), `User Graph` (`/user-graph`), and `User Analytics` (`/user-analytics`). Existing pages retain their service-centric workflows and expose contextual user cross-links.
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
- **Test Suite**: 49/49 tests passed in an isolated temporary-database harness; production data is never mutated by tests, including full and sparse NetworkTracing old-kernel ingestion coverage and WSSE UsernameToken extraction.
  - Unit & domain tests in `tests/test_analytics.py`, `tests/test_api.py`, `tests/test_ingestion.py`.
  - Comprehensive behavioral API tests in `tests/test_behavioral_api.py`.
- **End-to-End Curl & JS Safety Test Suite**: 37/37 tests passed (`sh backend/scripts/curl_test_all_pages.sh`).
  - Tested all 15 SPA routes, including all User Intelligence routes, with HTTP 200 and valid HTML shell bundle delivery.
  - Tested 22 backing APIs against frontend TypeScript contracts via `backend/scripts/validate_js_safety.py`.
  - 0 JavaScript crash risks identified (zero undefined `toFixed`, `length`, or `map` vulnerabilities).
- **Frontend Lint/Build**: Passed (`tsc --noEmit -p tsconfig.app.json` and `tsc -b && vite build`).
  - Added defensive optional chaining and fallback arrays across `Overview.tsx`, `Services.tsx`, `Principals.tsx`, `Anomalies.tsx`, and `Traces.tsx`.
  - Harmonized `backend/app/api/services.py` and `backend/app/api/principals.py` to supply full operational and hourly profiles.
- **Playwright Real Browser E2E Suite**: 15/15 pages passed (`python3 backend/scripts/test_pages_playwright.py`).
  - Headless Chromium navigated to all 15 existing and User Intelligence SPA routes.
  - Full React hydration, query resolution, and visual canvas/chart rendering verified.
  - 0 unhandled `pageerror` exceptions, 0 React render crash boundaries, and 0 console error failures.
- **Port 30102 Status**: Online and healthy, listening on all interfaces (`http://0.0.0.0:30102`).
- **Database Status**: Clean wiped state. SQLite `quick_check` passes (`[('ok',)]`). All 29 tables initialized fresh and empty (0 traces, 0 anomalies, 0 buckets). Server and worker restarted on port 30102, ready for clean dataset ingestion.
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
- **Reference**: Refer to `STATE.md` for full endpoints, features, and run guides.
