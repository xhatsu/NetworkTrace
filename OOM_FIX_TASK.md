# TASK: Fix the worker OOM failure (ClickHouse code 241) in aggregate_traces

## Problem (verified live in production)

The `tracescope-worker` analytics cycle fails deterministically every 60s:

```
behavioral-observability: failed
Received ClickHouse exception, code: 241
Memory limit (total) exceeded: would use 1.81 GiB, maximum: 1.80 GiB
```

- The deployed ClickHouse container has a 2Gi memory limit (CH self-caps ~90% = 1.80 GiB). This is an infrastructure constraint we are NOT changing — your fix must make the code work within it.
- Failure is in the `aggregate_traces` stage (`backend/app/services/aggregation.py`): it scans the full unbounded trace window (currently 250k rows spanning ~8.8 days, growing daily) in one query, so rollups never materialize → `rebuild_baselines` and `detect_anomalies` (later stages in `backend/worker.py:41-44`) never run → `/api/v1/anomalies`, baselines, and all rollup-fed dashboard views are starved.
- Ingestion and user intelligence are unaffected (separate paths) — do not touch them.

## Required fix

Window-slice the aggregation so no single query ever needs >1 GiB:

1. Read `backend/app/services/aggregation.py`, `backend/app/repositories/aggregate_repository.py`, `backend/app/services/baseline.py`, `backend/app/services/anomaly_detection.py`, and `backend/app/services/principal_relationships.py` first (the last one already implements the incremental composite-cursor pattern — `(ingest_order, row_uid)` — reuse that established approach/timezone conventions where applicable).
2. Refactor `aggregate_traces` to process bounded time slices (e.g. 24h, or row-count-bounded chunks) in a loop, persisting each slice's rollups before moving to the next. Prefer a persisted watermark/cursor so each 60s worker cycle only processes NEW rows since the last successful slice (like `process_principal_intelligence` does), making steady-state cycles cheap and the initial 250k-row bootstrap just a longer one-time loop.
3. Slice boundaries must align so minute/5-minute rollup buckets are never split across slices incorrectly — compute buckets per slice correctly at the edges.
4. Do not change the rollup output schema or the shape of data written to ClickHouse tables (downstream consumers depend on it). Do not modify `deploy/` — the helm memory bump is handled separately by the operator.
5. Optional hardening if cheap: set a conservative `max_memory_usage`/`max_execution_time` setting on the aggregation queries as a second line of defense.

## Constraints (hard)

- NO `git commit`, NO `git add`, NO `git stash`. Edit in place. The worktree is intentionally dirty with prior fix work — preserve it.
- Do not modify: `.venv/`, `frontend/node_modules/`, `.git/`, `.hermes/`, `deploy/`, `docs/`, or the existing `FIX_REPORT.md`/report files.
- Do not weaken or skip existing tests.
- Tests run against the local ClickHouse on `127.0.0.1:8123` via the repo venv: `.venv/bin/python -m pytest tests/ -q`. Get a baseline first; keep the existing 111 green.

## Deliverable

Write `OOM_FIX_REPORT.md` at repo root:
1. Root cause in one paragraph (why the query exceeds 1.8 GiB).
2. Approach: slicing/cursor design, how bucket-boundary correctness is preserved, steady-state vs bootstrap behavior.
3. Files changed.
4. Verbatim pytest baseline vs final summary lines.
5. Any caveats (e.g. remaining memory risk at much larger backlogs, interaction with the operator's future helm memory bump).
Honest reporting; real outputs only.
