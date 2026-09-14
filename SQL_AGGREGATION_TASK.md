# TASK: SQL-side aggregation for the analytics worker (Phase 1 of DESIGN_SQL_AGGREGATION.md)

The operator has supplied a design review at `DESIGN_SQL_AGGREGATION.md` (repo root). Read it FIRST — it is the architectural authority for this task. Your scope is its **"Recommended delivery sequence" step 1** only: SQL aggregation over bounded windows, byte-based queue limits, and memory monitoring. Steps 2–5 (dedup proof, shadow tables, aggregate-state cutover, serving-query optimization) are explicitly OUT of scope — do not start them.

## Current state of this worktree (verified)

- The worktree is intentionally dirty with prior fix work — preserve it. NO `git commit`/`git add`/`git stash`.
- `backend/app/services/aggregation.py` was recently refactored (uncommitted) to compute percentiles in Python over 6h-aligned slices with a persisted composite cursor `(ingest_order, row_uid)` in the `checkpoints` table. It passes: 113/113 tests, and an A/B live test (`OOM_FIX_TEST_REPORT.md`) proved 250k rows / 8.8 days aggregate in ~3.1s bootstrap, 13ms steady state, under a 1.8GiB ClickHouse ceiling.
- The problem it still has (per the design review §1): **raw duration samples still cross ClickHouse→Python** and percentiles are computed in Python. The A/B test enforced `max_memory_usage` on the CH connection but Python-side memory is still O(rows-in-window). The design review directs: move the GROUP BY and percentile computation into SQL; return only completed bucket rows to Python.

## Your scope (design review step 1)

1. **SQL aggregation core**: rewrite `aggregate_traces` so each bounded window/slice computes rollups entirely in ClickHouse SQL — `GROUP BY` bucket keys with `count()`, `countIf(error)`, `sum(duration_ms)`, and exact percentiles via `quantilesExactInclusive(0.5, 0.95, 0.99)(duration_ms)` (or `quantiles(0.5,0.95,0.99)` — decide and DOCUMENT which matches the existing interpolated Python `percentile()` definition closest, with a small validation test comparing SQL output vs the old Python function on a fixed dataset). Python receives only completed bucket rows.
2. **Preserve the proven cursor/slice architecture**: keep the `(ingest_order, row_uid)` watermark, 6h five-minute-aligned slice bounds, bucket-boundary correctness, late-arrival affected-bucket recompute, and checkpoint resume semantics from the current implementation. Change WHERE the math happens, not the recovery model. Read the current `aggregation.py` carefully and reuse its structure.
3. **Memory safety on both sides**:
   - CH side: apply a conservative `SETTINGS max_memory_usage` / `max_bytes_before_external_group_by` to the aggregation queries (headroom for merge phase — review §1). Values via config/env with sane defaults, not hardcoded magic numbers scattered in code.
   - Python side: no code path may accumulate raw duration lists anymore. Assert this structurally (e.g. the only rows fetched are grouped bucket rows).
4. **Byte-based queue limits** (review step 1, second item): the ingest writer currently bounds by record count (`OTEL_INGEST_TRANSACTION_RECORDS=50000`). Add a byte-based cap so one huge span can't blow the coalesced insert block (e.g. env `OTEL_INGEST_MAX_BATCH_BYTES`, enforced when accumulating requests in `backend/app/services/ingest_writer.py`, default ~32MiB, flush early when exceeded). Keep existing behavior for record-count bound.
5. **Worker/CH memory monitoring** (review step 1, third item): the worker already logs stage timings as JSON events; extend the per-stage completion event with lightweight memory telemetry: CH `system.metrics`/`system.events` peek (e.g. memory tracking metric) + Python `resource.getrusage(RSS)` before/after each stage. Log-only — no alerting infra.
6. **Cardinality guardrail** (review §4, minimal): after writing buckets, log the measured compression ratio (distinct bucket keys vs raw rows in the window) per slice at debug/info level. No new tables, no serving aggregates yet.

## Hard constraints

- Do NOT introduce materialized views, AggregatingMergeTree/TDigest state tables, retention TTLs, or any new tables except none are expected (schema stays as-is). Those are later phases.
- Do NOT change the `metric_buckets` output schema or row semantics — downstream readers (`principal_repository`, `topology_repository`, `aggregate_repository` queries) must keep working unchanged.
- Do NOT modify `deploy/`, `docs/`, `frontend/`, or any `*.md` except writing the deliverable report.
- Do not weaken/skip tests. No new dependencies.
- Percentile semantics decision must be evidenced: include a test that runs both the old Python `percentile()` (copy it into the test as reference) and the new SQL path on a deterministic synthetic dataset and asserts equality (or documents exact divergence bounds with the chosen quantile function).
- If SQL-side exact quantiles for a 6h slice still risk the CH memory ceiling at extreme cardinality, state the measured/estimated bound honestly in the report rather than hiding it.

## Testing

- `.venv/bin/python -m pytest tests/ -q` — baseline is 113 passed. Keep it green; add tests for: SQL-vs-Python percentile parity, byte-cap flush behavior in the writer, slice processing unchanged cursor semantics.
- Local ClickHouse available at `127.0.0.1:8123` for tests (repo venv has clickhouse-connect).

## Deliverable

Write `SQL_AGGREGATION_REPORT.md` at repo root:
1. Chosen quantile function + parity evidence vs the old Python definition.
2. What moved into SQL / what Python still does.
3. Byte-cap design (env var, default, interaction with record cap).
4. Memory telemetry sample output (verbatim one worker cycle).
5. Compression-ratio observation on the test data.
6. Verbatim pytest baseline vs final lines.
7. Explicitly out-of-scope items you noticed but did not touch (for the next phase).
Honest reporting; real outputs only.
