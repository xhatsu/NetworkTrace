# Two-million-transaction benchmark

Run the reproducible benchmark with:

```sh
python -m backend.benchmark --events 2000000 --services 320
```

The deterministic generator creates 2,000,420 server transactions across 320 services (the extra 420 records form a known persistent regression), plus parent-linked and deliberately unlinked client spans used to validate confirmed versus inferred topology. The benchmark imports through the same sanitizer/repository code as JSON/NDJSON imports, runs the separate-worker rollup and detector code, and measures warm representative API repository calls nine times (service detail three times). Peak RSS comes from `getrusage`; ClickHouse disk footprint is queried from `system.tables` (`clickhouse_bytes_on_disk`). Browser Canvas frame timing is a separate measurement because a headless graphical browser is not available in this environment.

Actual measurements from the current container will be recorded below after the included benchmark completes. Results are hardware- and filesystem-specific and are not a production capacity promise.

<!-- BENCHMARK_RESULTS -->

## Interpretation and limits

- The generated dataset covers duplicates by replay test, late timestamps, missing/malformed credentials, unknown callers, shared accounts, sampling uncertainty, sparse operation fixtures, confirmed/inferred edges, and a known traffic/latency/failure regression.
- Worker rollup memory is bounded to one source minute. Rollups compute exact p50/p95/p99 percentiles directly from raw trace samples in complete rollup windows. Topology aggregation streams client rows.
- ClickHouse is the sole persistence store (`http://127.0.0.1:8123`, database `tracescope`). Ingestion uses batched asynchronous inserts via `backend/app/services/ingest_writer.py` with bounded queuing (256 requests) and microsecond-precision monotonic row IDs.
- The background analytics worker (`backend/worker.py`) runs periodically on a 60-second cadence, rebuilding rollups, baselines, and detector findings idempotently.
- Tables use ClickHouse `ReplacingMergeTree` engines for deduplication and mutable entity updates.
- Frontend production output currently emits a roughly 221 KiB gzip JavaScript bundle; route-level splitting is advisable before rollout.
