# TASK: Diagnose why the ClickHouse service consumes high CPU with no web requests (report-only)

Production context: TraceScope deployed via helm in namespace `tracescope` (pods `tracescope-clickhouse-0`, `tracescope-app-0`, ingest deployment) behind `trace.n2d.id.vn`. The DEPLOYED build is still the OLD 0.2.0 image — the worktree's fixes are NOT deployed. The operator reports the ClickHouse pod eats significant CPU even when nobody is using the web UI. Find out why. REPORT ONLY — no fixes, no mutations, no restarts, no helm/kubectl write operations.

## Allowed access (read-only, evidence-gathering)

- `kubectl -n tracescope top pods`, `kubectl -n tracescope get pods`, `kubectl -n tracescope logs` (all pods, with `--since`/`--tail` bounds, NEVER dump unbounded logs)
- `kubectl -n tracescope exec tracescope-clickhouse-0 -- clickhouse-client --query "SELECT ..."` — SELECT/SHOW/system-table queries ONLY. No INSERT/ALTER/OPTIMIZE/KILL/DROP. Exception: `KILL QUERY` is permitted ONLY if you observe a specific runaway query actively degrading the service AND you report it first in your final report — otherwise just observe.
- Local host ClickHouse (`127.0.0.1:8123`) for comparison if useful.
- The repo (current worktree) for code context: `backend/worker.py`, `backend/app/services/aggregation.py`, `backend/app/services/ingest_writer.py`, `backend/clickhouse_migrations/*.sql`, helm templates.

## Investigation plan

1. **Quantify**: `kubectl top pods` sampled 3-4 times over ~3 minutes (note timestamps). Which pod, how many cores? Is it constant or spiky (correlate with the worker's 60s cadence)?
2. **Attribute inside ClickHouse** (via clickhouse-client):
   - `system.query_log` last 1-2 hours: top queries by `query_duration_ms`, `read_rows`, `memory_usage`, plus `query_kind`/`type` — group normalized query text. The old worker's unbounded aggregation query (timestamp-range scan over `traces` ending in code-241 MergeSortingTransform) is a PRIME suspect — every 60s it burns CPU until it dies. Prove or refute with query_log rows (count, avg duration, avg read_rows, ProfileEvents).
   - `system.metrics` / `system.events`: background merge pool activity, `BackgroundPoolTask`, `ReplicatedMerge*` n/a, merges per table via `system.merges` + `system.part_log` (last hours): parts written per table, merge frequency. Note `ingest_batches` has a 7-day TTL and `agent_stats_history` a 1-day TTL (migration 002) — TTL recompression/rewrite merges can churn.
   - `system.parts`: active parts per table — many small parts from continuous ingest → constant merge pressure. Correlate with actual ingest traffic: the fleet shippers POST to `:30103` continuously even with zero web users — ingestion + its merges may BE the "no requests" load.
   - `system.processes` at sample time: what is literally running during a CPU spike.
3. **Correlate with app/worker logs**: `kubectl logs tracescope-app-0 -c analytics-worker --since=30m` (bounded) — cycle starts, failures (code 241), stage timings. Match spike times to cycle starts.
4. **Check ingest path**: `kubectl logs deploy/tracescope-ingest --since=30m --tail=100` + `/api/v1/ingestion/status` via the public API (UA TraceScope-Verify/1.0) — are shippers actively pushing? Compare against ClickHouse insert rates in query_log/part_log.
5. **Ruling out**: CH container limits (`kubectl get pod tracescope-clickhouse-0 -o yaml` → resources), node pressure, and whether `system.query_log` even shows web-driven SELECTs (should be ~zero — confirm).

## Constraints

- READ-ONLY everywhere. No mutations to cluster, ClickHouse, or repo files (no git, no edits). Report-only deliverable.
- Bounded log pulls only. Polite pacing on kubectl exec SELECTs (system tables can be large — always add WHERE/LIMIT).
- Do not print secret values from any config you happen to see.

## Deliverable

Write `CH_CPU_DIAGNOSIS.md` at repo root:
1. CPU quantification (sampled numbers + timeline).
2. Attributed causes ranked by measured contribution, each with verbatim evidence (query_log aggregates, part counts, merge stats, log lines).
3. The causal chain in plain words (e.g. "worker retries doomed X-query every 60s: N attempts/hour × avg M s CPU" / "ingest writes P parts/min forcing Q merges").
4. Recommended fixes (ranked, NOT applied) with expected impact.
5. What you could not determine and why.
Real outputs only; every number traceable to a command you ran.
