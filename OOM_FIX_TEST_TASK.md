# TASK: Prove the OOM fix works under the exact production failure condition

Codex just refactored `aggregate_traces` (uncommitted in this worktree) to eliminate the ClickHouse code-241 failure. Your job: empirically prove the fix holds under a faithful reproduction of the production condition — 250k traces spanning ~8.8 days against a 1.8 GiB ClickHouse memory ceiling — and verify rollups/anomalies actually materialize afterward.

## Environment facts

- Local ClickHouse: `http://127.0.0.1:8123` (no auth). It also serves unrelated live telemetry (db with port:80 shipper rows) — do NOT touch other databases; use a dedicated scratch database and clean it up after.
- Dataset: `/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz` (production push used its first 250,000 spans; timestamps span ~8.8 days — that spread matters, reproduce it).
- The fix is in THIS worktree (uncommitted). The pre-fix code is at `HEAD` — `git archive HEAD` / `git show HEAD:backend/app/services/aggregation.py` gives you the old version without touching the worktree.
- Repo venv: `.venv/bin/python`. Test suite must stay green: `.venv/bin/python -m pytest tests/ -q` (113 expected).
- Production (for a read-only baseline check only): `GET https://trace.n2d.id.vn/api/v1/ingestion/status` and `/api/v1/anomalies` with UA `TraceScope-Verify/1.0` — confirms the stall still exists there (expect job failed / empty anomalies). No other prod interaction.

## Test plan

1. **Baseline read of prod** (1-2 requests, read-only): record current worker job status + anomalies count.
2. **Build the reproduction**: create scratch ClickHouse database (e.g. `oomtest_$$`), apply the repo migrations to it (use the repo's own migration/StorageRepository tooling), load 250,000 spans from the dataset into its traces table using the repo's own ingest/normalization path (a small script in /tmp is fine — mirror what `/tmp/push_to_production.py` did but write into the scratch DB directly to skip HTTP).
3. **Enforce the ceiling**: run the aggregation with the same effective limit as prod — CH setting `max_memory_usage=1932735283` (1.8 GiB) applied to the aggregation connection (check how `db_context.py` opens connections and apply the setting via query SETTINGS or a profile — read the code to pick the cleanest injection point; a test-only wrapper script in /tmp is acceptable).
4. **Old code control (A/B)**: copy the pre-fix `aggregation.py` (from `git show HEAD:...`) into a throwaway /tmp repo copy or monkeypatch module and run the same workload — expect and RECORD the code-241 failure. If the old code needs too much scaffolding to run in isolation, say so and skip the control with justification.
5. **Fixed code run**: run the FIXED worker (`python -m backend.worker --once` pointed at the scratch DB) with the ceiling enforced. Record per-stage outcomes. Expect: bootstrap completes via 6h slices with no 241; rollup/baseline/anomaly/principal stages all succeed.
6. **Verify outputs**: in the scratch DB (and via a direct repository call if cleaner): metric_buckets populated with exact p50/p95/p99, baselines present, anomaly events > 0 (the subset contains labeled anomalies), checkpoints table showing the composite cursor at the high-water mark. Re-run worker `--once` a second time — steady-state cycle should be fast and process 0 new rows (idempotence + cheap steady state).
7. **Late-arrival test**: insert a handful of rows with timestamps inside already-aggregated buckets after the first run; re-run; verify the affected buckets were recomputed and cursor still correct.
8. **Suite**: full pytest run — 113 green.
9. **Cleanup**: DROP the scratch database; remove /tmp scripts. Prove cleanup (SHOW DATABASES after).

## Constraints (hard)

- NO `git commit`/`git add`/`git stash`; the worktree stays untouched (read-only except nothing — you should not need to modify any repo file).
- Do NOT touch databases other than your scratch one; no helm/kubectl; no writes to production beyond the 2 read-only GETs.
- If the host ClickHouse is memory-tight, prefer running the scratch workload against it carefully (250k rows is small) — do not install a second ClickHouse.
- Cap total runtime ~30 min; if the 250k load is slow through the repo path, load via direct INSERT in chunks instead and note it.

## Deliverable

Write `OOM_FIX_TEST_REPORT.md` at repo root:
1. Prod baseline (stall confirmed, verbatim job status).
2. A/B result: old code → verbatim code-241 failure (or skip justification); fixed code → stage-by-stage success.
3. Output verification table (buckets/baselines/anomalies/cursor values).
4. Steady-state re-run evidence (rows processed=0, duration).
5. Late-arrival recompute evidence.
6. Pytest final line verbatim.
7. Cleanup proof + any caveats.
Real outputs only; never fabricate; state anything not testable and why.
