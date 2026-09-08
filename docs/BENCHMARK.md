# Two-million-transaction benchmark

Run the reproducible benchmark with:

```sh
python -m backend.benchmark --events 2000000 --services 320 --db data/benchmark-2m.db
```

The deterministic generator creates 2,000,420 server transactions across 320 services (the extra 420 records form a known persistent regression), plus parent-linked and deliberately unlinked client spans used to validate confirmed versus inferred topology. The benchmark imports through the same sanitizer/repository code as JSON/NDJSON imports, runs the separate-worker rollup and detector code, and measures warm representative API repository calls nine times (service detail three times). Peak RSS comes from `getrusage`; SQLite size is the main database file immediately after analysis. Browser Canvas frame timing is a separate measurement because a headless graphical browser is not available in this environment.

Actual measurements from the current container will be recorded below after the included benchmark completes. Results are hardware- and filesystem-specific and are not a production capacity promise.

<!-- BENCHMARK_RESULTS -->

## Interpretation and limits

- The generated dataset covers duplicates by replay test, late timestamps, missing/malformed credentials, unknown callers, shared accounts, sampling uncertainty, sparse operation fixtures, confirmed/inferred edges, and a known traffic/latency/failure regression.
- Worker rollup memory is bounded to one source minute, but a pathologically large single minute still sets that bound. Topology aggregation streams client rows.
- SQLite permits one writer. `BEGIN IMMEDIATE`, short import batches, WAL, and a 5-second busy timeout serialize writes; production should use a server database and job leasing.
- The current evaluation worker rebuilds rollups idempotently. The schema/checkpoints support affected-window recomputation, but selective dirty-bucket scheduling is still a rollout requirement.
- The fixed histogram uses 48 logarithmic upper bounds from 1 ms to 120 s. It is mergeable but cannot recover within-bucket exact quantiles.
- Frontend production output currently emits a roughly 221 KiB gzip JavaScript bundle; route-level splitting is advisable before rollout.
