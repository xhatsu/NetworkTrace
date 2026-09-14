# Analytics Worker OOM Fix Report

## Root cause

`aggregate_traces` resolved the full minimum-to-maximum trace timestamp range and issued one raw-row query for that entire unbounded interval. It then retained every returned row plus per-dimension duration arrays for both one-minute and five-minute groups in Python so it could calculate exact percentiles. As trace history grew, ClickHouse had to read and return the complete raw working set on every worker cycle; the verified production data set pushed that query to 1.81 GiB, above ClickHouse's 1.80 GiB effective ceiling, so code 241 aborted aggregation before rollups, baselines, or anomaly detection could complete.

## Approach

Aggregation now has two persisted phases in the existing `checkpoints` table:

- Bootstrap scans raw history in six-hour slices. Every slice boundary is aligned to a five-minute boundary, and each slice's one-minute and five-minute rollups are persisted before `next_slice_start_ms` advances. A captured composite high-water mark identifies the last `(ingest_order, row_uid)` present when bootstrap began, so rows arriving during bootstrap are handled afterward.
- Steady state uses the same `(ingest_order, row_uid)` cursor pattern as principal intelligence and reads at most 10,000 new trace identities per cursor batch. It derives the affected five-minute buckets from those rows, coalesces consecutive buckets only within the six-hour ceiling, and recomputes each complete bucket from raw traces. This catches late-arriving traces without rescanning unrelated history. The composite cursor advances only after all affected slices in the batch have been persisted.

All raw rollup queries therefore cover no more than six hours. Because six hours is exactly divisible by five minutes and all start/end points are five-minute aligned, neither one-minute nor five-minute buckets are split across queries; exact p50/p95/p99 calculations still receive every raw sample in a bucket. Existing timestamp-only aggregation checkpoints are treated as legacy and trigger a bounded bootstrap, avoiding silent skips during cursor migration. Explicit caller-supplied windows use the same bounded aligned slicing but do not mutate the worker cursor.

## Files changed

- `backend/app/services/aggregation.py` — bounded bootstrap slicing, persisted bootstrap progress, composite incremental cursor, complete affected-bucket recomputation, and bounded explicit-window processing.
- `tests/test_analytics.py` — regression coverage for late-arriving rows, steady-state no-op behavior, composite cursor persistence, and restart from the first unsuccessful bootstrap slice.
- `OOM_FIX_REPORT.md` — this report.

## Pytest baseline vs final

Baseline:

```text
111 passed in 262.41s (0:04:22)
```

Final:

```text
113 passed in 218.66s (0:03:38)
```

## Caveats

The six-hour cap is conservative for the current production density, but an extreme future workload that places enough high-cardinality raw traces inside a single six-hour slice could still approach the ClickHouse memory ceiling. The constant can be reduced without changing cursor or bucket semantics if that occurs. A future Helm memory increase provides additional headroom but is not required by, and was not included in, this fix. Cursor discovery follows the repository's established composite-cursor query pattern; at much larger total histories, ClickHouse indexing or projection work for `ingest_order` may be worthwhile even though steady-state materialization itself only processes new cursor rows and their affected buckets.
