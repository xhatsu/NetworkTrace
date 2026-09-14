# TASK: Complete design steps 2–5 (SQL aggregation follow-through)

You are completing phases 2–5 of `DESIGN_SQL_AGGREGATION.md` (repo root — architectural authority, read it FIRST). Step 1 is DONE and verified (SQL-side exact aggregation, byte cap, telemetry — see `SQL_AGGREGATION_REPORT.md`). Work the phases in order. This job may outlast one session: after EVERY phase, update `IMPLEMENTATION_PROGRESS.md` (repo root, create it) with per-item status (done/partial/blocked + evidence pointers) so a continuation run can resume exactly where you stopped.

## Current verified state

- Worktree dirty with all prior fix work — preserve it. NO `git commit`/`git add`/`git stash`.
- Test baseline: **114 passed** via `.venv/bin/python -m pytest tests/ -q` (local CH at `127.0.0.1:8123`).
- Aggregation: SQL-side exact `quantilesExact` nearest-rank-compatible, 6h aligned slices, `(ingest_order, row_uid)` cursor, checkpoints table, byte-capped writer, per-stage memory telemetry.
- Real dataset for measurements: `/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz` (production pushed its first 250,000 spans — use the same 250k as the production-representative sample).
- Live production still runs the OLD build; do NOT interact with production except zero writes. Everything here is repo + local CH.

## Phase 2 — Prove retry/crash correctness, measure cardinality, define late-data repair

1. **Dedup/retry proof suite** (the design gate for any future MV): tests that reproduce and assert correct behavior for: crash between trace insert and batch-marker insert (retry must repair, not lose, not duplicate — tests exist partially; extend to cover marker-insert failure mid-flight); client retry after successful commit but lost response; concurrent submissions with the same batch ID; the same span (same `dedup_key`) appearing in DIFFERENT batches (document current semantics — dedup or double-count — and make it explicit/consistent); a retry coalesced into a different insert block. Each test: deterministic, isolated temp DB.
2. **Cardinality measurement** (real numbers, not samples): load the 250k production-representative spans into a scratch DB; measure distinct 1m and 5m bucket keys vs raw rows, compression ratios, top-k dimension cardinalities (per caller/target/principal/operation). Write the numbers into the progress file — they decide whether serving aggregates (review §4) are justified.
3. **Late-data repair definition + implementation**: late span (event time inside already-aggregated buckets, ingested after cursor passed) must revise affected buckets and trigger re-evaluation where needed. Verify current behavior, add the missing trigger (e.g. revised-bucket markers the anomaly stage consumes), test: insert late span → next cycle recomputes only affected buckets → anomaly stage sees the revision. Also prove the cursor cannot skip late-visible records: `(ingest_order, row_uid)` is ingestion-ordered so late rows always sort after the cursor — assert this property in a test (rows inserted later have higher ingest_order even with old event time).

## Phase 3 — Aggregate states + retention in SHADOW tables; backfill

1. New migration `backend/clickhouse_migrations/003_aggregate_states_shadow.sql`: shadow table(s) `metric_buckets_agg` (AggregatingMergeTree) storing `sumState(count)`, `countIfState(error)`, `sumState(duration_ms)`, `quantilesTDigestState(0.5,0.95,0.99)(duration_ms)` with the SAME bucket key; plus optional smaller serving aggregates ONLY IF Phase 2 cardinality justifies them. TTL columns as the retention mechanism (raw `traces` TTL, buckets TTL, agent-stats TTL) — values from measured daily compressed growth on the scratch DB (report the measurement); put TTLs on shadow tables AND provide (but do not apply unilaterally to live tables beyond what migration 002 already does — note the deploy decision).
2. **Dual-write path**: aggregation writes BOTH the live exact path (current, unchanged) and the shadow state path, behind config flags (`OTEL_AGGREGATION_SHADOW_ENABLED`, default on in dev; cutover flag `OTEL_AGGREGATION_CUTOVER=false` default OFF). Backfill = replaying slices through the shadow path WITHOUT overlapping live contributions (separate shadow checkpoints).
3. **Percentile validation** (review §3): TDigest is approximate — on the 250k dataset, compare TDigest-merged p50/p95/p99 vs the exact nearest-rank values per bucket; report max relative error, especially tails (p99) on sparse buckets. Never average p95s — merging states only. Document error bounds honestly.

## Phase 4 — Cutover comparison (flag stays OFF; evidence gathered)

On the scratch DB with 250k spans: run both paths fully; compare per the review — total request counts, error counts, latency estimates (p50/p95/p99 deltas), dashboard-shaped queries (topology/services/principals reads), anomaly outputs (detect on both bucket sets). Produce a comparison table with exact deltas. Verdict + recommendation (cutover ready / not ready + why). Do NOT flip the default.

## Phase 5 — Serving queries + decoupled worker schedules

1. **Benchmarks first**: representative dashboard queries (topology graph, service detail, principal profile, overview KPIs) — FINAL vs argMax-tuple vs GROUP-BY variants on the 250k scratch DB; record timings. Rewrite selectively ONLY where the benchmark shows a real win and correctness is preserved (complete logical bucket key, unambiguous version ordering). Leave correct-but-slow queries alone if the win is marginal.
2. **Independent per-stage checkpoints & cadences**: each stage gets its own checkpoint + budget; aggregation every cycle; baselines on a slower configurable cadence (changed series only); anomalies triggered by newly completed/revised buckets; principal intelligence unchanged. Deterministic anomaly IDs so re-evaluation updates existing events instead of duplicating (id from detector+dimensions+window; test retry → same id → update not duplicate).

## Hard constraints

- NO git commit/add/stash; preserve worktree; no deploy/, no docs/, no frontend/ changes (serving-query rewrites are backend only); .md writes limited to IMPLEMENTATION_PROGRESS.md + final COMPLETION_REPORT.md (+ migration SQL).
- Do not weaken/skip tests. No new Python dependencies.
- Schema additions allowed ONLY as new migration files; live-table semantics unchanged while `OTEL_AGGREGATION_CUTOVER=false`.
- Keep 114 tests green at every phase boundary (they must pass before you update progress to "phase done").
- Scratch DBs dropped after measurement; cleanup proven.

## Deliverables

- `IMPLEMENTATION_PROGRESS.md` — running status, updated after each phase.
- `COMPLETION_REPORT.md` — per-phase: what/why/evidence (verbatim test lines, benchmark tables, cardinality numbers, TDigest error table, cutover comparison table), deferred items, deploy notes (which env vars/migrations the operator must apply, TTL values + measured justification, cutover decision left to operator).
- Verbatim final pytest line. Honest reporting: blocked/partial items stay marked as such.
