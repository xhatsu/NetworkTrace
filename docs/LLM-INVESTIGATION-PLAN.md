# LLM investigation of an existing abnormal finding

Planner deliverable, 2026-09-16. Implementation handoff: Codex Luna max. This document is the only planner change. The inspected checkout is HEAD `4a93014`, with substantial pre-existing tracked and untracked changes. Those changes are inputs, not changes attributable to this task.

## 1. Decision and scope

Build an explicit-request, API-only vertical slice: resolve one existing finding and capture its version → persist a queued investigation → assemble bounded evidence → request one structured relay response → validate → persist the result → retrieve status/result. Run the queue in the `all` application's lifespan, independently of analytics. A deterministic evidence summary remains available when the provider fails. No automatic launch, periodic finding scan, detector hook, generic chat, model-controlled evidence loop, or remediation execution.

The three supported sources are `anomaly_events`, `principal_change_events`, and `incidents`. An investigation cannot exist without a successfully resolved source and immutable snapshot. The LLM neither discovers findings nor classifies requests as malicious. It cannot create findings/incidents, change scores/severities/types, suppress contributions, update review state, or substitute a successor incident. It adds clearly labeled hypotheses and correlations to the original finding.

**MCP decision: INTERNAL.** A small internal typed evidence adapter suffices. The FastAPI process already has the relevant repository access; no external MCP consumer or MCP implementation was found in the inspected repository. A separate server would add credentials, routing, and authorization surfaces without helping this bounded request. The contracts below are internal Python/Pydantic contracts, not publicly callable tools. No MCP dependency, server, resources, or deployment is needed.

Use an injected `LLMProvider` interface with an HTTP adapter for the user's OpenAI-compatible relay. No application relay adapter/configuration was found in `backend/`, `frontend/src`, or the inspected tool/document context. The relay's endpoint, credentials, model availability, and schema-mode capability are **unverified operator inputs**; do not infer them from the coding agent's own connection. No `.env` or secret configuration is needed to implement and test with a fake relay.

The first release supports **one explicitly designated `all` API process on one replica** as investigation owner. This is a deliberate operational limit, not a distributed queue claim. Ingest and agent-stats roles cannot run or expose investigations. Multi-replica ownership, provider fan-out, automated launches, and a UI are deferred beyond this allowlist.

## 2. Grounding in actual interfaces

| Existing file / symbol | Verified behavior and implication |
|---|---|
| `backend/app/application.py:create_app`, `_ANALYTICS_ROUTERS`, `lifespan` | Roles are `all`, `ingest`, `agent-stats`; only `all` mounts analytics. Lifespan already owns writer startup/shutdown. Add a separate investigation lifecycle without coupling health/readiness or ingestion to provider availability. |
| `backend/app/security.py:require_api_key`; application mutation middleware | Authentication is optional when `OTEL_API_KEY` is empty; GETs are currently public. New investigation routes must fail closed without a configured key and require authentication for reads as well as writes. Existing routes stay unchanged. |
| `backend/app/repositories/anomaly_repository.py:get_anomaly` (113), `deterministic_anomaly_id` (10) | Reads `anomaly_events FINAL`; ID is an unsigned 64-bit hash. Return IDs as decimal **strings** in the new API to avoid JavaScript integer loss. Model facts include score, severity, confidence, reasons, baseline/current/delta and observation bounds. |
| `backend/app/api/anomalies.py:_observed_bounds`, `_enrich_evidence`, `get_anomaly_detail` | Detail adds present-day baseline queries, ClickHouse-only trace IDs, and synthetic training/window fields. Do not snapshot this enriched response as historical truth. Load the source record directly. |
| `backend/app/repositories/user_repository.py:list_changes` (231), `timeline` (215) | `list_changes` can return recent rows outside an empty requested interval; timeline includes ClickHouse-only traces. Neither is a strict investigation evidence reader. There is no direct single-change GET/read method. |
| `backend/app/repositories/user_repository.py:get_incident` (370) | Reads `incidents FINAL` then all associated change events without a LIMIT. Read the incident header directly and fetch bounded contributing rows separately. |
| `backend/app/api/users.py` | Owns `/incidents`, `/incidents/{incident_id}`, `/user-changes`, `/user-changes/{change_id}/review`, and `/users/{principal}/investigations`. There is no `backend/app/api/incidents.py`. |
| `backend/app/repositories/user_repository.py:investigations` (786) | Existing deterministic view ignores the supplied window for incident selection, builds triggers, and includes fallback trigger prose. It is not LLM persistence or authoritative source evidence. |
| `backend/app/repositories/trace_repository.py:TraceRepository.list_traces/get_trace` | Delegates to ES when configured, then silently falls back to ClickHouse on empty/error. No environment argument, no explicit backend provenance; detail loads up to 1,000 spans. Do not inherit this silent fallback. |
| `backend/app/repositories/elasticsearch_trace_repository.py:is_configured`, `list_traces` | ES is selected by backend setting **or URL presence**. Search uses bounded time/term filters, normalizes hits via `normalize_otel_record`, but may return raw `_source` on normalization failure and logs response text on errors. New investigation reader must drop normalization failures and avoid raw error logging. |
| `backend/app/repositories/aggregate_repository.py:query_series` (34) | Seconds in, grouped rollups out; `error_rate` is a fraction and `latency_p95` is MAX of bucket percentiles. Do not describe that as a true combined percentile. |
| `backend/app/services/blast_radius.py:calculate_blast_radius`; `topology_repository.py:get_service_dependencies` | Existing queries have no sufficient result/resource caps for tool use. Reuse their query meaning in a bounded reader, not an uncapped invocation followed by slicing. |
| `backend/clickhouse_migrations/001_initial.sql` | Change rows replace by `fingerprint`, incidents by `incident_id`. Neither has database CAS/transaction ownership. Quality rows are global windows, not per-principal measurements. |
| `backend/app/repositories/db_context.py:execute`, `db_transaction` | DB-API translation is not a transactional database; explicit transactions unsupported. `execute` exposes no per-query settings argument, but the connection has a native `client`. New bounded readers use parameterized native queries with settings locally. Do not refactor this adapter. |
| `backend/app/repositories/clickhouse_migrator.py:run_clickhouse_migrations` | Discovers sorted `*.sql`; current last migration is `006_principal_readiness_summary.sql`. New migration is `007_llm_investigations.sql`; no migrator edit required. |
| `backend/worker.py:run_jobs` (149); `anomaly_detection.py` (61–80); `behavioral_engine.py:EVENT_SCORES`, `FAMILY_CAPS`, `recalculate_incident_score` | Current pipeline is deterministic, service detector uses 300-second buckets. No LLM/ML stage or ML dependency in `backend/requirements.txt`. Leave the pipeline and point tables untouched. |
| `frontend/src/pages/Anomalies.tsx:AnomalyDetailPage`; `frontend/src/pages/user/UserInvestigationsTab.tsx`; `frontend/src/pages/UserIntelligence.tsx` | Future insertion points exist, but the workspace tab has an unrelated review-route mismatch and the shared `frontend/src/api.ts:api` has no built-in API-key flow. API-only avoids expanding into browser credential design or unrelated UI repairs. |
| `tests/conftest.py` | Uses actual ClickHouse test databases, not SQLite. Shutdown drops **all** databases beginning `test_`; migrations can also affect server system-log settings. Run acceptance only against a disposable server dedicated to this suite. |

Read-only live checks on `http://127.0.0.1:30102` returned HTTP 200 for health, OpenAPI, and limit-one anomaly/incident/change lists; `/api/v1/anomalies/0` returned 404. OpenAPI confirmed the routes above and no LLM route. Inspected response **keys**, not raw telemetry exports. The earlier counts in `docs/ABNORMAL-SCORING.md`, `docs/ML-BEHAVIORAL-TARGET-VS-CURRENT.md`, and `STATE.md` are historical observations, never acceptance constants. Those two design documents supply scoring/ML context; their proposed ML implementation is not part of this task.

## 3. Finding identity, snapshot, and lifecycle

Create Pydantic v2 strict models with `extra='forbid'`. All timestamps in new JSON are integer UTC epoch milliseconds; repository conversions to seconds are explicit. Reject floats/bools for IDs/timestamps, invalid UTF-8/control characters, unknown fields, NaN and infinity. Numeric source IDs arrive as strings matching `[1-9][0-9]{0,19}` and must fit UInt64; incident IDs are opaque strings of 1–128 characters, never interpreted as paths.

`FindingRef` is a discriminated union with **exactly one** source ID:

```json
{"kind":"anomaly_event","anomaly_event_id":"123"}
{"kind":"principal_change_event","principal_change_event_id":"456"}
{"kind":"incident","incident_id":"opaque-id"}
```

`FindingSnapshot` fields: `ref`, `source_version`, `snapshot_schema_version` (`finding-v1`), `captured_at_ms`, `source_updated_at_ms` (nullable), `observation_window` (`start_ms`, `end_ms`, `basis`, nullable when unknown), `dimensions`, `source_facts`, `source_status`, `successor_ref` (nullable), `redacted_fields`, `limitations`. Dimensions include only actual caller/target/principal/operation/source-IP/environment fields; absent environment stays unknown. Source facts preserve the original score, severity or priority, type/category, source confidence, baseline/current/delta, reason contributions, family scores, suppressed contributions, and contributing source IDs where present. Never synthesize severity for an incident or confidence for a change.

Build a canonical structured projection of the source row, parsing JSON with bounded size/depth and preserving scalar types. Canonical JSON uses sorted keys, compact separators, UTF-8 and no non-finite numbers. `source_version = sha256(canonical protected source projection)`; exclude read time and dynamic UI enrichments, include lifecycle fields and `updated_at` where present. Include contributing IDs in stable sorted order. Hash only sanitized fields; never hash credentials/raw bodies. Human review notes and arbitrary metadata are omitted entirely; `reviewed_at`, status and available update timestamps capture review state. Keep a versioned allowlist of evidence-bearing metadata keys, not arbitrary attribute passthrough. Document that this is a content version of the investigation-relevant source projection, not a database-wide revision.

Persist the immutable sanitized snapshot in the first investigation row and carry its exact bytes through later states. Maximum snapshot 64 KiB. Reject an oversized source with `source_too_large` before provider work rather than truncating authoritative facts. Free-text evidence is untrusted and length-bounded; keep required deterministic numeric fields unchanged. Reject malformed protected facts with `invalid_source`, never replace them with zeros. Read source rows using `FINAL`, exact ID and `LIMIT 2`; reject ambiguous change IDs associated with different fingerprints.

`GET /api/v1/investigations/source` obtains a snapshot/version for the client. `POST` requires that version and rereads the source. Recheck at dequeue, after evidence assembly, and immediately before publishing the result. On mismatch, persist `source_changed` with expected/current versions; never switch sources. Reads also return a fresh `source_check` so an old successful result remains visibly tied to its prior version. ClickHouse provides no cross-table snapshot isolation: record each evidence read time, and expose `checked_at_ms` for the source check; do not claim transactional simultaneity.

Eligibility is deterministic:

- Anomalies: active `open`, `acknowledged`, `investigating`; inactive `resolved`, `suppressed`, `ignored`.
- Changes: active `new`, `reviewed`; inactive `expected`, `ignored`, `resolved`, `suppressed`. Unknown statuses are ineligible until explicitly supported.
- Incidents: active `open`, `investigating`, and `closed_at` null; any successor means `superseded`, never follow it. Other statuses, including `accepted`, are inactive.
- Stale means last observed time older than 30 days (fixed v1 admission policy). Use anomaly `last_seen`, change `detected_at`, incident `last_seen_at`; fall back to anomaly `detected_at` only for age admission, not a fabricated observation interval. Historical closed/stale results remain retrievable; new generation is refused. Missing temporal/entity scope returns `insufficient_scope`.
- Initial POST for an already investigated identical version/configuration returns the existing investigation with `reused=true`. A changed version needs a new source fetch and explicit POST. Source closure/version mismatch wins over reusing a result and returns the existing result ID in the conflict if present.

## 4. Public API and execution ownership

New router prefix `/api/v1/investigations`, mounted only on `ROLE_ALL` before SPA fallback. No changes to existing finding responses.

| Method/path | Strict contract |
|---|---|
| `GET /source?kind=...&id=...` | Returns `{snapshot, eligibility:{status,reason}, latest_investigation_id}`; 404 unknown source. One exact source only. |
| `POST /` (register without trailing-slash ambiguity) | Body `{finding:FindingRef, source_version:hex64, retry_of:uuid|null}`; 16 KiB request limit. Returns 202 `{id,status,reused:false,source_version,status_url}` only after durable queue insertion; existing ID returns 200 with `reused:true`. No user prompt, arbitrary filters, model, URL or time range. |
| `GET /{id}` | Returns metadata, snapshot, evidence manifest, deterministic summary, validated result or null, failure code, and `source_check:{status,current_version,checked_at_ms}`. Missing source at read time is explicit. Never reruns work. |
| `GET /?kind=...&id=...&limit=...` | Finding-required history, limit 1–10, default 5; bounded latest summaries. No global telemetry or investigation scan endpoint. |
| `POST /{id}/cancel` | Idempotent cancellation; 202 while running, 200 if already canceled/terminal, with actual status. Successful completed results are never rewritten as canceled. |

`GET /source` must precede `GET /{id}` in router registration. All routes require `X-API-Key` via a new local dependency using the existing comparison semantics, **plus** a nonempty configured `OTEL_API_KEY`; configuration missing → 503, wrong/missing key → 401. Feature disabled → 404. No API key in OpenAPI defaults, browser assets, logs, or persisted requester labels. Existing global-key authorization means one trusted operator security domain, not tenant RBAC. No public/multi-tenant rollout without a separately designed identity/authorization boundary. Environment-qualified evidence still prevents accidental cross-environment correlation.

Errors use `{detail:{code,message,expected_version?,current_version?,existing_investigation_id?}}`, with sanitized fixed messages. Codes: 422 malformed source ref/version, 404 unknown source/run, 409 `source_changed|source_closed|source_superseded|source_stale|insufficient_scope|retry_not_allowed`, 422 `invalid_source|source_too_large`, 429 capacity/rate limit with `Retry-After: 1`, 503 owner/store unavailable. Provider failure is a persisted investigation outcome, not a failure of a finding API.

`InvestigationRunner.start()/submit()/cancel()/shutdown()` runs one asynchronous consumer, queue capacity 16, provider concurrency 1. A single process-wide admission/state lock serializes dedup, queue reservation, durable insert and cancellation. Cap new submissions at 6/minute and 100/day for the shared operator domain; consult persisted admissions on startup so restart does not reset spend limits. Reserve capacity before inserting; release on failed admission. HTTP client disconnect after 202 does not cancel a run.

Enable only on the designated single-replica, single-worker `all` process. Acquire a lifetime OS advisory lock at `settings.data_dir / 'llm-investigator.lock'`; second process on that filesystem refuses ownership. This lock does **not** coordinate separate pod filesystems. Require explicit single-owner configuration acknowledgement; reject edge roles and `storage_owner_url` proxy configurations for this release. Operators must keep other replicas feature-disabled; do not claim database uniqueness/fencing across misconfigured hosts. Horizontal ownership requires a future coordinator, outside this slice.

Run key = SHA-256 of source kind/ID/version + policy/prompt/output-schema versions + configured provider/model + retry index. Convert to a deterministic UUID using UUIDv5; store full dedup hash too. Under the owner lock, look up before insertion. First run index 0. A retry requires `retry_of` pointing to the same version's most recent terminal `failed|timed_out|canceled` run, never successful or source-invalidated work; derive next index server-side, maximum 2 retries (3 total). Repeated retry POSTs for the same parent return the same child. No arbitrary nonce to bypass dedup/rate limits.

States: `queued → assembling → generating → validating → succeeded`; nonterminal states may become `failed|timed_out|canceled|source_changed|source_closed|source_superseded|source_stale`. `cancel_requested` is a persisted flag, not a detector lifecycle. Total deadline 90 seconds from durable admission, including queue wait; evidence deadline 15 seconds, per-store query 2 seconds, provider budget 45 seconds including at most one repair. Queue-expired requests time out before provider use. Shutdown stops admissions, cancels active work, and persists terminal interrupted state within 5 seconds where storage permits.

Before accepting work on startup, recover old nonterminal rows as `failed/owner_interrupted`, without automatic provider replay. Recover in 100-row pages under bounded queries until complete; failure to finish keeps admissions disabled but does not fail the base app. Unknown INSERT outcome: query deterministic ID before acknowledging or retrying identical row. Failed terminal persistence makes retrieval show the last durable state; if its deadline is past, expose `effective_status=interrupted` and recover under the owner. Never return an undurable successful result. A late provider response after cancellation/deadline is discarded under the state lock.

## 5. Bounded evidence contract

Create `InvestigationEvidenceRepository` and `EvidenceAssembler.assemble(snapshot, context) -> EvidenceBundle`. They are the sole evidence access path. `InvestigationContext` is server-created from a validated snapshot and authenticated request, carries deadline/query budget/entity scope, and cannot be supplied by the model or arbitrary API JSON.

Every adapter request is `{context_id:uuid, finding_version:hex64, window:"focus"|"surrounding"|"history", limit:int}` plus only the tool-specific field in the table. `finding` takes only context ID/version. Reject extra properties, cross-context IDs, negative/oversized limits and unauthorized dimensions. Exact entity values, source environment, times, backend URLs and query text are all resolved server-side. The LLM receives results only; these tools are **not advertised for model invocation** in v1.

Common output:

```json
{
  "tool":"related_traces", "schema_version":"evidence-v1",
  "finding_version":"<sha256>", "window":{"start_ms":0,"end_ms":300000},
  "backend":"elasticsearch", "queried_at_ms":300001,
  "items":[{"evidence_id":"e0001","source":{"kind":"trace","id":"trace/span","version":"<sanitized-row-hash>","timestamp_ms":1000},"data":{"duration_ms":12}}],
  "returned":1, "partial":false, "unavailable_reason":null, "limitations":[]
}
```

The example shows the envelope; each `data` object is a typed union defined below, never arbitrary JSON. Source timestamp may be null only for a timeless baseline, with explicit retrieval-time provenance. Evidence IDs are unique within the frozen bundle; source IDs remain actual source identifiers, including ES `_index/_id` internally where available. Final bundle has a SHA-256 digest over canonical sanitized content and no raw Authorization, cookies, SOAP, bodies, headers, tokens, or arbitrary trace attributes.

| Internal tool | Window/limits and concrete typed `data` |
|---|---|
| `finding` | Exact pinned snapshot only, no query beyond version verification. Data = `FindingSnapshot`; incident contributing IDs/family scores stay authoritative. |
| `related_changes` | `focus` or `surrounding`; ≤20 rows, ordered detected time then ID. Data: ID string, fingerprint, principal ID/name, environment, type, score, severity, status, caller/target/operation/source IP, old/new value (sanitized), first_observed/detected_at/updated_at, reliability, bounded parsed reason facts. Exact principal/environment or exact service for a service finding; incident members from pinned contributing IDs and matching incident ID. Label nonmembers as surrounding correlations, not contributions. |
| `related_traces` | ≤20 spans, one sample query, no offset or pagination; optional `selection:"recent"|"errors"`, default recent. Data: event UID, trace/span/parent IDs, timestamp, principal/environment, caller/target, operation key, HTTP status, outcome, duration_ms, auth_result and structured attribution confidence/trust fields. No URL query string, raw attributes or bodies. Error selection is pre-existing HTTP/outcome filtering, not maliciousness classification. |
| `window_metrics` | `focus`/`surrounding`; `bucket_size:60|300`, ≤90 rows per call. Data: bucket_start_ms, bucket_size_sec, request_count, error_count, error_rate_fraction, rps, latency_avg_ms, max_bucket_p95_ms, observed_bucket_count. Group by time with exact finding dimensions. Null coverage is not zero traffic. |
| `attached_baseline` | ≤10 relevant values from source reason/baseline facts, with source snapshot IDs. Optional current baseline lookup by exact dimension/hour/day in `baseline_metrics` or `principal_baselines`, explicitly `reference_as_of_read`, never presented as the detection-time baseline. Data: dimension, metric, value, median/MAD/sample_count nullable, hour/day nullable, provenance. No feature-vector builder or scoring. |
| `principal_history` | `history`, ≤24 daily rows from `principal_daily_stats` for exact principal, plus ≤20 prior changes within the history cap if query budget permits. Daily data maps `day_start` → `day_start_ms`, `observation_count` → `observations`, `error_count` → `errors`, and `unique_callers/unique_sources/unique_targets/unique_operations` unchanged. Observations are not necessarily deduplicated requests. Legacy name-only aggregates are `environment_unqualified`; omit when environment separation is required. Never call unbounded `profile`/`timeline`. |
| `service_context` | `surrounding`, depth **1**, ≤10 callers and ≤10 targets, ≤10 affected principals/operations each; use bounded `metric_buckets FINAL` grouped queries. Data: caller, target, request_count, error_rate_fraction, operation/principal optional. Correlation graph, not proven causal blast radius. If query budget exhausted, omit optional affected sets. |
| `data_quality` | `focus`/`surrounding`, ≤90 `telemetry_quality_windows FINAL` rows: start/end, total_spans, counted_requests, linkage/extraction rates, collection_gap, sampling_ratio, created_at. Explicit `scope:"global"`; do not attribute global values to a principal. |

Time policy: focus is anomaly `first_seen..last_seen` when known, a change's containing 15-minute bucket (marked `inferred_15m_bucket`, not exact measured interval), or incident `started_at..last_seen_at`. Convert equal endpoints to a 1 ms selection interval with a recorded limitation. Focus queries cover at most 60 minutes; for longer incidents sample the **final** 60 minutes, expose original full bounds and `partial=true`. Surrounding window adds 15 minutes on each side, maximum 90 minutes. History is the preceding 7 days ending at focus start; never includes future or unrelated users. No synthetic anomaly training interval. Unknown anomaly observation bounds yield finding-only information from the source endpoint and `insufficient_scope` on new admission; do not use “now” to investigate a different window. A valid scoped finding whose bounded evidence queries fail can still produce an insufficient-evidence assessment.

Entity policy: retain every present exact source dimension for trace selection. Incident principal ID/environment is mandatory; targets/callers derive from validated member changes (maximum 10 distinct dimensions) rather than parsing arbitrary prose `scope`. A service anomaly without a principal may correlate that service's bounded callers/principals, with the service link explicit. Name-only data must not silently merge environments. If environment cannot be established, report unknown scope and omit environment-sensitive correlations; do not invent `production` for an anomaly lacking it. IP is supporting attribution evidence, never proof of the user's physical origin; preserve proxy/LB ambiguity from deterministic attribution.

Store selection: copy the current `is_configured` decision (backend ES/ELK or URL present) into the investigation reader using injected settings, then issue a single bounded query against that selected store. In configured ES mode, empty is empty and errors are missing evidence; **no automatic ClickHouse fallback**. With no ES configured, use ClickHouse. Analytics/finding persistence stays in ClickHouse. Record backend on every result so partial OTel vs agent coverage is visible. Never copy application trace rows to ClickHouse.

Implement fixed native ClickHouse SELECT templates inside the new repository using `get_connection(...).client.query(..., parameters=..., settings=...)`. Bind values, hardcode column/table allowlists, use `FINAL` on replacing tables, and apply `max_execution_time=2`, `max_rows_to_read=100000`, `max_result_rows=1000`, `max_memory_usage=67108864`, overflow mode `throw`. Catch resource-limit failures as unavailable evidence; do not return a truncated query as complete. Per-run at most 12 store queries including optional tools; source version checks/admission get a separate cap of 6 exact lookups. Queries run in a dedicated executor with at most 2 threads so a hung read cannot exhaust ingestion's threadpool. Set transport timeouts on dedicated clients; a coroutine timeout alone does not kill a synchronous DB query.

Implement ES search locally in the new reader with existing field mappings/`normalize_otel_record` as reference: range filter, exact dimension terms, `_source` allowlist, size ≤20, no `match_all`, no scripting, `track_total_hits:false`, server timeout 2s, client timeout ≤3s, HTTP body read cap 128 KiB. Drop unnormalizable hits; never send raw `_source`. Enforce environment and exact-ID predicates before and after normalization. Response hit IDs plus normalized span IDs provide citations; response errors become fixed codes, not raw response text. Fixing generic ES/repository behavior is outside this task.

Evidence bundle ≤128 KiB, ≤200 items total, strings ≤512 characters, maximum nesting 6. Prune optional evidence in fixed order (history, optional affected entities, surrounding samples) with explicit omissions; never truncate source facts to fit. Reduce prompt further to ≤24 KiB serialized UTF-8 after fixed instructions to fit the relay's required input budget; record omitted evidence IDs/counts. If the protected snapshot alone exceeds that prompt cap, persist `failed/prompt_budget_exceeded` with a deterministic summary and make no provider call. Byte caps are not exact token counts: configure/verify relay context ≥32k tokens, use conservative input token estimates, and reject locally if the configured budget cannot fit. Source-only evidence may be valid with `assessment=insufficient_evidence`; tool failures do not prove no activity.

Sanitization runs before version hashing, persistence and prompt construction. Use field allowlists first, then redact credential-shaped substrings (Authorization/Basic/Bearer, cookies, password/token/secret assignments, WSSE password/digest/nonce fragments) in every permitted string, including names, operations and reason text; never decode credentials to search them. If an identity string requires redaction, retain an opaque evidence-local alias for display and keep its exact query value only in the server context, never in model output or logs. Unknown nested keys are dropped. All protected numeric facts remain unchanged. This is defense in depth, not a claim that regex can identify every possible secret: arbitrary payload/free-form attributes are excluded entirely.

## 6. Structured assessment and provider boundary

`LLMProvider.generate(request:GenerationRequest, deadline) -> ProviderReply` is injected into the runner. `OpenAICompatibleProvider` uses existing `httpx`, a fixed configured base URL and model, no new SDK dependency. Proposed relay wire contract is one non-streaming `POST {base_url}/chat/completions` with `{model,messages,max_tokens:2000}` plus configured `response_format` mode. Expect `choices[0].message.content` containing one JSON object; usage/model fields are optional, stored as reported. Explicit modes `json_schema` and `json_object` are deployment settings, not dynamically negotiated through uncontrolled retries. Mock both. A real relay compatibility probe must use synthetic data before enablement; this plan does not claim its wire contract was verified live.

New settings in the existing frozen `Settings` dataclass: `OTEL_LLM_INVESTIGATION_ENABLED=false`, `OTEL_LLM_SINGLE_OWNER_ACK=false`, `OTEL_LLM_BASE_URL` (empty), `OTEL_LLM_API_KEY` (empty, `repr=False`), `OTEL_LLM_MODEL` (empty), `OTEL_LLM_RESPONSE_MODE=json_object`, `OTEL_LLM_ALLOW_LOOPBACK_HTTP=false`, `OTEL_LLM_CONTEXT_TOKENS=32768`. Budgets/time policies above are constants in `policy-v1`, not per-request overrides. Validate config only for the enabled owner. Provider key comes from process environment supplied by operators; never inspect/write `.env`, reuse ES/internal tokens, or copy the Codex relay secret. Record provider name and configured model, not URL credentials/key. Provider telemetry export requires operator authorization for the selected destination; existing finding access does not select arbitrary destinations.

HTTPS with certificate verification required except explicit loopback-only HTTP for a local relay/test fixture. Reject URL userinfo, query, fragment, unexpected paths; permit a configured base ending `/v1`. Fixed destination is operator-controlled. Disable redirects and ambient HTTP proxy inheritance (`trust_env=False`); never follow model-returned URLs. Dedicated AsyncClient with connect timeout 3s, bounded response body 64 KiB and total budget 45s. No external tools, shell, SQL, filesystem, Kubernetes, browser or credential API supplied to the model. Tool-call responses from the relay are invalid, not executed.

Model output `AssessmentV1` (all objects forbid extras):

```text
schema_version: literal "assessment-v1"
assessment: enum "explained" | "partially_explained" | "insufficient_evidence"
observed_fact_ids: array[evidence_id], max 20
correlation_ids: array[calculation_id], max 10
hypotheses: array[{
  id: string(max 32), statement: string(max 512),
  confidence: enum low|medium|high,
  supporting_evidence_ids: array[evidence_id](1..10),
  alternatives: array[string(max 256)](1..3),
  counter_evidence_ids: array[evidence_id](0..10)
}], max 5
missing_evidence: array[{
  code: enum unavailable|truncated|scope_unknown|baseline_not_snapshotted|sampling_unknown|causality_unproven,
  explanation: string(max 256), related_evidence_ids: array[evidence_id](0..5)
}], max 10
recommendations: array[{
  action: enum inspect_trace_sample|compare_attached_baseline|review_related_changes|review_service_context|human_review,
  evidence_ids: array[evidence_id](1..5), rationale: string(max 256)
}], max 5
```

The server, not the model, builds `observed_facts` from cited typed evidence and `derived_correlations` from a calculation catalog. Each calculation stores ID, inputs with evidence IDs/field names, formula/version, interval and computed result. Initial calculations: request-rate = requests / measured bucket seconds; error fraction = errors / requests (null for zero requests); source baseline delta/ratio only when compatible units and nonzero denominator are present; time overlap between two cited event windows. No risk formula, anomaly score, probability of maliciousness, percentile recomputation or inferred ML feature vectors. The model can select calculation IDs but cannot supply numerical results. Server-rendered summary uses these facts and the original finding, not an unchecked model paragraph.

Validation rejects unknown IDs, wrong versions, references to pruned evidence, empty hypothesis support, recommendation actions outside the enum, excessive strings/counts, score/type/severity overrides, prose-only/Markdown responses, duplicate JSON keys and nonfinite numbers. Facts are rendered from evidence so citations alone cannot turn model prose into facts. Hypotheses remain unverified interpretations even when cited; confidence is an ordinal investigation assessment, never a calibrated probability or replacement detector confidence. Render any text as escaped plain text; do not render supplied HTML, executable Markdown or outbound links. Recommend human review rather than asserting credential compromise or malicious intent from free text.

Prompt `investigation-v1` states the finding-only boundary, unchanged facts/scores, uncertainty rules, and required schema. Put canonical JSON evidence in a separate user message marked `UNTRUSTED_TELEMETRY_DATA`; use JSON escaping and length checks, not just a delimiter that telemetry can close. All strings in records, names, reason text and tool results remain data, including strings that imitate system messages. Never concatenate them into developer/system instructions. The model has no tools, so injections cannot gain authority even if wording is persuasive.

One repair allowed only for schema/reference validation errors, within the original token/time budget. Send the same frozen evidence and fixed validation error **codes**, not the invalid provider response or arbitrary validator prose. No repair for 401/403, rate limit, timeout, refusal or server/network failure. Total output allowance is 2,000 tokens across attempts (reserve 1,000 for each when repair is enabled); persist both attempts' safe usage/latency. Still invalid → `failed/invalid_output` with deterministic summary. Safety/refusal is `failed/provider_refused`. Do not persist raw invalid response or entire prompts.

## 7. Persistence, migration and observability

New migration `backend/clickhouse_migrations/007_llm_investigations.sql`: one additive table, no ALTER of source tables and no backfill. Table `llm_investigations`:

```text
id UUID; dedup_key FixedString(64); retry_index UInt8; retry_of Nullable(UUID)
finding_kind LowCardinality(String); finding_id String; source_version FixedString(64)
snapshot_schema_version String; prompt_version String; result_schema_version String; policy_version String
provider String; configured_model String; reported_model Nullable(String)
state LowCardinality(String); state_version UInt64; cancel_requested UInt8
created_at_ms UInt64; updated_at_ms UInt64; started_at_ms Nullable(UInt64)
finished_at_ms Nullable(UInt64); deadline_ms UInt64; expires_at DateTime64(3,'UTC')
snapshot_json String; evidence_json String; evidence_digest Nullable(String)
deterministic_summary_json String; result_json Nullable(String)
failure_code Nullable(String); metadata_json String
ENGINE ReplacingMergeTree(state_version)
ORDER BY (finding_kind, finding_id, id)
TTL expires_at DELETE
```

All transitions append a complete row with a strictly increasing per-ID `state_version`, read back using `FINAL`. Initialize version 1 and increment under the owner lock; on restart use stored version+1. Retry of the same uncertain INSERT resends identical ID/version/content. Repository methods: `get(id)`, `get_by_dedup_key(key)`, `list_for_finding(ref,limit)`, `append_state(row)`, `list_nonterminal(limit,cursor)`, `admission_counts(now)`. These are fixed-template, parameterized queries; ID/dedup reads are bounded by result/resource limits. ClickHouse merging is not a unique constraint: idempotency relies on supported single ownership plus deterministic IDs; test unmerged read behavior explicitly.

Keep all JSON payloads bounded: snapshot 64 KiB, evidence 128 KiB, result 32 KiB, metadata 16 KiB. Retain results/snapshots/evidence and failure metadata for 30 days from admission, unchanged across state transitions. Read filters require `expires_at > now()` so expired results are unavailable even before asynchronous TTL deletion. Dedup guarantee is within that retention; the source age gate prevents uncontrolled fresh reruns of expired historical findings. Only minimal sanitized evidence snapshots are stored, not full raw traces or bulk ES documents; this does not alter the agent-only raw trace persistence invariant.

Metadata: safe requester label `api_key_operator` (no key hash), attempt counts, per-tool query times, backend, returned counts, truncation/missing reasons, input/output token counts nullable, estimated-token flag, finish reason enum, source check times, failure class, end-to-end latency. Store only fixed error codes, no exception bodies or provider request/response dumps. Evidence source IDs/timestamps and bundle digest make each displayed claim auditable. No raw prompt or response logging. Do not expose high-cardinality principal IDs in metric labels.

Use structured logger `tracescope-investigation`: admitted/reused/rejected, state transitions, tool durations/counts, provider attempts, validation/repair, cancel/timeout, persistence failure and source invalidation, keyed by run UUID. In-memory counters track queue occupancy and failures by fixed code; retrieval provides per-run metadata. No new global observability service or provider-dependent health check. Provider disabled/outage leaves all deterministic APIs and worker stages operational.

Migration is discovered automatically and is compatible with old binaries ignoring the new table. Operators apply it through the existing designated migration owner only after review; implementation tests use disposable ClickHouse. Rollback is feature disable and owner shutdown, retaining table/results for audit and TTL. No downgrade/drop, no replay of findings, no score modifications. Enabling the feature must validate the table exists; missing schema disables investigations with 503 diagnostics without breaking ingestion.

## 8. Future ML compatibility and UI boundary

The existing deterministic facts (`NEW_TARGET`, `NEW_CALLER`, `NEW_OPERATION`, `NEW_SOURCE_IP`, `NEW_IP_CALLER_PAIR`, `DORMANT_REACTIVATED`, etc.) remain facts with unchanged points. Current scores are additive with family caps, not learned. A future detector may attach a versioned `detector_signal` to an **existing emitted finding**: `{producer, model_version, score, score_scale, window_size_sec:300, window_start_ms, feature_deviations, readiness, supporting_1m_signal_ids}`. Add that typed snapshot projection in a later schema version, preserving the source score as a sibling signal. No accepting arbitrary feature/score JSON as a replacement finding now.

The investigator may explain attached feature deviations and 1m early-change evidence after the 5m finding exists. It does not train the future model, build features, set its threshold, evaluate sequences for new abnormalities or promote a 1m signal into an incident. No implementation of the ML proposal in the contextual document is authorized by this plan.

V1 has no frontend modifications. API consumers can request, poll and cancel by exact source ID; run history is available without a chat interface. A later reviewed UI can place a small result panel in `AnomalyDetailPage` and the selected incident of `UserInvestigationsTab`, after browser authentication is designed. It must display the original source score separately, show source version/age and stale results, render the five result categories, and never automatically launch on navigation. Existing deterministic “Investigate” review actions retain their meaning; do not relabel them as LLM execution.

## 9. Worker file allowlist and implementation order

Only these files are authorized for the subsequent worker implementation. The planner edits only this plan. If implementation requires another path, report the concrete reason before expanding scope. Do not rewrite existing dirty files wholesale.

**Existing files to modify narrowly:**

1. `backend/config.py` — add only the investigation settings above; it is already dirty.
2. `backend/app/application.py` — router and owner lifecycle integration only; preserve role/ingestion behavior.

**Files to create:**

1. `backend/app/models/investigation.py` — source refs/snapshots, request/response/evidence/assessment schemas and bounded validators.
2. `backend/app/repositories/investigation_repository.py` — versioned persistence and admission/recovery reads.
3. `backend/app/repositories/investigation_evidence_repository.py` — strict finding loader and bounded CH/ES readers.
4. `backend/app/services/investigation_evidence.py` — scope derivation, sanitizer, evidence/correlation assembler and deterministic summary.
5. `backend/app/services/investigation_provider.py` — injectable provider protocol and fixed relay HTTP adapter.
6. `backend/app/services/investigation.py` — source-version checks, admission/dedup/rate limits, single-owner runner, cancellation/recovery.
7. `backend/app/prompts/investigation_v1.txt` — fixed instruction template, read as package-local text; no model-controlled filename.
8. `backend/app/api/investigations.py` — fail-closed auth and request/status/source/history/cancel contracts.
9. `backend/clickhouse_migrations/007_llm_investigations.sql` — additive table only.
10. `tests/test_llm_investigation_unit.py` — pure schema/scope/calculation/prompt tests.
11. `tests/test_llm_investigation_repository.py` — migrations, versioned state, dedup/TTL/recovery tests.
12. `tests/test_llm_investigation_security.py` — auth, query authorization, injection/redaction and cross-environment tests.
13. `tests/test_llm_investigation_api.py` — ASGI API and role/flag/error contracts.
14. `tests/test_llm_investigation_integration.py` — bounded real-store/fake-relay end-to-end tests including cancellation/provider failures.
15. `backend/scripts/test_llm_investigations.sh` — POSIX acceptance wrapper that fails unless `OTEL_TEST_DISPOSABLE_CLICKHOUSE=1`, an explicit host/port and an empty `OTEL_ES_URL` are supplied; reject production DB names and unset provider keys for the test subprocess. Invoke the exact selected tests below with a watchdog; never source `.env` or start infrastructure.

Implement in that dependency order: schemas/persistence → source/evidence reads → calculations/prompt/provider with mocks → owner/state machine → API/lifespan → tests and runbook verification. No external relay data transfer is needed for implementation acceptance. Worker should include any operational deviations in its final report rather than editing state/history documents.

**Denylist:** every path outside the allowlist, specifically `AGENTS.md`, `STATE.md`, both contextual docs, task briefs, `backend/worker.py`, `backend/elasticsearch.py`, all detector/normalization/aggregation/principal source files, existing user/anomaly/trace repositories and APIs, `backend/app/security.py`, `db_context.py`, `clickhouse_migrator.py`, migrations 001–006, `backend/requirements.txt`, `tests/conftest.py`, existing tests, all `frontend/`, all `deploy/`, `run_server.sh`, bootstrap/bundle/oldkernel links, `tools/`, generated data, `.env*`, secret files and Git state. Do not commit, reset, stash, checkout, reformat unrelated work, deploy, restart live services, run Kubernetes commands or mutate live databases.

## 10. Tests, acceptance and rollout

Tests must use synthetic identities/telemetry, fake clocks, injected repository/provider clients and `httpx.MockTransport` for relay/ES; no provider credentials. Integration uses one disposable ClickHouse server explicitly selected by the operator and the existing test harness. The new wrapper must check its guard **before importing pytest/conftest**, because conftest performs discovery and cleanup. Do not run the repository suite on shared/live ClickHouse just because database names start with `test_`.

Required assertions:

- **Unit:** three source kinds, UInt64 string boundary, wrong/zero/overflow IDs, strict timestamps, malformed/duplicate JSON keys, enum/length/depth/byte budgets, canonical stable versions, source-score preservation, 15m change-window labeling, 60m incident clipping, UTC second/ms conversion, missing baseline and zero-denominator math. Version changes when protected facts/lifecycle change; irrelevant read timestamps do not change it.
- **Repository/schema:** migration twice is idempotent, old table schemas/counts unchanged, `FINAL` returns latest pre-merge state, retry identical row, monotonic state versions, history limit, expiry read filtering, interrupted startup recovery, ambiguous source ID rejection. Persistence outage/ambiguous insert never acknowledges an unpersisted success.
- **Evidence authorization:** all tools require a valid context/version; wrong principal/environment, invented source IDs, arbitrary SQL/URL/path/time ranges, negative limits, excessive spans and extra fields rejected. Empty scoped changes remain empty despite global rows. ES-empty/error never pulls unrelated ClickHouse rows; CH-only mode works. Query caps are asserted on generated queries/native settings, not only returned arrays. Oversized ES body/unparseable hits become missing evidence. Global quality and current-only baselines carry limitations.
- **Injection/security:** telemetry that says “ignore prior instructions”, embeds role delimiters, requests SQL/shell/network, or includes fake citations cannot alter instructions or execute anything. Authorization/Basic/password/WSSE/cookie/bearer canaries inside arbitrary nested attributes/error bodies never reach prompts, table rows, logs or result. Unrecognized trace attributes are dropped. Relay redirects, tool calls, malformed JSON and injected score fields rejected. Citation-to-fact rendering verifies values from evidence; unsupported numeric calculations cannot be returned as facts.
- **API:** feature off 404, empty key 503, wrong key 401 on **all** methods, good key source fetch and admission; invalid/missing finding 422/404 with zero provider calls; missing version 422; stale/closed/superseded/mismatch 409; same request/retry reuses run; source invalidation while queued/generating is persisted and prevents a fresh result; unrelated existing APIs unaffected. Edge roles never mount routes or start owner.
- **Runner/provider failures:** concurrent 20 identical POSTs produce one ID/one relay call; 17 distinct admissions demonstrate queue bound; rate budget survives restart. Queue wait timeout, connect/read/deadline timeout, 429/500/refusal, cancellation before/during generation, malformed reply then one valid repair, second invalid reply, late completion, and result-storage failure have explicit states and bounded attempts. Provider outage retains deterministic summary and source facts byte-for-byte.
- **One bounded integration scenario, parameterized over three source types:** seed one valid finding per kind plus unrelated decoys, ≤40 traces, 12 rollups and one quality row; snapshot → POST → poll ≤5 seconds with fake fast provider → validate citations/frozen facts → repeat POST → retrieve same ID. Query all source rows before/after and require exact equality; no new anomaly/change/incident rows. Add source update during fake provider wait and verify `source_changed`. Limit query/provider counts explicitly.

Acceptance commands (run from repository root, only after implementation; **not run by this planner**):

```sh
# Operator first selects a dedicated disposable ClickHouse server on this test port.
# These variables describe that test instance, never the active :8123 deployment.
OTEL_TEST_DISPOSABLE_CLICKHOUSE=1 OTEL_CLICKHOUSE_HOST=127.0.0.1 OTEL_CLICKHOUSE_PORT=18123 OTEL_ES_URL= timeout 300s sh backend/scripts/test_llm_investigations.sh
timeout 10s sh -n backend/scripts/test_llm_investigations.sh
timeout 10s git diff --check -- backend/config.py backend/app/application.py
```

The wrapper executes `.venv/bin/python -m pytest -q tests/test_llm_investigation_unit.py tests/test_llm_investigation_repository.py tests/test_llm_investigation_security.py tests/test_llm_investigation_api.py tests/test_llm_investigation_integration.py tests/test_service_boundaries.py tests/test_split_workloads_integration.py tests/test_agent_traces_only.py tests/test_identity_normalization_and_incidents.py`. Clear `ELASTICSEARCH_URL` as well as `OTEL_ES_URL` in its child environment; fixtures turn on provider flags only with mock settings. Wrapper must refuse a missing guard/host/port, stop if test ClickHouse is unavailable, and never auto-discover/fall back to the live store. Also assert existing test fixtures cannot override the selected test server. Test count is discovered, not hardcoded. Expected: exit 0, strict source-only admission, unchanged source tables, bounded store/provider calls, no external provider traffic, no leaked canaries and no regressions in role/storage/deterministic behavior.

Read-only post-deployment checks, for a separately authorized operator rollout: health remains 200 at `http://127.0.0.1:30102/api/v1/health`; disabled investigation route returns 404. Enabled synthetic staging flow exercises authenticated source/admission/poll/cancel and all source statuses using the API tests' contracts. Do not put key values in commands, shell history or logs. The existing live curl scripts are not acceptance prerequisites: planner/worker must not let broad live scripts create test telemetry or alter review state. API contract tests are performed in ASGI with controlled fixtures.

Rollout sequence: merge/review implementation separately → apply additive migration through existing owner → verify fake relay integration on disposable store → operator supplies relay credentials/destination/model and verifies schema/context compatibility with synthetic input → explicitly enable only the single owner in staging → inspect bounded metadata and failure behavior → separately authorize production enablement. No Helm/deployment edits in this worker scope. Disable feature to roll back; no detection behavior or data migration rollback needed. No automatic launch flag is introduced.

Unresolved **deployment inputs**, not implementation blockers: actual authorized relay URL/model/secret, supported response mode/context and data-handling policy, availability of a disposable test server, and confirmation that exactly one `all` process is enabled. Do not invent those values. Acceptance with fake relay is sufficient for code review; production readiness requires these operator checks. If multi-replica execution or browser launching is required, request a separately reviewed expansion rather than weakening the ownership/auth boundaries.

## 11. Planner verification

The planner read the task brief, project instructions, scoring/ML context, source models/repositories/APIs/configuration/migrations, test harness, and relevant UI entry points. Verified live health/OpenAPI/list/missing-ID behavior read-only. No implementation, migration, suite execution, relay call, infrastructure mutation or commit was performed. Only this document is authorized for the planner; preserve all pre-existing dirty work.

```text
PLAN_STATUS: READY_FOR_IMPLEMENTATION
IMPLEMENTATION_SCOPE: backend/config.py,backend/app/application.py,backend/app/models/investigation.py,backend/app/repositories/investigation_repository.py,backend/app/repositories/investigation_evidence_repository.py,backend/app/services/investigation_evidence.py,backend/app/services/investigation_provider.py,backend/app/services/investigation.py,backend/app/prompts/investigation_v1.txt,backend/app/api/investigations.py,backend/clickhouse_migrations/007_llm_investigations.sql,tests/test_llm_investigation_unit.py,tests/test_llm_investigation_repository.py,tests/test_llm_investigation_security.py,tests/test_llm_investigation_api.py,tests/test_llm_investigation_integration.py,backend/scripts/test_llm_investigations.sh
MCP_DECISION: INTERNAL
ACCEPTANCE_COMMANDS: OTEL_TEST_DISPOSABLE_CLICKHOUSE=1 OTEL_CLICKHOUSE_HOST=127.0.0.1 OTEL_CLICKHOUSE_PORT=18123 OTEL_ES_URL= timeout 300s sh backend/scripts/test_llm_investigations.sh;timeout 10s sh -n backend/scripts/test_llm_investigations.sh;timeout 10s git diff --check -- backend/config.py backend/app/application.py
```
