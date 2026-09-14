# TASK: Live E2E test of the deployed app at https://trace.n2d.id.vn

Test the DEPLOYED TraceScope application end-to-end over HTTP and produce an evidence-based report. The repo in this directory is the source of truth for what the app SHOULD do — but note: the just-completed fixes (see FIX_REPORT.md) are uncommitted and almost certainly NOT yet deployed, so where live behavior differs from fixed expectations, report it as an observation (e.g. "matches pre-fix code"), never as an assumption.

## Pre-flight facts (measured moments ago)

- `GET /` → 200 (~0.46s)
- `GET /api/v1/health` → 200 `{"status":"ok","demo_mode":false,"service_role":"all"}`
- Deployment: Helm chart `deploy/helm/tracescope` via Cloudflare Tunnel; app API/UI on :30102, ingest :30103, ClickHouse on 127.0.0.1:8123 (host `tracescope` db). Same host also serves the app locally at http://127.0.0.1:30102 — you may cross-check local vs public to isolate ingress issues.
- Endpoint map: see AGENTS.md §1 (overview, services, principals, topology, anomalies, traces, blast-radius, users, user-changes, user-graph, user-analytics, incidents, ingest + aliases, agent stats, legacy aliases `/api/v1/accounts`, `/api/v1/dashboard/*`, `/api/v1/events`, `/api/v1/ingestion/status`).

## Test matrix (execute ALL; polite pacing — this is production: sequential requests, no loops tighter than ~200ms, total under ~300 requests)

1. **Core API happy paths**: GET health, overview, services, services/{first}, principals, principals/{first}, topology, anomalies, traces, traces/{first_id}, users, user-graph, user-analytics, incidents. For each: status code, response shape (does it match the Pydantic models in backend/app/models/?), non-trivial payload (real data present vs empty), response time. Fetch one real ID first (from services/anomalies/traces lists) before detail calls.
2. **Parametrization**: time-range params on topology/anomalies/services — try BOTH `start`/`end` and `from`/`to` with a narrow recent window (e.g. last 30 min) and compare result counts; report which spelling actually filters (this was fix #13). Pagination on traces: `limit=1`, `limit=1000000` (observe: clamped? error? huge response?), `limit=-5`, `offset=-1`.
3. **Error handling / contract**: unknown service/principal/anomaly ID (expect clean 404, not 500 — fix #14 concern); malformed inputs (`/api/v1/traces/not-a-uuid` style); unknown routes; trailing-slash behavior; HTTP method mismatch (e.g. DELETE on a GET route).
4. **Security posture (live verification of fixed findings)**:
   - `GET /internal/storage/health`, `GET /internal/anything` and any `/internal/*` path found in `backend/app/api/internal_storage.py` → report status. If reachable from the public URL, that is the CRITICAL #2 exposure — demonstrate with read-only GETs only (max 3 requests) and include the exact request+status in the report.
   - Unauthenticated mutations: `POST /api/v1/ingest` with a 1-record valid-ish OTLP/ELK JSON body → expect 401/403 if `OTEL_API_KEY` is set, else 200 (report which — auth-off is finding #7). Try the aliases too (`/api/v1/ingest/traces`, `/api/ingest`). Also `DELETE /api/agent/stats/nonexistent-node-xyz` and `PATCH /api/v1/anomalies/00000000-0000-0000-0000-000000000000` → report status (mutation auth + 404 correctness).
   - Do NOT send oversized payloads or decompression bombs to production. Malformed-gzip only: `POST /api/ingest` with tiny corrupt gzip (~50 bytes) → expect 400, never 5xx.
   - SPA traversal probes (fix #10): `GET /../AGENTS.md`, `GET /%2e%2e/AGENTS.md`, `GET /..%2FAGENTS.md`, `GET /../../etc/passwd` → expect 404. Report exactly what returns (200 with file content = critical).
5. **Frontend serving**: `GET /` returns the SPA HTML referencing hashed assets; fetch 1-2 referenced `/assets/*.js` (200, non-empty); `GET /some/deep/route` → SPA fallback returns index.html (200) and NOT a file outside dist; compare asset hashes served publicly vs locally built `frontend/dist` if present.
6. **Agent stats protocol** (read-only): `GET /api/agent/stats`, `GET /api/agent/stats/{node if any}` — shape + status. Skip DELETEs except the single unauthenticated one in §4.
7. **Ingestion status**: `GET /api/v1/ingestion/status` — counters present and sane.
8. **Local-vs-public consistency**: for 3 representative endpoints (health, topology, one asset), diff local (127.0.0.1:30102) vs public responses — catches ingress/tunnel mismatches.

## Hard constraints

- READ-ONLY against production except the explicitly listed bounded mutation probes (all expected to be rejected; no authenticated writes — you do not have the API key and must not extract or guess it from cluster secrets).
- FORBIDDEN: helm upgrade/rollback, kubectl apply/delete/scale/restart/port-forward/exec, curl brute force, nmap/scanners, large payloads, actual compression bombs, anything that writes to ClickHouse (no synthetic trace ingestion with a key).
- Read-only kubectl (`get pods`, `get ingress`, `get svc` in the app's namespace) is allowed ONLY to diagnose a discrepancy; label any such evidence.
- Do not modify ANY file in this repo. No git commands that mutate state. Deliverable file only (below).
- If a request errors unexpectedly (5xx), capture status + body snippet + retry once after 2s before concluding.

## Deliverable

Write `LIVE_APP_TEST_REPORT.md` at repo root:
1. Executive summary: pass/fail counts, top issues.
2. Matrix results table: endpoint/probe | sent | status | key response evidence | verdict (pass/fail/observation).
3. Issues found: severity, evidence (verbatim status + response snippet), whether it matches pre-fix or fixed code, suggested action (deploy? code?).
4. Deployment-version assessment: does live behavior indicate the pre-fix build (e.g. /internal reachable, auth missing) or the fixed build?
5. Local-vs-public consistency findings.
Honest reporting: record real outputs verbatim; never fabricate. If something could not be tested, say why.
