# Principal-intelligence N+1 fix report

Execution date: 2026-09-14 UTC

## Outcome

The principal-intelligence stage now processes explicit 5,000-row pages, persists the existing composite `(ingest_order, row_uid)` checkpoint after every durably written page, and yields after a completed page when `OTEL_ANALYTICS_STAGE_BUDGET_SECONDS` is exhausted. The cursor query is narrow, readiness is one grouped query per page, derived state is held in a batch-local latest-row cache and block-inserted, behavioral events are deduplicated and block-inserted, and incident changes use coalesced replacement rows instead of synchronous mutations.

The complete 250,000-span scratch run finished the 135,934 principal-bearing rows in 118.899 seconds and 28.725006 ClickHouse CPU-seconds. The immediate no-new-row run took 0.030 seconds, processed zero rows, and left the checkpoint byte-for-byte unchanged.

## Implemented fixes

1. **Batch checkpoint and crash resume**
   - `backend/app/services/principal_relationships.py:826-860` reads the existing checkpoint with `FINAL`, retains every unknown/legacy JSON member, uses the established tuple cursor, flushes all derived rows for one page, and then appends the new checkpoint version before fetching another page.
   - No checkpoint is advanced while a page is being computed. A failure before the durable flush leaves downstream state and cursor unchanged. `tests/test_principal_fix.py:49-74` injects a mid-page exception, verifies the old checkpoint remains, resumes, verifies exact final counters, and verifies the next run processes zero rows.

2. **Readiness full-scan elimination**
   - `backend/app/services/behavioral_engine.py:143-213` separates the unchanged readiness decision rules from collection of their four aggregate inputs.
   - `backend/app/services/principal_relationships.py:272-286` runs one grouped trace aggregate for all principal IDs in a page. Every detector call in that page uses the cached tuple.
   - `tests/test_principal_fix.py:77-92` compares cached/grouped results with the legacy direct full-scan function for novelty, unusual-time, dormancy, and advanced detectors on identical trace data. Results match exactly.

3. **Grouped reads and batched derived writes**
   - `backend/app/services/principal_relationships.py:288-401` preloads principal, baseline, registry, candidate, dimension, relationship, source, hourly, and daily state in grouped page queries. Missing keys are seeded explicitly, so they do not fall back to row-at-a-time reads.
   - `backend/app/services/principal_relationships.py:429-544` applies rows sequentially to batch-local latest state, preserving first/last seen, observation/error/success counts, distinct-day/window promotion rules, and unique-dimension counts.
   - `backend/app/services/principal_relationships.py:546-600` emits one block insert per derived table/column shape. Behavioral events are reduced by their existing deterministic fingerprint dimensions and inserted as a block. Incident scoring is recalculated once per affected incident after the event block is durable.
   - `tests/test_principal_fix.py:95-106` verifies final principal, caller, target, relationship, and registry counts after a multi-row batch.

4. **Mutation-free incidents**
   - `backend/app/services/behavioral_engine.py:216-230` writes a complete replacement incident row.
   - `backend/app/services/behavioral_engine.py:316-374`, `:380-473`, and `:478-602` use `FINAL` reads, replacement inserts, and batch coalescing. The stage produces no `UPDATE incidents`, therefore the compatibility adapter cannot translate worker incident activity into `ALTER TABLE ... UPDATE ... mutations_sync=1`.
   - `backend/app/repositories/user_repository.py:295-310` applies the same replacement-row rule to operator incident status changes; `:316-356` reads incidents with `FINAL`, preserving API response shapes while making replacement visibility deterministic.
   - `tests/test_principal_fix.py:109-116` asserts both incident-writing paths contain no incident update statement and that readers use `FINAL`.

5. **Narrow cursor query**
   - `backend/app/services/principal_relationships.py:837-845` selects only the 20 columns consumed by incremental derivation instead of `SELECT *`; the tuple predicate and ordering are unchanged.
   - Cursor-query peak memory fell from 215,732,230 bytes in the production diagnosis to 29,937,636 bytes in the scratch run (7.21x lower). Peak memory across every scratch-stage query was 33,581,067 bytes.

6. **Budget yield**
   - `backend/app/services/principal_relationships.py:852-853` checks elapsed monotonic time only after derived blocks and the page checkpoint are durable, then returns control to the worker cycle.
   - `tests/test_principal_fix.py:119-134` forces a two-row page and an exhausted budget and proves progress occurs as `2, 2, 1, 0` across cycles, without skipping or replaying a completed page.

7. **Checkpoint compatibility**
   - The existing JSON object is modified in place only for `ingest_order` and `row_uid`; `bootstrap_cutoff_ms`, `ratio`, and unknown fields remain intact.
   - `tests/test_principal_fix.py:137-147` starts from a pre-existing legacy-compatible checkpoint and proves all non-cursor fields survive.

## Parity and equivalence evidence

| Contract | Evidence | Result |
|---|---|---|
| Readiness rules | Old aggregate-backed `evaluate_readiness` vs grouped cached tuple, four detector families | Exact tuple parity |
| Derived counters | Principal, caller, target, relationship, historical registry after block processing | Exact expected counts |
| Crash/resume | Injected exception before page flush, unchanged checkpoint, restart, empty subsequent run | No duplicated downstream state |
| Incident semantics | Existing behavioral/API suite plus mutation-free source assertion | API shapes and capped scoring preserved |
| Budget | Forced one-page yield over five pending rows | `2, 2, 1, 0`, no gap/replay |
| Legacy cursor | Existing checkpoint with extra field and non-default ratio | Preserved |

## 250k performance comparison

Method: a temporary local `clickhouse/clickhouse-server:24.8` container was bound to `127.0.0.1:8123`. A scratch database named `principal_fix_perf_20260914` was migrated, then the first 250,000 records from `/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz` were decoded with the canonical OTLP parser and inserted in 5,000-row blocks. A compatible cursor at zero forced the fixed incremental path across the full backlog. `system.query_log` was flushed and queried for `OSCPUVirtualTimeMicroseconds`, `read_rows`, and `memory_usage`. The scratch database was dropped in `finally`, its absence was verified (`0` matching databases), and the temporary ClickHouse container was removed.

Production values below are the fixed 15-minute diagnosis window. The fixed run completed the entire backlog, whereas production still had not completed the stage; the comparison therefore favors the production denominator.

| Metric | Production diagnosis | Fixed 250k run | Reduction |
|---|---:|---:|---:|
| Principal/derived query count | 80,966 | 3,545 | 22.84x |
| Total rows read | 1,630,724,788 | 31,136,760 | 52.37x |
| ClickHouse CPU-seconds | 295.142 | 28.725006 | 10.27x |
| Readiness query count | 6,399 row-level scans | 50 grouped page queries | 127.98x |
| Readiness rows read | 1,599,775,596 | 12,500,000 | 127.98x |
| Cursor-query peak memory | 215,732,230 bytes | 29,937,636 bytes | 7.21x |
| Peak memory, any stage query | not separately reported | 33,581,067 bytes | n/a |
| Backlog completion wall time | did not finish in the observed window | 118.899 s | n/a |
| Principal-bearing rows completed | partial/unknown | 135,934 | n/a |

Additional fixed-run output:

```text
loaded=250000
query_count=3545
read_rows=31136760
cpu_seconds=28.725006
peak_query_memory_bytes=33581067
grouped_readiness_queries=50
grouped_readiness_read_rows=12500000
grouped_readiness_peak_memory_bytes=9499206
cursor_queries=51
cursor_read_rows=12750000
cursor_peak_memory_bytes=29937636
processed=135934
events_final=14717
incidents_final=16
principals_final=8
wall_seconds=118.899
```

Steady state:

```text
second_result={'processed': 0, 'changes': 0, 'cursor': 1789380973566377042, 'bootstrap_cutoff_ms': 0}
second_wall_seconds=0.03
checkpoint_unchanged=true
```

The worker's built-in `_memory_snapshot` records before/after process-wide `MemoryTracking`, not a per-query peak and not ClickHouse query CPU. For an honest peak/CPU comparison, this report uses the same ClickHouse-native `system.query_log.memory_usage` and `ProfileEvents['OSCPUVirtualTimeMicroseconds']` evidence source used by the production diagnosis. No peak value was inferred from point-in-time snapshots.

## Test evidence

Baseline before changes, verbatim:

```text
123 passed in 271.54s (0:04:31)
```

Required new acceptance tests, verbatim:

```text
......                                                                   [100%]
6 passed in 8.42s
```

Final complete suite, verbatim:

```text
..................                [100%]
129 passed in 155.20s (0:02:35)
```

Python compilation and `git diff --check` also completed without output/errors. No Git mutation was performed.

## Deferred or excluded

- No deployment, documentation, frontend, schema, or unrelated worker-stage file was changed.
- Two preliminary benchmark attempts were excluded: one used the generic normalizer and produced anonymous principals; another exposed remaining lazy point reads and was stopped before completion. Their scratch database was dropped before each retry. Only the canonical-parser, grouped-preload run above is reported as performance evidence.
- The fixed workload still reads each 250,000-row trace set once per 5,000-row page for readiness because the accepted design is one grouped query per batch. A durable principal-history summary could remove those 12.5 million reads in a future schema change, but is not required for semantic parity and was intentionally not introduced here.
