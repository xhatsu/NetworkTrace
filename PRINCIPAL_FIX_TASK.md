# TASK: Fix the principal-intelligence N+1 storm (the measured ClickHouse CPU cause)

Read FIRST: `CH_CPU_DIAGNOSIS.md` (repo root) — the production diagnosis you are fixing. Authority for context: `DESIGN_SQL_AGGREGATION.md` §5 (stage independence/budgets) and the established composite-cursor pattern.

## The measured problem (production evidence, 15-min window)

With zero web traffic, `process_principal_intelligence` dominated ClickHouse CPU:
- `evaluate_readiness()` (`backend/app/services/behavioral_engine.py:160-164`) runs a **full-table aggregate over `traces` per processed trace** — measured 6,399 full scans/15 min, 1.6B rows read, 117.5 CPU-s.
- The row loop (`backend/app/services/principal_relationships.py:432-458`): `SELECT *` batches of 10,000 sorted by `(ingest_order,row_uid)`, then `_process_incremental_row()` per trace issuing point reads, four FINAL count refreshes, per-row derived INSERTs, and synchronous `ALTER TABLE incidents UPDATE ... SETTINGS mutations_sync=1` mutations (7,851 mutations + 25,671 new parts + 5,133 merges/15 min).
- The checkpoint is saved ONLY after the entire backlog loop → any restart replays the whole 250k-row storm.

## Required fixes (aligned with diagnosis recommendations 1–5)

1. **Batch-bounded processing with per-batch checkpoints**: after each durably persisted batch (derived writes committed), advance and save the `(ingest_order, row_uid)` checkpoint BEFORE processing the next batch. A restart must resume from the last completed batch, never replay. Test: simulated mid-batch crash → restart → exactly-once downstream state, no reprocessing.
2. **Kill the readiness full-scan**: replace per-row full-table aggregates with per-principal readiness computed once per principal per cycle (cache the aggregate result for the batch — principals repeat heavily within a batch), or one grouped query per batch covering all its principals. Semantics of the readiness decision (novel/known per dimension) must be preserved exactly — parity test: old full-scan result vs new cached/grouped result on the same data.
3. **Batch derived writes**: accumulate relationship/candidate/change rows in memory and insert in blocks (e.g. per batch or per N rows), not per row. Same final table state.
4. **No synchronous mutations**: replace `ALTER TABLE incidents UPDATE ... SETTINGS mutations_sync=1` with versioned ReplacingMergeTree-style inserts (bump a version column, deterministic logical key already exists) OR coalesce updates once per incident per batch. Readers must already use FINAL (verify) or be updated where needed. No behavior change visible in API responses.
5. **Narrow the cursor query**: replace `SELECT *` with the explicit column list actually consumed by `_process_incremental_row()`; keep the composite cursor predicate. Verify memory drop (report peak memory before/after from the worker telemetry).
6. **Stage budget honored**: the principal stage must respect `OTEL_ANALYTICS_STAGE_BUDGET_SECONDS` — on budget expiry, stop after the current batch (checkpoint saved) and yield to the next cycle. No more multi-hour monopolization.

## Hard constraints

- NO git commit/add/stash (the repo was just committed by a prior job — build on HEAD as-is, leave your changes uncommitted).
- Preserve all existing behavior contracts: checkpoint format compat (a pre-existing checkpoint in the `checkpoints` table must be honored, not discarded — test it), API response shapes, user-changes/incidents semantics, deterministic anomaly IDs.
- Do not touch: `deploy/`, `docs/`, `frontend/`, other worker stages (aggregation/baselines/anomalies — their recent work stays).
- Keep the suite green: `.venv/bin/python -m pytest tests/ -q` (baseline: 123 passed at HEAD). Add tests for: crash-resume exactly-once, readiness parity, batched-write equivalence, mutation-free incident updates, budget yield.
- Local ClickHouse at `127.0.0.1:8123` for tests. Scratch DBs dropped after use.

## Performance evidence (required in report)

On a scratch DB loaded with the 250k production-representative dataset (`/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz` first 250,000 spans — mirror the loading approach from `OOM_FIX_TEST_REPORT.md`):
1. Run the fixed principal stage once over the full backlog: total wall time, CPU-s via worker telemetry, peak CH memory, and the query-log scan count for the readiness shape (must be ~#principals, not #traces).
2. Compare against the measured production numbers (6,399 scans, 1.6B rows, 295 CPU-s/15min) — report the reduction factor.
3. Second run (no new rows): near-zero work, checkpoint unchanged.

## Deliverable

Write `PRINCIPAL_FIX_REPORT.md` at repo root: per-fix approach + file:line, parity/equivalence evidence, performance table (before/after), verbatim pytest lines, checkpoint-compat note, and anything deferred. Honest reporting; real outputs only.
