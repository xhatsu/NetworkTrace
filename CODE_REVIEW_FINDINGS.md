
## Coverage

Reviewed the requested first-party scope: 83 backend files, 14 test files, 16 frontend source files, 38 Kubernetes/Helm files, seven bootstrap files, and the root lifecycle/container entrypoints—approximately 26,500 lines. Excluded dependencies, generated output, caches, Markdown documentation, task reports, and the binary `bootstrap/bundle.tar.gz` as directed.

The review was read-only. I did not run tests because the suite creates caches and temporary ClickHouse databases, conflicting with the explicit no-create/no-mutate constraint. Repository status was checked before and after and remained unchanged.

## Findings

### Critical

[critical] ClickHouse’s default expression does not produce unique row IDs — `backend/clickhouse_migrations/001_initial.sql:14`

`traces.id` and `anomaly_events.id` use `toUnixTimestamp64Micro(now64(6))`, which is constant within a multi-row insert block. The ingestion writer inserts up to 50,000 rows together (`backend/app/services/ingest_writer.py:262`), while incremental processing advances solely by `id` in 10,000-row pages (`backend/app/services/principal_relationships.py:423`); rows beyond the first page sharing that ID can therefore be skipped permanently. Anomaly lookup and mutation by ID can also select or update multiple incidents (`backend/app/repositories/anomaly_repository.py:91`). Generate a unique per-row UUID/hash/sequence and use a composite, stable cursor rather than timestamp alone.

[critical] The default Helm deployment exposes privileged internal APIs with a publicly known token — `deploy/helm/tracescope/values.yaml:146`

The chart defaults `internalApiToken` to `change-me-in-production`, places it in a Secret, and the catch-all Ingress sends `/internal/*` to the all-role API (`deploy/helm/tracescope/templates/ingress.yaml:97`). That role mounts the internal storage router (`backend/app/application.py:142`), including normalized-trace commits and agent deletion operations (`backend/app/api/internal_storage.py:41`). A default installation is therefore writable by anyone who knows the published chart value. Require an explicitly supplied random token, reject placeholder values during rendering, and block `/internal` at the public Ingress/network-policy boundary.

### High

[high] SQLite upserts and transactions are silently discarded by the ClickHouse adapter — `backend/app/repositories/db_context.py:169`

The adapter turns `BEGIN`, `COMMIT`, and `ROLLBACK` into no-ops and strips every `ON CONFLICT` clause. Principal aggregation relies on conflict updates to increment request counts (`backend/app/services/principal_relationships.py:65`), while rollups rely on replacement upserts (`backend/app/repositories/aggregate_repository.py:12`). This produces duplicate or count-one rows and exposes unmerged `ReplacingMergeTree` versions to queries that do not use `FINAL` or `argMax`. Replace SQLite-shaped operations with explicit ClickHouse aggregation/versioning semantics instead of silently weakening them.

[high] Batch deduplication can acknowledge permanent trace loss — `backend/app/services/ingest_writer.py:267`

The writer inserts the `ingest_batches` marker before inserting trace rows, but the two inserts are not transactional. If the trace insert fails after the marker succeeds, a retry finds the marker and reports the request as a duplicate without restoring the missing traces (`backend/app/services/ingest_writer.py:251`). Use an idempotent data-first or staging workflow where acceptance cannot become visible before trace persistence succeeds.

[high] Deployment manifests omit the storage-owner URL and bypass the single-writer boundary — `deploy/helm/tracescope/templates/configmap.yaml:8`

Neither Helm nor raw Kubernetes manifests configure `OTEL_STORAGE_OWNER_URL`. Without it, every scaled ingestion pod creates its own local writer (`backend/app/application.py:110`), despite Helm allowing 3–12 ingestion replicas (`deploy/helm/tracescope/values.yaml:78`). Cross-pod requests with the same batch ID can both pass the check-before-insert path and duplicate trace data. Configure the storage-owner service explicitly, remove direct database credentials from edge pods, and validate this invariant in manifest tests.

[high] Gzip payloads are fully expanded before the decompressed-size limit is checked — `backend/app/services/otlp_parser.py:35`

`gzip.decompress(raw_body)` materializes the entire result before comparing it with `max_decompressed_bytes`. A small compression bomb can consume large amounts of memory and terminate an ingestion worker before the intended 413 response. Use incremental decompression with a hard output cap and enforce compressed-body limits at the proxy or ASGI boundary.

[high] Configured API-key protection is bypassed by several mutating routes — `backend/app/api/ingest.py:188`

The generic ingestion route checks `OTEL_API_KEY`, but OTLP/APM ingestion aliases do not. Agent telemetry writes and deletes (`backend/app/api/agent_stats.py:95`), security-policy updates (`backend/app/api/reference_compat.py:440`), and user-review actions (`backend/app/api/users.py:147`) are also unprotected. Apply authentication as a router-wide dependency or central mutation policy, with tests covering every non-GET route.

[high] Detector baselines and current service measurements use incompatible aggregation grains — `backend/app/services/baseline.py:31`

Service baselines append each individual caller/principal/operation bucket to the service sample set rather than summing all dimensions for each time window. Detection later sums current request and error counts across dimensions before comparing them with those per-dimension baselines (`backend/app/services/anomaly_detection.py:29`). Services with many dimensions can consequently generate systematic false spikes and error anomalies. Aggregate historical data to one service/window sample before calculating medians and MAD.

[high] Direct trace import writes and analyzes different ClickHouse databases — `backend/scripts/send_traces.py:173`

Direct mode passes the legacy path `data/tracescope.db`, which the compatibility layer hashes into a test database (`backend/app/repositories/db_context.py:328`). It then runs aggregation without that database argument (`backend/scripts/send_traces.py:239`), causing production and hashed-test databases to be mixed during one import. Replace the legacy path with one explicit ClickHouse database setting and propagate it through every repository and analytics stage.

[high] SPA fallback permits filesystem traversal if dot segments reach ASGI unchanged — `backend/app/application.py:383`

The catch-all route joins attacker-controlled `full_path` directly to `frontend_dist` and serves any resulting file, without resolving the path and checking containment. A raw or encoded traversal path that survives an upstream proxy can expose any readable file outside the frontend directory. Resolve both paths and require the candidate to be relative to the resolved distribution directory; add direct ASGI tests for encoded traversal variants.

[high] Bootstrap installation executes unauthenticated network content as root — `bootstrap/nt-bootstrap.py:127`

The generated installer downloads a bundle over plain HTTP, extracts it, and executes its installer without a signature or pinned digest. The download host is derived from an unvalidated HTTP `Host` header (`bootstrap/nt-bootstrap.py:321`) and interpolated into generated shell text. A network intermediary or hostile host value can replace or inject commands into a root-level installation. Require authenticated transport plus a pinned signature/digest and strictly validate and shell-quote the download authority.

### Medium

[medium] Helm’s ClickHouse password is wired under the wrong environment name — `deploy/helm/tracescope/templates/secret.yaml:9`

The Secret exports `CLICKHOUSE_PASSWORD`, while application configuration reads `OTEL_CLICKHOUSE_PASSWORD` (`backend/config.py:17`). The ClickHouse StatefulSet also does not consume the configured password (`deploy/helm/tracescope/templates/clickhouse-statefulset.yaml:42`). Non-empty password configuration is therefore ignored or causes mismatched authentication. Use explicit `secretKeyRef` mappings for both server and clients with the exact expected names.

[medium] Global time filters are ignored or omitted across major pages — `frontend/src/api.ts:3`

The frontend emits `start` and `end`, but topology, anomaly, and service APIs accept `from` and `to` (`backend/app/api/topology.py:23`, `backend/app/api/anomalies.py:116`, `backend/app/api/services.py:79`). Trace and principal queries omit the global filter altogether (`frontend/src/pages/Traces.tsx:49`, `frontend/src/pages/Principals.tsx:51`). Users therefore see data outside the selected time interval. Standardize parameter names and include the time range in every relevant request and query key.

[medium] Mutation row counts are fabricated, breaking not-found behavior — `backend/app/repositories/db_context.py:256`

Every successful command receives `rowcount = 1` and increments `total_changes`, regardless of whether a ClickHouse mutation matched any row. Anomaly updates therefore report success for nonexistent IDs (`backend/app/repositories/anomaly_repository.py:105`), preventing the API’s intended 404 (`backend/app/api/anomalies.py:213`). Perform an existence check or obtain an authoritative mutation result rather than simulating SQLite counters.

[medium] Synchronous ClickHouse operations run directly inside async handlers — `backend/app/api/services.py:24`

Async endpoints execute blocking `clickhouse_connect` queries on the event-loop thread; readiness (`backend/app/application.py:169`) and agent ingestion (`backend/app/api/agent_stats.py:95`) have the same pattern. Slow database calls can stall unrelated requests and health probes within that worker. Convert blocking handlers to synchronous FastAPI endpoints or move repository work to a threadpool/async driver.

[medium] Agent history retention is declared but never enforced — `backend/app/repositories/agent_stats_repository.py:14`

`_HISTORY_KEEP_PER_NODE = 2880` is unused, and the upsert path only appends history (`backend/app/repositories/agent_stats_repository.py:122`). The ClickHouse table has no TTL or bounded-retention mechanism. Long-running fleets will accumulate unbounded telemetry despite the documented 24-hour limit. Add a table TTL or periodic partition-aware pruning.

[medium] Trace pagination accepts unbounded and invalid limits — `backend/app/api/traces.py:9`

`limit` and `offset` are unconstrained integers and are interpolated into a `SELECT *` query after integer conversion (`backend/app/repositories/trace_repository.py:59`). Huge limits can cause excessive database and application memory use, while negative values produce database errors instead of validation responses. Use bounded `Query` constraints and preferably cursor-based pagination.

[medium] The hardened container cannot persist security-policy changes — `backend/app/api/reference_compat.py:22`

Policy GET/POST writes `policy.json` under the configured data directory, but Helm uses a read-only root filesystem and mounts only `/tmp` as writable (`deploy/helm/tracescope/templates/storage-statefulset.yaml:107`). Updates can fail or disappear across restarts, and would not be coherent across replicas. Store policy in ClickHouse or another shared durable store and avoid writes during GET requests.

[medium] Current Helm chart defaults deploy previous-version application images — `deploy/helm/tracescope/values.yaml:50`

The chart and `appVersion` are `0.2.0`, while default API, ingest, agent, and UI tags remain `0.1.0`. A fresh default installation can deploy binaries that do not match current templates and configuration assumptions. Derive default tags from `Chart.appVersion` or update every image tag atomically with the chart release.

### Low

[low] Exact percentile calculation underreports small samples — `backend/app/services/aggregation.py:11`

The index uses `int((n - 1) * q)`, so p95 and p99 of two observations return the smaller value. This can hide tail latency in low-volume buckets. Use a documented percentile definition such as nearest-rank or interpolation and test one-, two-, and three-value inputs.

[low] Nullable service metadata can crash frontend filtering — `frontend/src/pages/Services.tsx:57`

The schema permits null `service_group` and `module`, while backend defaults only missing keys—not explicitly null values (`backend/app/api/services.py:58`). The search code then calls `.toLowerCase()` directly. Normalize nulls to strings in the API and retain defensive frontend coercion.

[low] Malformed trace attributes can crash the detail page — `frontend/src/pages/Traces.tsx:393`

Trace rendering performs an unconditional `JSON.parse(span.attributes)`. One corrupt or legacy value throws during React rendering and can take down the trace-detail view. Parse defensively and show the original value or an “invalid attributes” state.

## Test gaps

- No test verifies uniqueness of IDs across a multi-row ClickHouse insert or cursor pagination through more than 10,000 equal-timestamp rows.
- Batch-dedup tests do not inject failure between marker insertion and trace insertion.
- Deployment validation does not assert the storage-owner URL, internal-route isolation, or absence of default credentials.
- Authentication tests do not enumerate every mutating public endpoint.
- Gzip tests cover malformed input but not bounded streaming decompression or high compression ratios.
- Analytics tests do not compare service baselines and current metrics at identical dimensional grain.
- No direct-ASGI traversal tests cover raw and percent-encoded dot segments.
- Frontend/API contract tests do not verify that global time filters alter returned data.
- Agent-stat tests do not prove physical history retention.
- Percentile tests omit very small sample sizes.
- No installation test verifies ClickHouse password propagation or that default chart image versions match the chart.

## Verdict

Do not release the current build. The shared-ID behavior can permanently skip data, and the default Helm topology exposes privileged internal writes with a known credential. The non-transactional dedup flow, silently discarded ClickHouse upserts, missing storage-owner routing, and authentication/decompression weaknesses also present substantial data-integrity and security risk; these should be corrected and covered by focused failure-injection and deployment tests before release.