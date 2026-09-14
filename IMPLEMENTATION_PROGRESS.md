# SQL Aggregation Delivery Progress

Architectural authority: `DESIGN_SQL_AGGREGATION.md`. Delivery task: `PHASES_TASK.md`.
The production cutover default remains OFF.

## Phase 2 — done

### 2.1 Dedup/retry proof gate — done

- `tests/test_ingest_writer.py` deterministically covers raw-trace commit followed by
  batch-marker failure, including a two-batch marker insert failure. Retry discovers
  the durable `ingest_batch_id`, repairs each missing marker, and inserts no new trace.
- A successful durable commit followed by a lost response is reproduced by discarding
  the first result and replaying the batch; replay returns duplicate with one raw row.
- Concurrent submissions with one batch ID remain covered and admit exactly one request.
- Current cross-batch contract is explicit: the batch ID is the idempotency boundary.
  The same `dedup_key` in two different batch IDs is stored and counted twice
  (at-least-once across batches), proven as `(rows, unique dedup keys, unique batch IDs)
  = (2, 1, 2)`. Live semantics were not changed.
- A replay placed in a different coalesced insert block returns duplicate and leaves one
  row for the original batch.
- Focused evidence: `19 passed in 53.95s`.

### 2.2 Real 250k cardinality and storage measurement — done

Source: first 250,000 records from
`/home/ubuntu/Viettel/NetworkTracing/data/otel_traces_2m.jsonl.gz`, loaded without
sampling into scratch database `sqlagg_phase2_250k`.

| Measurement | Value |
|---|---:|
| Raw rows | 250,000 |
| Event-time span | 1,799,982 ms (about 30 minutes) |
| Distinct detailed 1m keys / raw compression | 6,837 / 36.57:1 |
| Distinct detailed 5m keys / raw compression | 4,135 / 60.46:1 |
| Combined detailed rows / raw compression | 10,972 / 22.79:1 |
| Distinct callers / targets / principals / operations | 0 / 15 / 1 / 941 |
| Raw compressed / uncompressed bytes | 51,981,606 / 117,839,243 |
| Exact bucket compressed / uncompressed bytes | 383,232 / 1,718,394 |
| Raw compressed growth extrapolated at measured rate | 2.495 GB/day (2.324 GiB/day) |
| Exact bucket compressed growth extrapolated | 18.4 MB/day |

Top target volumes were session-cache 64,308; api-gateway 49,689;
catalog-service 37,753; notification-service 19,173; and cart-service 11,412.
The only caller was empty (250,000), the only principal was `unknown` (250,000),
and the largest operations were three browse/catalog/cache operations at 14,810 each.
Operation has 941 values and is the material cardinality driver. The detailed rollup
already compresses strongly, so phase 3 will not create speculative smaller serving
aggregates; phase 5 benchmarks will decide whether any serving shape merits one.

Scratch cleanup evidence: after `DROP DATABASE IF EXISTS sqlagg_phase2_250k`,
`SELECT count() FROM system.databases WHERE name='sqlagg_phase2_250k'` returned `0`.

### 2.3 Late-data repair — done

- Incremental discovery remains ordered by `(ingest_order,row_uid)`, independently of
  event time. A test inserts an older-event-time span after the cursor and proves the
  composite cursor advances while the old five-minute bucket is recomputed.
- Each successful five-minute replacement writes a durable `aggregation-revised`
  marker to the existing `dirty_buckets` table.
- `detect_revised_anomalies` evaluates marked event-time windows and deletes markers
  only after successful evaluation, making detector failure retryable.
- The test proves only the affected historical window is marked and observed by the
  anomaly stage.

### Phase boundary test

Command: `.venv/bin/python -m pytest tests/ -q`

```text
.................                          [100%]
119 passed in 173.62s (0:02:53)
```

## Phase 3 — done

### 3.1 Shadow states and retention — done

- New migration `backend/clickhouse_migrations/003_aggregate_states_shadow.sql`
  creates only the justified detailed-key `metric_buckets_agg` table using
  `AggregatingMergeTree`, `sumState(toUInt64(1))`, `countIfState(UInt8 error)`,
  `sumState(Float64 duration_ms)`, and
  `quantilesTDigestState(0.5,0.95,0.99)(Float64 duration_ms)`.
- `bucket_time` is a materialized TTL column and the shadow table applies a 90-day
  TTL. No smaller serving aggregates were created because phase-2 cardinality showed
  strong compression and phase 5 has not yet proven a query win.
- Retention proposal based on the measured rate is raw 30 days, buckets 90 days,
  agent history 1 day. Migration 002 already applies the agent-history TTL. Migration
  003 provides the raw/live-bucket DDL only as comments, so it cannot change live
  semantics without an operator deploy decision. At the measured rate, 30 raw days
  project to about 74.9 GB compressed and 90 exact-bucket days to about 1.66 GB,
  before merge and free-space headroom.

### 3.2 Flagged dual write and backfill — done

- `OTEL_AGGREGATION_SHADOW_ENABLED` defaults true for development comparison.
  `OTEL_AGGREGATION_CUTOVER` defaults false and no serving repository uses shadow
  while it is false.
- Every exact bounded slice is also recomputed into mergeable shadow states. Existing
  shadow rows for the event-time slice are synchronously deleted before replacement,
  preventing additive-state double counting when late data revises a bucket.
- `backfill_shadow_aggregates` uses the separate `aggregation_shadow_cursor` checkpoint.
  On the real data it processed one aligned slice; immediate replay processed zero.
  Both 60s and 300s merged request totals remained exactly 250,000, with 1,920 errors.
- Shadow storage for 10,972 state rows was 1,513,907 bytes compressed and 3,374,786
  bytes uncompressed. This is larger than exact rows on this dataset and is explicitly
  included in the capacity decision.

### 3.3 Real-250k TDigest validation — done

Reference is the live exact SQL path, whose `quantilesExact` levels preserve the
pre-existing nearest-rank `ceil(n*q)-1` rule. All 10,972 exact keys joined one-to-one
to shadow keys. Request-count mismatches: 0. Error-count mismatches: 0. Maximum
latency-sum delta: 0.005000001 ms (the exact live path stores two-decimal sums).

| Grain / percentile | Buckets | Max abs error | Max relative error | 95th-rank abs error |
|---|---:|---:|---:|---:|
| 60s p50 | 6,837 | 7.656206 ms | 1.804117% | 0.001000 ms |
| 60s p95 | 6,837 | 0.001011 ms | 0.049748% | 0.000005 ms |
| 60s p99 | 6,837 | 0.001013 ms | 0.049748% | 0.000007 ms |
| 300s p50 | 4,135 | 21.444922 ms | 1.632302% | 0.007110 ms |
| 300s p95 | 4,135 | 4.009863 ms | 1.032798% | 0.000003 ms |
| 300s p99 | 4,135 | 0.001013 ms | 0.048779% | 0.000003 ms |
| 60s p99, <=5 samples | 5,535 | 0.001003 ms | 0.049748% | 0.000002 ms |
| 300s p99, <=5 samples | 3,836 | 0.001003 ms | 0.048779% | 0.000002 ms |

No percentile-of-percentiles or average of p95 values is used; reads merge TDigest
states across the complete key. Scratch cleanup was proven by a `system.databases`
count of `0` after dropping `sqlagg_phase3_250k`.

### Phase boundary test

Command: `.venv/bin/python -m pytest tests/ -q`

```text
..................                        [100%]
121 passed in 195.13s (0:03:15)
```

## Phase 4 — done (cutover verdict: not ready, flag OFF)

Fresh scratch database `sqlagg_phase4_250k` loaded the same first 250,000 records
and ran exact and shadow paths fully. A scratch-only compatibility table allowed the
unchanged baseline/detector code to evaluate shadow values; no production schema or
serving path was redirected.

| Comparison | Exact | Shadow | Delta |
|---|---:|---:|---:|
| Complete logical keys | 10,972 | 10,972 | 0 |
| Request-count mismatches by key | 0 | 0 | 0 |
| Error-count mismatches by key | 0 | 0 | 0 |
| Maximum p50 difference | — | — | 21.444922 ms |
| Maximum p95 difference | — | — | 4.009863 ms |
| Maximum p99 difference | — | — | 0.001013 ms |
| Overview request/error totals | 250,000 / 1,920 | 250,000 / 1,920 | 0 / 0 |
| Overview average latency | 131.730503 ms | 131.730496 ms | -0.000007 ms |
| Overview max detailed p95 | 4,399.820000 ms | 4,399.819824 ms | -0.000176 ms |
| Service rows | 15 | 15 | 0 |
| Max service count/error delta | — | — | 0 |
| Max service displayed-latency delta | — | — | 0.000176 ms |
| Principal rows | 1 | 1 | 0 |
| Principal target/operation cardinality | 15 / 941 | 15 / 941 | 0 / 0 |
| Topology rows | 0 | 0 | 0 |
| Detector windows | 7 | 7 | 0 |
| Anomaly outputs / unique signatures | 4 / 4 | 4 / 4 | 0 |
| Only-exact / only-shadow anomaly signatures | 0 / 0 | 0 / 0 | 0 / 0 |

The result is favorable but not sufficient for cutover. This 30-minute production
slice has no resolved caller and only the `unknown` principal, so it cannot validate
non-empty topology or identity-shaped outputs. Shadow states also used more compressed
space than exact rows on this sample, and the measured 1.804117% p50 / 1.032798% p95
worst relative errors require an operator tolerance decision. Recommendation: keep
`OTEL_AGGREGATION_CUTOVER=false`, collect a caller/principal-rich comparison window,
approve percentile tolerances, and capacity-plan state retention before cutover.

Scratch cleanup: `sqlagg_phase4_250k` was dropped and `system.databases` returned `0`.

### Phase boundary test

Command: `.venv/bin/python -m pytest tests/ -q`

```text
..................                        [100%]
121 passed in 188.85s (0:03:08)
```

## Phase 5 — done

### 5.1 Benchmarks before serving-query changes — done, no rewrites justified

The 250k scratch database contained two exact replacement versions per logical key
(21,944 physical rows, 10,972 `FINAL` rows). Each variant received one warm-up plus
15 timed executions with query cache disabled. Times are client-observed milliseconds.
The `argMax` variant selected the entire metric tuple with unambiguous
`tuple(created_at,id)` ordering and grouped by the complete logical key. The state
variant used `GROUP BY` plus merge functions, never averaged percentiles.

| Query family | FINAL median / p95 | argMax tuple median / p95 | state GROUP BY median / p95 | Decision |
|---|---:|---:|---:|---|
| Overview KPIs | 10.163 / 11.483 | 20.076 / 26.560 | 34.017 / 53.247 | Keep FINAL |
| Topology graph | 10.207 / 11.508 | 8.935 / 12.365 | 7.864 / 29.861 | No rewrite: result was empty |
| Service detail | 10.633 / 18.028 | 13.504 / 20.718 | 19.900 / 30.332 | Keep FINAL |
| Principal profile | 10.937 / 33.388 | 21.388 / 31.187 | 28.283 / 51.350 | Keep FINAL |

Exact `argMax` results matched `FINAL` for every family. Non-empty state results were
not bit-exact because TDigest is approximate. No backend serving query was rewritten:
there is no demonstrated real win with preserved correctness.

### 5.2 Independent schedules, checkpoints, and anomaly identity — done

- Aggregation runs every worker cycle and retains `aggregation_cursor` plus bounded
  query/memory settings.
- Baselines use independent `worker_baselines` state, default 300-second cadence,
  and a configurable 100 changed-target-series page. The composite
  `(bucket_version,target_service)` cursor prevents a same-version page boundary from
  skipping targets; each selected target rebuilds its complete history.
- Anomalies run from durable newly completed/revised bucket markers, consume at most
  the configurable 100 windows per cycle, delete only successfully evaluated markers,
  and persist `worker_anomalies` state.
- Principal intelligence remains independently paged and checkpointed by its existing
  `principal_intelligence` `(ingest_order,row_uid)` cursor.
- Every stage reports the configurable 55-second execution budget and whether it was
  exceeded. The data-unit limits bound baseline series and anomaly windows; aggregation
  retains bounded slices and ClickHouse query budgets; principal behavior is unchanged.
- Anomaly IDs are deterministic BLAKE2b UInt64 values over detector, complete
  dimensions, and event-time window. Retry writes the same ID, and anomaly reads now
  use `FINAL`; the test proves two evaluations yield one logical row with the update.

Real 250k `backend.worker --once` evidence:

| Stage | Elapsed | Budget exceeded |
|---|---:|---|
| aggregate_traces | 0.767 s | false |
| rebuild_baselines | 0.147 s | false |
| detect_anomalies | 1.030 s | false |
| process_principal_intelligence | 0.242 s | false |

The cycle produced 6,837 1m buckets, 4,135 5m buckets, 971 baselines, and four
anomalies. Checkpoints existed for all four stages, logical anomaly count and unique ID
count were both four, pending revision markers were zero, and cutover remained false.
`sqlagg_phase5_250k` cleanup returned `0` databases.

### Phase boundary test

Command: `.venv/bin/python -m pytest tests/ -q`

```text
..................                      [100%]
123 passed in 200.60s (0:03:20)
```
