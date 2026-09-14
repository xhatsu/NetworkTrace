# SQL Aggregation Delivery Completion Report — Phases 2–5

Authority: `DESIGN_SQL_AGGREGATION.md`. Execution contract: `PHASES_TASK.md`.
Completed locally on 2026-09-14 against ClickHouse 24.8 and the first 250,000
records of `/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz`.

## Outcome

Phases 2 through 5 are implemented and tested in order. The exact live aggregation
path remains the serving path. `OTEL_AGGREGATION_CUTOVER` defaults to `false` and was
false in every measurement. The shadow path is suitable for continued comparison,
but the cutover recommendation is **not ready** pending a caller/principal-rich data
window, explicit approximation tolerances, and retention capacity approval.

No git add/commit/stash operation was used. No deployment, docs, or frontend file was
changed by this delivery. The pre-existing dirty worktree was preserved. All scratch
databases were dropped; the final query for names matching `sqlagg_phase%` or `test_%`
returned `[]`.

## Phase 2 — retry correctness, cardinality, and late repair

### Retry/crash gate

The deterministic isolated-DB proof suite now covers all required cases:

| Case | Proven behavior |
|---|---|
| Trace insert succeeds, batch-marker insert fails | First request fails; retry finds raw `ingest_batch_id`, repairs marker, inserts zero duplicate rows |
| Marker failure for multiple coalesced jobs | Every marker is repaired; raw and marker counts remain one per batch |
| Commit succeeds, response is lost | Retried batch returns duplicate with one durable raw row |
| Concurrent same batch ID | Exactly one request is admitted; all others return duplicate |
| Same `dedup_key`, different batch IDs | Explicit current contract: stored/counted twice; batch ID is the idempotency boundary |
| Retry enters a different coalesced block | Retry returns duplicate; companion request commits normally |

The different-batch assertion is `(rows, unique dedup keys, unique batch IDs) =
(2, 1, 2)`. This deliberately preserves live at-least-once cross-batch semantics. The
shadow path reads the same raw rows, so it remains consistent with exact counts.

Focused proof line:

```text
19 passed in 53.95s
```

### Cardinality and measured storage

The full 250,000-record production-representative slice was loaded, not sampled.
Its event-time extent was 1,799,982 ms (about 30 minutes).

| Measurement | Result |
|---|---:|
| Raw rows | 250,000 |
| Detailed one-minute keys | 6,837 |
| Raw-to-one-minute compression | 36.57:1 |
| Detailed five-minute keys | 4,135 |
| Raw-to-five-minute compression | 60.46:1 |
| Combined detailed rows | 10,972 |
| Raw-to-combined compression | 22.79:1 |
| Distinct caller / target / principal / operation | 0 / 15 / 1 / 941 |
| Raw compressed / uncompressed storage | 51,981,606 / 117,839,243 bytes |
| Exact buckets compressed / uncompressed storage | 383,232 / 1,718,394 bytes |
| Extrapolated raw compressed growth | 2.495 GB/day (2.324 GiB/day) |
| Extrapolated exact-bucket growth | 18.4 MB/day |

Top target volumes were session-cache 64,308, api-gateway 49,689,
catalog-service 37,753, notification-service 19,173, and cart-service 11,412.
The only caller value was empty, the only principal was `unknown`, and operation was
the cardinality driver with 941 values. This supports retaining the detailed rollup
without creating speculative smaller serving aggregates.

### Late-data repair

The existing composite cursor is ingestion ordered. A test inserts a span after the
cursor with older event time and proves `(ingest_order,row_uid)` advances, the one
affected historical slice is recomputed, and no subsequent cycle reprocesses it.
Every completed/revised five-minute replacement writes a durable
`aggregation-revised` marker to the existing `dirty_buckets` table. The anomaly stage
processes marked event-time windows and deletes markers only after successful
evaluation, so a detector failure remains retryable.

### Phase-2 boundary

```text
.................                          [100%]
119 passed in 173.62s (0:02:53)
```

## Phase 3 — mergeable shadow states, retention, and backfill

### Migration and state model

New migration `backend/clickhouse_migrations/003_aggregate_states_shadow.sql` creates
`metric_buckets_agg` with `AggregatingMergeTree` and the complete live logical key.
It stores:

- `sumState(toUInt64(1))` request state;
- `countIfState(UInt8 error predicate)` error state;
- `sumState(Float64 duration_ms)` latency-sum state;
- `quantilesTDigestState(0.5,0.95,0.99)(Float64 duration_ms)` percentile state.

The table has a materialized `bucket_time` and 90-day TTL. No incremental materialized
view was added. Late/repeated slice processing synchronously removes old shadow states
for the bounded event-time interval before inserting recomputed states, preventing
additive double counting.

`OTEL_AGGREGATION_SHADOW_ENABLED` defaults true for development comparison. The exact
path and shadow path are both written, but no reader uses shadow merely because it is
populated. `OTEL_AGGREGATION_CUTOVER=false` remains the default.

Backfill has its own `aggregation_shadow_cursor`. On the 250k data it processed one
aligned slice; immediate replay processed zero. Request totals remained 250,000 for
both 60s and 300s states, with 1,920 errors at each grain. Shadow storage was
1,513,907 compressed bytes and 3,374,786 uncompressed bytes for 10,972 rows—larger
than the exact bucket table on this short dataset.

### Retention decision data

The proposed values are raw 30 days, buckets/shadow 90 days, and agent history 1 day.
Migration 002 already applies the one-day agent history TTL. Migration 003 applies
the TTL only to the new shadow table and provides the live raw/bucket DDL as comments,
so an operator must explicitly approve and apply those live-table policies. At the
measured rate, 30 raw days project to about 74.9 GB compressed and 90 exact-bucket
days to about 1.66 GB, before ClickHouse merge and free-space headroom. Principal
first-seen/baseline tables are not tied to raw retention.

### TDigest versus exact nearest-rank

The reference is the exact `quantilesExact` path using the already-proven levels that
match `ceil(n*q)-1`. All 10,972 keys joined one-to-one. Count mismatches: 0. Error
mismatches: 0. The maximum latency-sum delta was 0.005000001 ms because exact live
sums are stored to two decimals.

| Grain / percentile | Buckets | Max absolute error | Max relative error | 95th-rank absolute error |
|---|---:|---:|---:|---:|
| 60s p50 | 6,837 | 7.656206 ms | 1.804117% | 0.001000 ms |
| 60s p95 | 6,837 | 0.001011 ms | 0.049748% | 0.000005 ms |
| 60s p99 | 6,837 | 0.001013 ms | 0.049748% | 0.000007 ms |
| 300s p50 | 4,135 | 21.444922 ms | 1.632302% | 0.007110 ms |
| 300s p95 | 4,135 | 4.009863 ms | 1.032798% | 0.000003 ms |
| 300s p99 | 4,135 | 0.001013 ms | 0.048779% | 0.000003 ms |
| 60s p99, at most 5 samples | 5,535 | 0.001003 ms | 0.049748% | 0.000002 ms |
| 300s p99, at most 5 samples | 3,836 | 0.001003 ms | 0.048779% | 0.000002 ms |

No p95 values are averaged. Larger windows and serving shapes merge TDigest states.

### Phase-3 boundary

```text
..................                        [100%]
121 passed in 195.13s (0:03:15)
```

## Phase 4 — cutover comparison

Both paths ran fully on a fresh 250k scratch DB. A scratch-only compatibility table
allowed unchanged baseline and detector code to read the merged state results. No live
or repository serving source was redirected.

| Comparison | Exact | Shadow | Delta |
|---|---:|---:|---:|
| Complete logical keys | 10,972 | 10,972 | 0 |
| Request-count mismatches by key | 0 | 0 | 0 |
| Error-count mismatches by key | 0 | 0 | 0 |
| Maximum p50 difference | — | — | 21.444922 ms |
| Maximum p95 difference | — | — | 4.009863 ms |
| Maximum p99 difference | — | — | 0.001013 ms |
| Overview request / error totals | 250,000 / 1,920 | 250,000 / 1,920 | 0 / 0 |
| Overview average latency | 131.730503 ms | 131.730496 ms | -0.000007 ms |
| Overview max detailed p95 | 4,399.820000 ms | 4,399.819824 ms | -0.000176 ms |
| Service rows | 15 | 15 | 0 |
| Max service count/error delta | — | — | 0 |
| Max service displayed-latency delta | — | — | 0.000176 ms |
| Principal rows | 1 | 1 | 0 |
| Principal target / operation cardinality | 15 / 941 | 15 / 941 | 0 / 0 |
| Topology rows | 0 | 0 | 0 |
| Detector windows | 7 | 7 | 0 |
| Anomaly outputs / unique signatures | 4 / 4 | 4 / 4 | 0 |
| Only-exact / only-shadow anomaly signatures | 0 / 0 | 0 / 0 | 0 / 0 |

Verdict: **not cutover-ready**. Counts and observed anomaly outputs are encouraging,
but this slice has no resolved callers and only the `unknown` principal, so topology
and identity parity are not substantively exercised. TDigest tolerance and increased
state-storage cost also need operator approval. The default stays OFF.

### Phase-4 boundary

```text
..................                        [100%]
121 passed in 188.85s (0:03:08)
```

## Phase 5 — serving benchmarks and independent worker stages

### Benchmarks first

The scratch exact table contained two replacement versions per key: 21,944 physical
rows and 10,972 logical rows. Each query ran once for warm-up and 15 timed times with
ClickHouse query cache disabled. The exact alternative uses one whole metric tuple in
`argMax` ordered by unambiguous `tuple(created_at,id)` at the complete bucket key. The
state alternative groups the complete key and uses merge functions.

| Query | FINAL median / p95 | argMax tuple median / p95 | state GROUP BY median / p95 | Result |
|---|---:|---:|---:|---|
| Overview KPI | 10.163 / 11.483 ms | 20.076 / 26.560 ms | 34.017 / 53.247 ms | Keep FINAL |
| Topology graph | 10.207 / 11.508 ms | 8.935 / 12.365 ms | 7.864 / 29.861 ms | Empty result, no rewrite |
| Service detail | 10.633 / 18.028 ms | 13.504 / 20.718 ms | 19.900 / 30.332 ms | Keep FINAL |
| Principal profile | 10.937 / 33.388 ms | 21.388 / 31.187 ms | 28.283 / 51.350 ms | Keep FINAL |

Exact `argMax` output matched `FINAL` everywhere. State output was approximate for
non-empty latency shapes. No serving query was rewritten because no representative,
correctness-preserving real win was measured.

### Stage checkpoints, cadence, and budgets

- Aggregation runs every cycle with its independent `aggregation_cursor`, bounded
  slices, and ClickHouse memory/spill settings.
- Baselines have `worker_baselines`, a default 300-second cadence, a configurable
  100-series page, and a composite `(bucket_version,target_service)` cursor. Only
  changed targets are selected; their complete history is rebuilt.
- Anomalies have `worker_anomalies`, consume only newly completed/revised markers,
  and process at most a configurable 100 windows per cycle. Successful windows alone
  lose their markers.
- Principal intelligence retains its existing independent `principal_intelligence`
  cursor and bounded pages, as required.
- Every stage logs the default configurable 55-second budget and `budget_exceeded`.
  Baseline and anomaly work are unit-bounded; aggregation retains query/slice budgets;
  principal processing semantics remain unchanged.

Anomaly IDs are deterministic unsigned 64-bit BLAKE2b values derived from detector,
caller, target, principal, source IP, operation, and event-time window. Retry therefore
writes the same logical key. Repository reads use `FINAL`; the integration test writes
two evaluations and observes one logical row with the updated score.

Real one-shot worker evidence on 250k:

| Stage | Elapsed | Python max-RSS delta | ClickHouse MemoryTracking delta | Over 55s budget |
|---|---:|---:|---:|---|
| aggregate_traces | 0.767 s | 33,752 KiB | 17,107,606 B | false |
| rebuild_baselines | 0.147 s | 0 KiB | 862,678 B | false |
| detect_anomalies | 1.030 s | 0 KiB | 1,218,286 B | false |
| process_principal_intelligence | 0.242 s | 0 KiB | 2,394,032 B | false |

The cycle returned 6,837 one-minute buckets, 4,135 five-minute buckets, 971 baselines,
four anomalies, and zero principal changes for this identity-empty slice. All four
stage checkpoints existed, anomaly logical count equaled unique ID count at 4, and
pending revisions were 0.

### Phase-5 boundary and final pytest line

```text
..................                      [100%]
123 passed in 200.60s (0:03:20)
```

## Changed delivery files

- `backend/clickhouse_migrations/003_aggregate_states_shadow.sql`
- `backend/config.py`
- `backend/worker.py`
- `backend/app/services/aggregation.py`
- `backend/app/services/anomaly_detection.py`
- `backend/app/services/baseline.py`
- `backend/app/repositories/anomaly_repository.py`
- `tests/test_ingest_writer.py`
- `tests/test_analytics.py`
- `IMPLEMENTATION_PROGRESS.md`
- `COMPLETION_REPORT.md`

These files already coexist with substantial pre-task dirty changes; nothing was
reset, staged, stashed, or committed.

## Operator actions and honest deferrals

1. Apply migration 003 through the normal single schema-owner migration flow. Do not
   add an incremental materialized view; retry/correction semantics remain based on
   bounded raw recomputation.
2. Keep `OTEL_AGGREGATION_CUTOVER=false`. `OTEL_AGGREGATION_SHADOW_ENABLED=true`
   enables ongoing shadow evidence; disable it if the added write/mutation/storage
   cost is not acceptable.
3. Decide whether the observed TDigest errors satisfy product tolerances. Specifically
   review worst observed 300s p50 1.632302% and p95 1.032798%, not only p99.
4. Capture a longer comparison dataset containing resolved callers and principals
   before approving topology/identity cutover.
5. Capacity-plan merges and free-space headroom, then explicitly apply live raw 30-day
   and bucket 90-day TTLs if approved. This delivery does not apply them.
6. Configure, if needed: `OTEL_BASELINE_CADENCE_SECONDS` (300),
   `OTEL_BASELINE_SERIES_BUDGET` (100), `OTEL_ANOMALY_WINDOW_BUDGET` (100), and
   `OTEL_ANALYTICS_STAGE_BUDGET_SECONDS` (55).
7. Cross-batch span identity remains at-least-once: the same `dedup_key` in different
   batch IDs is counted twice. Changing that is a separate ingestion contract and
   backfill decision, not silently included here.

No item is hidden as complete: cutover, live raw/bucket TTL activation, topology and
resolved-principal parity, and any serving-query rewrite are explicitly deferred.
