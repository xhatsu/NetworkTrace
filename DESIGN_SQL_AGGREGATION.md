# DESIGN REVIEW: Aggregation architecture (operator directive — apply per SQL_AGGREGATION_TASK.md)

Move aggregation into ClickHouse, but make retry correctness the first design gate. The proposed ranking overlooks a few issues that could turn an OOM fix into incorrect analytics.

## 1. Separate Python OOM from ClickHouse memory errors

These require different fixes:

| Failure | Effective fix |
|---|---|
| Python worker stores millions of durations | Stop transferring raw samples; aggregate in ClickHouse |
| ClickHouse query fails with code 241 | Bound query scope, reduce concurrency, configure spill |
| Container is OOMKilled | Budget total process memory against its container limit |

`max_bytes_before_external_group_by` controls ClickHouse aggregation memory, not Python memory. Raising `max_memory_usage` can also worsen container pressure. Spill thresholds need headroom for the aggregation merge phase and concurrent queries.

Immediate bridge: retain bounded processing, move its GROUP BY and percentile calculations into SQL, and return only completed bucket rows to Python.

## 2. Prove deduplication before attaching an incremental materialized view

This is the biggest architectural trap:

1. A span is inserted twice.
2. The materialized view processes both inserts.
3. ReplacingMergeTree later removes the duplicate raw row.
4. The rollup still contains both contributions.

Incremental materialized views process inserted blocks; they do not track later source-table reconciliation. The `ingest_batches` row alone does not establish atomicity between the trace insert and the dedup marker. Check: crash after trace insertion but before recording batch completion; client retry after the commit succeeds but the response is lost; concurrent submissions with the same batch ID; the same span appearing in different batches; a retry being coalesced into different insert blocks.

If these guarantees are not established, start with SQL recomputation of affected buckets. Read deduplicated raw data for bounded windows and write replacement bucket versions. This removes Python's memory problem while preserving a repairable model. Adopt insert-time aggregation only when duplicate and correction semantics are explicit and tested.

## 3. Store mergeable states, not only percentile values

For the eventual AggregatingMergeTree rollup: request count, error count, duration sum, `quantilesTDigestState(0.5,0.95,0.99)(duration_ms)`. Read using the corresponding merge functions and grouping dimensions. Build five-minute and hourly views by merging states.

Never average one-minute p95 values to produce a five-minute p95. Compute error rate from total errors / total requests. TDigest is approximate and order-dependent; validate its tail estimates against representative traffic. "Statistically indistinguishable" is too strong without measurement. If preserving the interpolated percentile definition matters, select a matching exact reference algorithm for validation.

## 4. Control rollup cardinality

Current key: caller × target × principal × operation × minute. If most combinations occur only once, rollups may remain nearly as large as raw data. Memory depends on active groups and aggregate states, not just insert-block size.

Start with the detailed rollup, measure its compression ratio, and add smaller serving aggregates where justified (service health: target/minute; topology: caller+target/minute; principal activity: principal+caller+target/minute; operation detail: target+normalized operation/minute). Normalize operations so request IDs and dynamic path segments do not become unique groups. Avoid building every possible combination upfront.

## 5. Make analytics incremental and independently recoverable

The four sequential stages couple unrelated workloads. Give each stage its own checkpoint and execution budget: aggregation (newly affected buckets), baselines (changed series, slower cadence), anomalies (newly completed/revised buckets), principal intelligence (bounded pages, persist after successful writes).

Keep event time separate from ingestion progress. Late events revise their historical buckets, and revisions should trigger reevaluation where needed. Use deterministic anomaly identifiers so retries update an existing event instead of producing duplicates. Verify that `(ingest_order, row_uid)` cannot skip records that become visible after the cursor advances.

## 6. Replace FINAL selectively

`argMax` is not automatically faster or a mechanical replacement. Its grouping must match the complete logical bucket key. For replacement buckets, select a whole metric tuple with one argMax using an unambiguous version ordering. For aggregate-state tables, use GROUP BY and merge functions. Benchmark representative dashboard queries before rewriting every existing query.

## 7. Set retention from measured storage and analytical needs

Thirty days raw / ninety days buckets are candidates, not established limits. Measure daily compressed growth including rollups; reserve space for merges and backfills. Apply retention to agent statistics and intermediate tables too. Keep principal first-seen history and baseline state separately if behavioral detection needs context beyond raw retention — otherwise an old relationship can incorrectly become "new" again.

## Recommended delivery sequence

1. **Now:** SQL aggregation over bounded windows; byte-based queue limits; worker and ClickHouse memory monitoring.
2. **Next:** verify retry/crash behavior, measure cardinality, define late-data repair.
3. **Then:** introduce aggregate states and retention in shadow tables; backfill without overlapping live contributions.
4. **Cut over:** compare counts, errors, latency estimates, dashboard results, anomaly outputs.
5. **Finally:** optimize serving queries and decouple worker schedules.

The first release should demonstrate bounded worker memory as history grows, unchanged counts under retries, and correct handling of late spans. Those are stronger acceptance criteria than simply removing Python percentile code.
