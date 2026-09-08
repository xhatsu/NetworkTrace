# Explainable detectors

All findings expose the rule, window, training period, current/baseline sample sizes, absolute delta, percentage change only when meaningful, persistence, limitations, contributors, and representative trace IDs. The worker implements robust volume/latency/proportion checks plus separate novelty, dormancy, operation-mix, usage-hour, dependency, and operation-matched instance detectors. The latter detectors are intentionally conservative and remain candidates for threshold calibration on production history.

| Detector | Statistic | Guardrails |
|---|---|---|
| RPS/TPS spike/drop | Median/MAD on matching one-minute rates | ≥30 current requests, ≥8 baseline buckets, ≥25% and ≥0.2 req/s, 2 buckets; drop skipped for missing/partial ingestion |
| Latency regression | Merged-histogram p95 vs robust baseline | ≥30 current and ≥200 baseline requests, ≥75 ms and ≥30% |
| 5xx / 401-403 increase | Wilson-aware proportion comparison | ≥30 current, ≥5 failures/denials, ≥2 percentage points |
| Slow rate | Duration above service threshold (default 1 s) | ≥30 current, ≥5 slow requests, ≥5 percentage points |
| New relationship/edge | First seen after training period | ≥3 observations in 10 minutes; evidence grade retained |
| Usage-hours / operation-mix change | Hour histogram or total-variation distance | ≥50 observations; compare like weekday windows |
| Dormant account return | Seen before, absent 14 days, then active | ≥5 renewed requests; identity caveat always shown |
| Instance imbalance | Operation-matched p95/share divergence | ≥30 per instance; at least 2 comparable instances |

Lifecycle states are open, acknowledged, resolved, or suppressed. Suppression requires an expiry. A stable fingerprint groups recurrence while occurrences retain separate windows.
