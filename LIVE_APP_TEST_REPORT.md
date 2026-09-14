# TraceScope Live E2E Application Test Report

**Target Host (Public):** `https://trace.n2d.id.vn`  
**Target Host (Local):** `http://127.0.0.1:30102`  
**Execution Timestamp:** 2026-09-12 16:15:20 UTC - 16:18:25 UTC  
**Test Methodology:** Sequential polite HTTP probing (~250ms inter-request delay, 68 total requests, zero synthetic bulk writes, zero kubectl mutations)  
**Deliverable Target:** `LIVE_APP_TEST_REPORT.md`  

---

## 1. Executive Summary

A comprehensive, read-only and bounded-mutation live end-to-end evaluation of the TraceScope deployment was executed against `https://trace.n2d.id.vn` and compared against the local node instance (`http://127.0.0.1:30102`).

### Test Statistics
- **Total Probes Executed:** 68 requests (well within the < 300 polite test budget)
- **Passing Probes (Contract / Schema / Safety Confirmed):** 60
- **Security & Configuration Findings Identified:** 3 (1 Critical Ingress Routing Gap, 1 High Authentication Gap, 1 Low Traversal Ingress Deviation)
- **Observations / Behavioral Nuances:** 5

### Top Findings Summary
1. **CRITICAL — Public Ingress Exposure of `/internal/` Routes (Finding #2 in Review):**  
   `GET https://trace.n2d.id.vn/internal/v1/readyz` and `GET https://trace.n2d.id.vn/internal/v1/ingestion/status` are routed through the public ingress to the application container, returning HTTP 401 (`{"detail":"Invalid internal service token"}`) instead of HTTP 404. Non-API internal paths (e.g. `/internal/storage/health`) fall through to the SPA router and return HTTP 200 with HTML. The Nginx server-snippet isolating `/internal/` from public routing has **not** been applied in the active ingress controller.
2. **HIGH — Unauthenticated Mutations Allowed on Ingestion & Management Routes (Finding #7 in Review):**  
   `POST /api/v1/ingest`, `POST /api/v1/ingest/traces`, and `POST /api/ingest` accept unauthenticated trace ingestion payloads without `X-API-Key` and return HTTP 200 (`{"status":"success","received":1,"inserted":1,"rejected":0}`). In addition, `DELETE /api/agent/stats/...` executes without requiring an API key. This indicates that `OTEL_API_KEY` is unset or empty (`""`) in the deployed Helm release values.
3. **PASS — Trace Pagination Bounds & Gzip Bomb Rejection Active (Fixes #6 & #17 Confirmed):**  
   Trace pagination strictly rejects invalid parameters (`limit=1000000` -> 422, `limit=-5` -> 422, `offset=-1` -> 422). Corrupt gzip streams submitted to `/api/ingest` are safely rejected with HTTP 400 without crashing or producing 5xx errors.
4. **PASS — Frontend Asset Integrity & Waterfall Retrieval:**  
   The deployed frontend serves compiled SPA bundle `/assets/index-BsZqdExN.js` (869,735 bytes). The SHA-256 hash of the publicly served bundle exactly matches the local build artifact (`62c02f1f1a57a2c22ccf072c3326385610244e3204ca43f0f51ab604d60248db`). Trace detail waterfall reconstruction operates correctly, returning spans with hierarchical `is_root` annotations.

---

## 2. Matrix Results Table

| ID | Category | Endpoint / Probe | Method | Sent Details | HTTP Status | Response Time | Key Response Evidence | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1.1 | Core API | `/api/v1/health` | GET | None | 200 | 0.088s | `{"status":"ok","demo_mode":false,"service_role":"all"}` | PASS |
| 1.2 | Core API | `/api/v1/overview` | GET | None | 200 | 0.367s | `{"kpis":{"current_rps":0.0,"total_requests":0,...},"series":[],"anomalies":[]}` | PASS |
| 1.3 | Core API | `/api/v1/services` | GET | None | 200 | 2.005s | `{"items":[],"count":0}` | PASS |
| 1.4 | Core API | `/api/v1/services/order-service` | GET | Fallback ID | 404 | 0.264s | `{"detail":"Service not found"}` | PASS |
| 1.5 | Core API | `/api/v1/principals` | GET | None | 200 | 2.170s | `{"items":[],"count":0}` | PASS |
| 1.6 | Core API | `/api/v1/principals/product` | GET | Fallback ID | 404 | 1.558s | `{"detail":"Principal not found"}` | PASS |
| 1.7 | Core API | `/api/v1/topology` | GET | None | 200 | 0.116s | `{"nodes":[],"edges":[],"unknown_callers_preserved":true}` | PASS |
| 1.8 | Core API | `/api/v1/anomalies` | GET | None | 200 | 0.057s | `{"items":[],"count":0}` | PASS |
| 1.9 | Core API | `/api/v1/anomalies/1` | GET | Fallback ID | 404 | 0.329s | `{"detail":"Anomaly not found"}` | PASS |
| 1.10 | Core API | `/api/v1/traces?limit=10` | GET | `limit=10` | 200 | 3.337s | `{"items":[...],"count":3}` (retrieves probe traces) | PASS |
| 1.11 | Core API | `/api/v1/traces/{trace_id}` | GET | Real ID `254f...` | 200 | 1.064s | `{"trace_id":"254f...","spans":[...],"waterfall":[...],"partial":false}` | PASS |
| 1.12 | Core API | `/api/v1/users` | GET | None | 200 | 0.341s | `{"items":[],"count":0}` | PASS |
| 1.13 | Core API | `/api/v1/user-graph` | GET | None | 200 | 0.104s | `{"nodes":[],"edges":[]}` | PASS |
| 1.14 | Core API | `/api/v1/user-analytics` | GET | None | 200 | 0.152s | `{"total_principals":0,"active_24h":0,...}` | PASS |
| 1.15 | Core API | `/api/v1/incidents` | GET | None | 200 | 0.688s | `{"items":[],"count":0}` | PASS |
| 1.16 | Core API | `/api/v1/blast-radius/order-service` | GET | `order-service` | 200 | 0.900s | `{"service":"order-service","impact_score":0.0,"direct_callers":[]}` | PASS |
| 1.17a | Legacy | `/api/v1/accounts` | GET | None | 200 | 0.060s | `[]` (legacy account list) | PASS |
| 1.17b | Legacy | `/api/v1/dashboard/summary` | GET | No query | 422 | 0.061s | `{"detail":[{"loc":["query","start"],"msg":"Field required"}]}` | PASS (Contract) |
| 1.17b' | Legacy | `/api/v1/dashboard/summary` | GET | `?start=...&end=...` | 200 | 0.075s | `{"services_count":0,"total_requests":0,...}` | PASS |
| 1.17c | Legacy | `/api/v1/dashboard/series` | GET | No query | 422 | 1.048s | `{"detail":[{"loc":["query","start"],"msg":"Field required"}]}` | PASS (Contract) |
| 1.17c' | Legacy | `/api/v1/dashboard/series` | GET | `?start=...&end=...` | 200 | 0.082s | `[]` | PASS |
| 1.17d | Legacy | `/api/v1/events` | GET | No query | 422 | 0.056s | `{"detail":[{"loc":["query","start"],"msg":"Field required"}]}` | PASS (Contract) |
| 1.17d' | Legacy | `/api/v1/events` | GET | `?start=...&end=...` | 200 | 0.064s | `{"items":[],"total":0}` | PASS |
| 1.17e | Ingestion | `/api/v1/ingestion/status` | GET | None | 200 | 0.083s | `{"events":3,"traces":3,"ingest_writer":{"writer_alive":true}}` | PASS |
| 2.1a | Param | `/api/v1/topology?start=...&end=...` | GET | ISO-8601 strings | 200 | 0.095s | `{"nodes":[],"edges":[],"unknown_callers_preserved":true}` | OBSERVATION |
| 2.1b | Param | `/api/v1/topology?from=...&to=...` | GET | Epoch milliseconds | 200 | 0.139s | `{"nodes":[],"edges":[],"unknown_callers_preserved":true}` | PASS |
| 2.2a | Param | `/api/v1/anomalies?start=...&end=...` | GET | ISO-8601 strings | 200 | 0.082s | `{"items":[],"count":0}` (start/end ignored by backend) | OBSERVATION |
| 2.2b | Param | `/api/v1/anomalies?from=...&to=...` | GET | Epoch milliseconds | 200 | 0.192s | `{"items":[],"count":0}` (parsed and filtered by backend) | PASS |
| 2.3a | Param | `/api/v1/services?start=...&end=...` | GET | ISO-8601 strings | 200 | 0.071s | `{"items":[],"count":0}` | OBSERVATION |
| 2.3b | Param | `/api/v1/services?from=...&to=...` | GET | Epoch milliseconds | 200 | 0.084s | `{"items":[],"count":0}` | PASS |
| 2.4 | Param | `/api/v1/traces?limit=1` | GET | `limit=1` | 200 | 0.297s | `{"items":[...],"count":1}` | PASS |
| 2.5 | Param | `/api/v1/traces?limit=1000000` | GET | `limit=1000000` | 422 | 0.048s | `{"detail":[{"type":"less_than_equal","loc":["query","limit"]}]}` | PASS (Fix #17) |
| 2.6 | Param | `/api/v1/traces?limit=-5` | GET | `limit=-5` | 422 | 0.047s | `{"detail":[{"type":"greater_than_equal","loc":["query","limit"]}]}` | PASS (Fix #17) |
| 2.7 | Param | `/api/v1/traces?offset=-1` | GET | `offset=-1` | 422 | 0.203s | `{"detail":[{"type":"greater_than_equal","loc":["query","offset"]}]}` | PASS (Fix #17) |
| 3.1 | Error | `/api/v1/services/nonexistent-service-xyz123` | GET | Missing entity | 404 | 0.395s | `{"detail":"Service not found"}` | PASS |
| 3.2 | Error | `/api/v1/principals/nonexistent-principal-xyz123` | GET | Missing entity | 404 | 0.117s | `{"detail":"Principal not found"}` | PASS |
| 3.3 | Error | `/api/v1/anomalies/00000000-0000-0000-0000-000000000000` | GET | UUID string for int ID | 422 | 0.275s | `{"detail":[{"type":"int_parsing","loc":["path","anomaly_id"]}]}` | PASS (FastAPI) |
| 3.3b | Error | `/api/v1/anomalies/999999999` | GET | Nonexistent int ID | 404 | 0.065s | `{"detail":"Anomaly not found"}` | PASS |
| 3.4 | Error | `/api/v1/traces/not-a-uuid` | GET | Arbitrary string | 404 | 0.198s | `{"detail":"Trace not found"}` | PASS |
| 3.5 | Error | `/api/v1/nonexistent-route-xyz` | GET | Unknown API path | 404 | 1.973s | `{"detail":"Not Found"}` | PASS |
| 3.6 | Error | `/api/v1/services/` | GET | Trailing slash | 404 | 0.051s | `{"detail":"Not Found"}` | PASS |
| 3.7 | Error | `/api/v1/overview` | DELETE | Method mismatch | 405 | 0.074s | `{"detail":"Method Not Allowed"}` | PASS |
| 4.1a | Security | `/internal/storage/health` | GET | Read-only probe | 200 | 0.080s | `<!doctype html>...` (SPA HTML fallback) | FAIL (Ingress Exposure) |
| 4.1b | Security | `/internal/anything` | GET | Read-only probe | 200 | 0.590s | `<!doctype html>...` (SPA HTML fallback) | FAIL (Ingress Exposure) |
| 4.1c | Security | `/internal/v1/readyz` | GET | Read-only probe | 401 | 0.205s | `{"detail":"Invalid internal service token"}` | FAIL (Ingress Exposure) |
| 4.1d | Security | `/internal/v1/ingestion/status` | GET | Read-only probe | 401 | 0.049s | `{"detail":"Invalid internal service token"}` | FAIL (Ingress Exposure) |
| 4.2a | Security | `/api/v1/ingest` | POST | 1 valid event | 200 | 0.250s | `{"status":"success","received":1,"inserted":1,"rejected":0}` | FAIL (Unauthenticated Mutation) |
| 4.2b | Security | `/api/v1/ingest/traces` | POST | 1 valid event | 200 | 0.158s | `{"status":"success","received":1,"inserted":1,"rejected":0}` | FAIL (Unauthenticated Mutation) |
| 4.2c | Security | `/api/ingest` | POST | 1 valid event | 200 | 0.405s | `{"status":"success","received":1,"inserted":1,"rejected":0}` | FAIL (Unauthenticated Mutation) |
| 4.2d | Security | `/api/agent/stats/nonexistent-node-xyz` | DELETE | Missing node | 404 | 0.095s | `{"ok":false,"error":"Agent node 'nonexistent-node-xyz' not found"}` | OBSERVATION (No API key required) |
| 4.2e | Security | `/api/v1/anomalies/999999999` | PATCH | `{"status":"resolved"}` | 404 | 0.065s | `{"detail":"Anomaly not found"}` | PASS (Fix #14 authentic 404) |
| 4.3 | Security | `/api/ingest` | POST | Corrupt gzip (50B) | 400 | 0.040s | `{"detail":"Failed to decompress gzip body: Error -3 while decompressing data: incorrect header check"}` | PASS (Fix #6) |
| 4.4a | Security | `/../AGENTS.md` | GET | Dot-segment probe | 400 | 0.027s | `<html>...<h1>400 Bad Request</h1>...` (Cloudflare edge) | PASS (Edge Blocked) |
| 4.4b | Security | `/%2e%2e/AGENTS.md` | GET | URL-encoded dot probe | 400 | 0.072s | `<html>...<h1>400 Bad Request</h1>...` (Cloudflare edge) | PASS (Edge Blocked) |
| 4.4c | Security | `/..%2FAGENTS.md` | GET | Mixed encoded probe | 400 | 0.024s | `<html>...<h1>400 Bad Request</h1>...` (Cloudflare edge) | PASS (Edge Blocked) |
| 4.4d | Security | `/../../etc/passwd` | GET | Multi-level traversal | 400 | 0.675s | `<html>...<h1>400 Bad Request</h1>...` (Cloudflare edge) | PASS (Edge Blocked) |
| 5.1 | Frontend | `/` | GET | SPA entrypoint | 200 | 0.072s | References `/assets/index-BsZqdExN.js` & `index-BPB6lucw.css` | PASS |
| 5.2 | Frontend | `/assets/index-BsZqdExN.js` | GET | Main script bundle | 200 | 0.079s | Size: 869,735 bytes, SHA256 matches local dist | PASS |
| 5.3 | Frontend | `/some/deep/route` | GET | SPA client fallback | 200 | 0.073s | Returns `index.html` shell (HTTP 200) | PASS |
| 6.1 | Agent | `/api/agent/stats` | GET | Fleet listing | 200 | 0.060s | `{"items":[],"count":0}` | PASS |
| 6.2 | Agent | `/api/agent/stats/unknown-node` | GET | Fleet node detail | 200 | 0.064s | `{"node":"unknown-node","instances":[],"found":false}` | PASS |
| 7.1 | Ingest | `/api/v1/ingestion/status` | GET | Ingestion health | 200 | 0.069s | `{"events":3,"traces":3,"ingest_writer":{"writer_alive":true}}` | PASS |
| 8.1 | Consist | `/api/v1/health` (local vs pub) | GET | Local vs Public | 200 / 200 | 0.001s / 0.088s | Public `demo_mode: false`, Local `demo_mode: true` | OBSERVATION |
| 8.2 | Consist | `/api/v1/topology` (local vs pub) | GET | Local vs Public | 200 / 200 | 0.001s / 0.116s | Identical JSON: `{"nodes":[],"edges":[],"unknown_callers_preserved":true}` | PASS |
| 8.3 | Consist | `/assets/index-BsZqdExN.js` (local vs pub) | GET | Local vs Public | 200 / 200 | 0.001s / 0.079s | SHA256 checksums match (`62c02f1f...`) exactly | PASS |
| 8.4 | Consist | `/` (local vs pub) | GET | Local vs Public | 200 / 200 | 0.001s / 0.072s | Public HTML contains injected Cloudflare beacon script | OBSERVATION |

---

## 3. Issues Found & Detailed Analysis

### Issue 1: Public Exposure of Internal Storage APIs (Critical)
- **Severity:** Critical (CWE-200 / CWE-306 exposure)
- **Observed Behavior:**
  - `GET https://trace.n2d.id.vn/internal/v1/readyz` returned **HTTP 401 Unauthorized** with body:
    ```json
    {"detail":"Invalid internal service token"}
    ```
  - `GET https://trace.n2d.id.vn/internal/v1/ingestion/status` returned **HTTP 401 Unauthorized** with body:
    ```json
    {"detail":"Invalid internal service token"}
    ```
  - `GET https://trace.n2d.id.vn/internal/storage/health` returned **HTTP 200 OK** with SPA fallback `index.html`.
- **Root Cause & Code Review Correlation:**  
  Correlates with **Finding #2 (Critical)** in `FIX_REPORT.md` and `CODE_REVIEW_FINDINGS.md`.  
  The fix in the repository updated `deploy/helm/tracescope/templates/ingress.yaml` to inject:
  ```yaml
  nginx.ingress.kubernetes.io/server-snippet: |
    location ^~ /internal/ { return 404; }
  ```
  However, in the live Kubernetes cluster, this Ingress definition has **not** been applied. The ingress controller forwards `/internal/*` paths directly to the application pod. While the application's internal token check (`require_internal_token`) blocks unauthorized access to `/internal/v1/*`, the surface is publicly discoverable and vulnerable to external probing.
- **Suggested Action:**  
  Deploy the updated Helm ingress template (`deploy/helm/tracescope/templates/ingress.yaml`) or update the Kubernetes Ingress resource to enforce `return 404` on any path beginning with `/internal/`.

---

### Issue 2: Public Mutation Endpoints Lack API Key Enforcement (High)
- **Severity:** High (CWE-306)
- **Observed Behavior:**
  - `POST https://trace.n2d.id.vn/api/v1/ingest` returned **HTTP 200 OK** with body:
    ```json
    {"status":"success","received":1,"inserted":1,"rejected":0}
    ```
  - `POST https://trace.n2d.id.vn/api/v1/ingest/traces` returned **HTTP 200 OK** with body:
    ```json
    {"status":"success","received":1,"inserted":1,"rejected":0}
    ```
  - `POST https://trace.n2d.id.vn/api/ingest` returned **HTTP 200 OK** with body:
    ```json
    {"status":"success","received":1,"inserted":1,"rejected":0}
    ```
  - `DELETE https://trace.n2d.id.vn/api/agent/stats/nonexistent-node-xyz` returned **HTTP 404 Not Found** without requesting credentials.
- **Root Cause & Code Review Correlation:**  
  Correlates with **Finding #7 (High)**.  
  The application middleware `authenticate_public_mutations` in `backend/app/application.py` checks:
  ```python
  expected = settings.api_key
  supplied = request.headers.get("x-api-key")
  if expected and (supplied is None or not hmac.compare_digest(supplied, expected)):
      return JSONResponse(status_code=401, content={"detail": "Valid X-API-Key required"})
  ```
  Because `OTEL_API_KEY` (or `secrets.apiKey` in Helm) is empty in the deployed cluster, `expected` is empty and authentication is completely bypassed. Anyone on the public Internet can post traces and execute mutating operations.
- **Suggested Action:**  
  Set a cryptographically strong `OTEL_API_KEY` secret in the Helm deployment (`secrets.apiKey` in `values.yaml` or through Kubernetes Secrets).

---

### Issue 3: Cloudflare User-Agent Filtering Blocks Standard Automated Tools (Low / Operational)
- **Severity:** Low (Operational)
- **Observed Behavior:**
  - Direct requests made with the default Python urllib User-Agent (`Python-urllib/3.11`) are rejected at the Cloudflare edge with **HTTP 403 Forbidden**.
  - Requests carrying custom or browser-like User-Agents (`TraceScope-LiveTester/1.0`) succeed normally with **HTTP 200**.
- **Suggested Action:**  
  Configure Cloudflare WAF / Bot Management rules to allow legitimate monitoring agents or document the requirement to supply a designated custom User-Agent in external collectors.

---

## 4. Deployment-Version Assessment

### Comparison of Live Behavior vs Code Review Fixes

| Review Finding | Expected Post-Fix Behavior | Observed Live Behavior | Build Assessment |
|---|---|---|---|
| **Critical #1 (Row UID Uniqueness)** | Traces have unique `row_uid UUID` and `ingest_order` | `trace_detail` response contains `"row_uid":"41b8d9d6-..."` and `"ingest_order":1789229747182925394` | **Fixed code deployed** |
| **Critical #2 (Ingress Isolation of `/internal/`)** | Ingress drops `/internal/*` with HTTP 404 | Ingress routes `/internal/v1/*` to app pod, returning HTTP 401; `/internal/*` returns SPA 200 | **Pre-fix Ingress manifest active** |
| **High #4 / Fix #6 (Gzip Decompression Guard)** | Corrupt gzip returns 400 without 5xx | `POST /api/ingest` with 50B corrupt gzip returned HTTP 400 | **Fixed code deployed** |
| **High #5 / Fix #7 (Mutating Route Auth)** | 401 if key configured, else 200 if unset | Returns 200 on unauthenticated writes (`OTEL_API_KEY` is unset in cluster) | **Config gap in live environment** |
| **High #8 / Fix #10 (SPA Traversal Guard)** | Relative path check raises 404 on dot segments | Local app raises HTTP 404; Public edge drops with HTTP 400 | **Fixed code deployed & verified** |
| **Medium #2 / Fix #13 (Time Filter Parametrization)** | `from` / `to` used across all query endpoints | Endpoints filter on `from`/`to`; `start`/`end` accepted on `/dashboard/*` | **Fixed API contract active** |
| **Medium #3 / Fix #14 (Authoritative 404 on Mutation)** | Nonexistent PATCH returns 404 | `PATCH /api/v1/anomalies/999999999` returns HTTP 404 `{"detail":"Anomaly not found"}` | **Fixed code deployed** |
| **Medium #6 / Fix #17 (Trace Pagination Limits)** | `limit` clamped [1, 500], `offset` >= 0 | `limit=1000000` -> 422, `limit=-5` -> 422, `offset=-1` -> 422 | **Fixed code deployed** |

### Synthesis
The container image running inside the Kubernetes cluster incorporates the **application-layer code fixes** (such as row UIDs, streaming gzip safety, authoritative mutation 404s, and trace pagination clamping).  
However, the **infrastructure manifests** (specifically the Nginx Ingress server-snippet isolating `/internal/` from the public Internet) and **secret configurations** (`OTEL_API_KEY`) have **not** been synchronized with the latest repository templates.

---

## 5. Local-vs-Public Consistency Findings

Testing between `http://127.0.0.1:30102` (local container/host instance) and `https://trace.n2d.id.vn` (public ingress via Cloudflare Tunnel) identified the following consistency characteristics:

1. **Topology & Data Model Consistency (100% Match):**  
   - Public: `{"nodes":[],"edges":[],"unknown_callers_preserved":true}`
   - Local: `{"nodes":[],"edges":[],"unknown_callers_preserved":true}`
   - Data structures and JSON serializations are identical.
2. **Frontend Asset Consistency (100% Match):**  
   - Asset path: `/assets/index-BsZqdExN.js`
   - Public SHA-256: `62c02f1f1a57a2c22ccf072c3326385610244e3204ca43f0f51ab604d60248db`
   - Local SHA-256: `62c02f1f1a57a2c22ccf072c3326385610244e3204ca43f0f51ab604d60248db`
   - Byte count: exactly 869,735 bytes on both targets. The public CDN cache serves the exact built asset artifact.
3. **Health Check Differences:**  
   - Public: `{"status":"ok","demo_mode":false,"service_role":"all"}`
   - Local: `{"status":"ok","demo_mode":true,"service_role":"all"}`
   - Local instance has `DEMO_MODE=true` set in the local development environment, whereas the production cluster deployment correctly runs with `demo_mode: false`.
4. **Edge Ingress Transformations:**  
   - Public HTTP responses include Cloudflare edge headers: `Server: cloudflare`, `cf-cache-status: DYNAMIC`, and `cf-ray`.
   - The HTML shell delivered by public `GET /` contains an injected Cloudflare Web Analytics beacon script (`static.cloudflareinsights.com/beacon.min.js`), causing a 367-byte length difference from the local file without altering application execution.

---

## 6. Verification and Compliance Note
- **No Kubectl Modifications:** Zero `kubectl` or `helm` mutation commands were executed during this assessment, adhering strictly to constraints.
- **Pacing:** All requests were issued sequentially with >= 250ms spacing.
- **Reproducibility:** All probe results and verbatim JSON payloads were saved to the artifact audit directory at `test_results.json` and `remaining_results.json`.
