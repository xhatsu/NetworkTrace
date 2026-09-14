# TASK: Push real user trace data through production ingestion and verify the user-analysis system end-to-end against ClickHouse

Push the canonical real trace dataset into the LIVE TraceScope deployment, then prove the user-analysis pipeline (principal extraction → ClickHouse persistence → user intelligence APIs) works correctly.

## Environment facts

- Live ingest (proven working, currently NO API key required): `POST https://trace.n2d.id.vn/api/v1/ingest` (aliases `/api/v1/ingest/traces`, `/api/ingest`). Bounded coalescing writer: 429 + `Retry-After: 1` on saturation — honor it with backoff. `X-Batch-Id` dedup is active — send unique batch IDs per chunk.
- Dataset: `/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz` (2,000,000 OTel spans, 15 microservices, 55 edges, 151,610 labeled anomaly spans) + ground truth `data/otel_traces_2m_manifest.json`.
- Existing shipper: `/home/ubuntu/Viettel/NetworkTracing/push-data-to-hub.py` (built to stream this exact dataset; targets the old `/v1/traces` hub path — check and retarget to the current ingest endpoint, or write a small pusher script in `/tmp` if simpler).
- Generator (if needed): `/home/ubuntu/Viettel/NetworkTracing/generate-otel-traces.py` + `otel_generator/` package.
- Analytics worker runs on a 60s cadence — rollups/baselines/anomalies/user intelligence materialize in waves after ingest.
- 3 old synthetic probe traces exist in ClickHouse (trace_id `254f60cb…`, service/operation `unknown`, anonymous) — ignore them, do not attempt deletion.

## Workflow

1. **Inspect first (gate decision):**
   - Sample the jsonl.gz (zcat | head). Determine whether spans carry user/principal identity fields (e.g. basic-auth user, `user_name`, `principal`, identity attributes) that TraceScope's principal extractor (`backend/app/services/principal_extractor.py` — read it to see exactly what it consumes) can extract.
   - **If identity IS present:** proceed with the real 2M dataset.
   - **If identity is ABSENT:** the user system would only ever see `-anonymous-` and the test is meaningless. Then use the project's own canonical generator (`generate-otel-traces.py`, check its CLI flags for identity/auth enrichment) to produce a dataset WITH user identities (200k–500k spans, a few hours window, several realistic users hitting multiple services), and push that instead. State clearly in the report which path you took and why.
2. **Push:** start with a bounded subset (~250k spans) through the live public ingest endpoint. Use HTTP keep-alive, 2–4 threads max, honor 429/Retry-After, unique `X-Batch-Id` per chunk. Track: sent / acked / rejected / 429 count / duration / throughput. Spot-verify a few pushed trace_ids via `GET /api/v1/traces/{id}` mid-push. If throughput is healthy and time permits, continue toward the full dataset; otherwise report the partial.
3. **Wait for analytics:** after the push completes, wait 2–3 worker cycles (~2–3 min), then verify.
4. **Verify user analysis (the actual goal):** via the public API:
   - `GET /api/v1/users` — inventory non-empty, plausible distinct-user count.
   - `GET /api/v1/users/{top-user}` — profile: target services, operations, hourly activity consistent with the pushed data.
   - `GET /api/v1/user-graph` — nodes/edges populated; edges consistent with caller→target relationships in the dataset.
   - `GET /api/v1/user-analytics` — totals (total_principals, active_24h) sane vs pushed data.
   - `GET /api/v1/user-changes` — check whether novel-user/new-IP detectors fired for the newly seen users (this is the user_new_source_ip / ip_new_user machinery from docs/ANOMALIES.md).
   - `GET /api/v1/overview` + `/api/v1/ingestion/status` — total_requests / events / traces counters consistent with records acked; `writer_alive: true`.
   - `GET /api/v1/anomalies` — anomalies materializing from the dataset's labeled anomaly spans (ground truth: 151,610 spans across families — compare detected incident counts by family, tolerance for worker cadence and windows).
5. **Cross-check against ground truth:** use `otel_traces_2m_manifest.json` (or generator output stats) as expected values: distinct services, edges, user counts, anomaly-span families. Report expected vs observed with % match.

## Constraints (hard)

- Do NOT run helm/kubectl mutations of any kind (no exec, no delete, no scale, no port-forward).
- Do NOT drop/truncate/alter ClickHouse tables or data. Read-only interaction with persisted data.
- Do NOT modify code in either repo. Temp scripts go in `/tmp` only.
- The public endpoint currently accepts unauthenticated writes (known config gap). Do not attempt to extract, guess, or set any API key.
- Keep total push volume sane: if effective throughput < ~200 spans/s after tuning, stop at the 250k subset and report rather than grinding for an hour.
- Do not DoS the tunnel: sequential-ish with modest concurrency, backoff on 429/5xx, cap runtime at ~35 minutes total.

## Deliverable

Write `USER_DATA_PUSH_TEST_REPORT.md` at `/home/ubuntu/Viettel/OtelTrace/`:
1. Path taken (real dataset vs generator-with-identities) and why.
2. Push stats table (chunks, records, acked, rejected, 429s, duration, avg throughput).
3. Verification table: check | expected (ground truth) | observed (API) | match % | verdict.
4. User-analysis deep-dive: top users found, their services/operations, graph shape, detector firings (user-changes), anomalies by family vs labeled ground truth.
5. ClickHouse persistence evidence (counter deltas, trace-id lookups).
6. Issues found (severity + evidence) and overall verdict: does the user-analysis system work end-to-end with ClickHouse?
Real outputs verbatim; never fabricate; state anything untestable and why.
