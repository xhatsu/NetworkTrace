# SQL Aggregation Phase 1 Report

## 1. Quantile choice and parity evidence

The compatibility contract in the pre-SQL worker is nearest-rank:

```python
index = max(0, math.ceil(len(values) * quantile) - 1)
```

`quantilesExactInclusive` and `quantiles` do not preserve that contract because they interpolate. For example, ClickHouse returns p50 `5.0` for `[1.0, 9.0]`, while the existing Python function returns `1.0`. Plain `quantilesExact(0.50, 0.95, 0.99)` also differs when `n*q` is an integer because ClickHouse selects `floor(n*q)` with zero-based indexing; on values 1 through 100 it returns `(51, 96, 100)` instead of `(50, 95, 99)`.

The implementation therefore uses `quantilesExact` with the immediately preceding Float64 value for each requested percentile:

```sql
quantilesExact(
  0.49999999999999994,
  0.9499999999999998,
  0.9899999999999999
)(duration_ms)
```

This retains exact ClickHouse quantiles while reproducing the established `ceil(n*q)-1` rank at integer boundaries. `test_sql_exact_percentiles_match_old_python_nearest_rank` copies the old Python implementation as an independent reference, inserts the deterministic values `1.0 .. 100.0` into one dimension/minute, executes the production SQL aggregation path, and asserts equality for both 60-second and 300-second rows. Expected and observed p50/p95/p99 were `(50.0, 95.0, 99.0)`. The existing 100-sample raw-data test also proves that one high outlier is excluded from p99 under the preserved rank definition.

Focused parity and byte-cap test output:

```text
...                                                                      [100%]
3 passed in 3.61s
```

## 2. SQL/Python responsibility boundary

For each existing bounded slice, ClickHouse now performs the complete 1-minute and 5-minute `GROUP BY` over the unchanged key `(bucket_start, bucket_size, caller_service, target_service, principal_name, operation)`. SQL computes `count()`, `countIf(error)`, `sum`, `avg`, `min`, `max`, and the three exact quantiles. Only completed grouped rows cross from ClickHouse to Python; `aggregation.py` no longer fetches raw `duration_ms` rows or builds duration lists.

Python still converts grouped rows to the unchanged `MetricBucket` model, applies the existing two-decimal storage rounding, saves the unchanged `metric_buckets` schema, derives the existing service/principal topology summaries from 1-minute bucket rows, and owns recovery orchestration. The proven 6-hour five-minute-aligned slices, `(ingest_order, row_uid)` watermark, 10,000-row cursor paging, late-arrival affected-bucket recomputation, bootstrap checkpoint-after-success rule, and resume behavior were left intact.

Aggregation query limits are centralized in `backend/config.py`:

- `OTEL_AGGREGATION_MAX_MEMORY_USAGE`: default 1 GiB.
- `OTEL_AGGREGATION_EXTERNAL_GROUP_BY_BYTES`: default 256 MiB.
- The effective external-group threshold is capped at half the query limit so the merge phase retains at least half of the per-query allowance.

These settings bound each SQL aggregation query. Exact quantile states still retain samples inside ClickHouse; external `GROUP BY` spill does not prove safety for every possible extreme density/cardinality distribution. A sufficiently dense single 6-hour slice can still receive ClickHouse code 241. Operators can reduce the slice separately in code or lower/tune the environment budgets after measuring production density; no unsupported worst-case bound is claimed here.

## 3. Byte-based ingest cap

`OTEL_INGEST_MAX_BATCH_BYTES` defaults to 32 MiB. Each queued request records the UTF-8 byte length of its normalized Pydantic JSON representation. The coalescer checks the prospective request count and byte total before appending the next request. It flushes the current block if either adding that request would exceed `OTEL_INGEST_TRANSACTION_RECORDS` (still default 50,000) or the new byte limit. The deferred request remains first for the next transaction, preserving queue order and request atomicity.

An individually oversized request is isolated rather than split across durability responses. Public ingestion is already bounded by the existing 10 MiB request limit, which is below the default 32 MiB coalesced-block cap. The writer status payload now exposes `transaction_byte_limit` alongside `transaction_record_limit`.

`test_writer_flushes_before_coalesced_byte_cap` gives requests estimated at 6, 4, and 1 bytes to a 10-byte writer and proves transaction grouping is exactly `[[6, 4], [1]]` while the record cap remains independently enabled.

## 4. Memory telemetry sample

The worker now samples Linux `resource.getrusage(RUSAGE_SELF).ru_maxrss` and ClickHouse `system.metrics.MemoryTracking` before and after every stage. Completion events contain both snapshots and deltas. Telemetry lookup failure is non-fatal and produces a null ClickHouse value. `MemoryTracking` is server-global, so its delta can include concurrent ClickHouse activity; it is an operational signal, not per-query attribution.

This is the verbatim output of one isolated worker cycle against `sqlagg_report_20260914`, containing 100 deterministic spans:

```text
{"event": "worker_stage_start", "stage": "aggregate_traces", "memory_before": {"python_max_rss_kb": 41404, "clickhouse_memory_tracking_bytes": 2053092672}}
{"event":"aggregation_slice_complete","slice_start_ms":1767225600000,"slice_end_ms":1767225900000,"raw_rows":100,"bucket_rows_1m":1,"bucket_rows_5m":1,"raw_to_1m_bucket_ratio":100.0,"raw_to_all_bucket_ratio":50.0}
{"event": "worker_stage_complete", "stage": "aggregate_traces", "elapsed_seconds": 0.123, "memory_before": {"python_max_rss_kb": 41404, "clickhouse_memory_tracking_bytes": 2053092672}, "memory_after": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2053994818}, "python_max_rss_delta_kb": 128, "clickhouse_memory_tracking_delta_bytes": 902146}
{"event": "worker_stage_start", "stage": "rebuild_baselines", "memory_before": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2054022122}}
{"event": "worker_stage_complete", "stage": "rebuild_baselines", "elapsed_seconds": 0.018, "memory_before": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2054022122}, "memory_after": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2054175531}, "python_max_rss_delta_kb": 0, "clickhouse_memory_tracking_delta_bytes": 153409}
{"event": "worker_stage_start", "stage": "detect_anomalies", "memory_before": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2054202883}}
{"event": "worker_stage_complete", "stage": "detect_anomalies", "elapsed_seconds": 0.04, "memory_before": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2054202883}, "memory_after": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2054993507}, "python_max_rss_delta_kb": 0, "clickhouse_memory_tracking_delta_bytes": 790624}
{"event": "worker_stage_start", "stage": "process_principal_intelligence", "memory_before": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2055020811}}
{"event": "worker_stage_complete", "stage": "process_principal_intelligence", "elapsed_seconds": 0.151, "memory_before": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2055020811}, "memory_after": {"python_max_rss_kb": 41532, "clickhouse_memory_tracking_bytes": 2057122200}, "python_max_rss_delta_kb": 0, "clickhouse_memory_tracking_delta_bytes": 2101389}
{"event": "worker_cycle_complete", "1m_buckets": 1, "5m_buckets": 1, "service_edges": 1, "principal_edges": 1, "baselines": 4, "anomalies": 0, "principal_records": 0, "principal_changes": 0}
```

## 5. Compression-ratio observation

Each successfully written slice emits raw-row count, 1-minute and 5-minute output row counts, and both raw-to-1m and raw-to-all-output ratios. The isolated sample produced 100 raw rows, one 1-minute key, and one 5-minute key: raw-to-1m compression was `100.0:1`; raw-to-all-output compression was `50.0:1`. This is deliberately a deterministic functional sample, not a production cardinality forecast.

## 6. Pytest baseline and final result

Operator-provided baseline line (the task supplied no elapsed time):

```text
113 passed
```

Final command:

```text
.venv/bin/python -m pytest tests/ -q
```

Final verbatim completion lines:

```text
..................                               [100%]
114 passed in 180.31s (0:03:00)
```

The net increase is one test because the prior nearest-rank unit test was replaced by the stronger SQL-vs-Python integration parity test, and a new byte-cap flush test was added. Existing tests were not skipped or weakened.

## 7. Explicitly deferred work

In accordance with delivery-sequence step 1, this change did not add or modify schemas, materialized views, `AggregatingMergeTree` tables, TDigest/aggregate state tables, TTLs, retention, serving-query rewrites, deduplication guarantees, retry/crash protocol, late-data repair design, shadow backfills, cutover logic, anomaly identity behavior, or independent per-stage checkpoints/schedules. Those remain later-phase work under `DESIGN_SQL_AGGREGATION.md`.
