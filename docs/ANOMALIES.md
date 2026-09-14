# Explainable detectors

All findings expose the rule, window, training period, current/baseline sample sizes, absolute delta, percentage change only when meaningful, persistence, limitations, contributors, and representative trace IDs. The worker implements robust volume/latency/proportion checks plus separate novelty, dormancy, operation-mix, usage-hour, dependency, and operation-matched instance detectors. The latter detectors are intentionally conservative and remain candidates for threshold calibration on production history.

| Detector | Statistic | Guardrails |
|---|---|---|
| RPS/TPS spike (`traffic_spike`) | Median/MAD on matching rates | Current RPS > max(2×base, base + 3×MAD), ≥50 requests, ≥2 baseline samples |
| RPS/TPS drop (`traffic_drop`) | Median/MAD baseline comparison | Current RPS < 25% of baseline when base > 5.0 RPS |
| Latency regression (`latency`) | Exact p95 vs robust baseline | Current p95 > max(1.8×base, base + 3×MAD), current p95 > 150 ms, ≥10 requests |
| 5xx / error surge (`error_rate`) | Proportion vs baseline error rate | Current error rate > base + 4%, ≥5 failures |
| New service relationship (`new_service_edge`) | Caller-target edge unobserved in training period | ≥5 observed requests across edge |
| New principal relationship (`new_principal_edge`) | Principal unobserved accessing target in training period | ≥5 observed requests; higher severity for sensitive targets |
| Unusual execution time (`unusual_time`) | Off-hours hour-of-day profile | Interactive user active at 02:00–05:00 UTC, ≥3 requests |
| User + Source IP anomalies (`user_new_source_ip` / `ip_new_user`) | Principal-to-source mapping vs history | Known user from novel IP or known IP used by novel user (≥1 request) |
| Identity & Behavioral shifts (`behavioral_engine`) | Multi-layer candidate promotion & deviation scoring | Operation mix shift, caller principal switch, fanout surge, dormant reactivation, auth failure burst |

Lifecycle states are `open`, `investigating`, `resolved`, or `suppressed`. Suppression requires an expiry. Grouped security incidents bundle related behavioral events within 15-minute observation windows, apply strict family score caps (Origin 35, Access 40, Activity 35, Identity Mapping 30, Authentication 45), close after 30 minutes idle, and enforce a 24-hour maximum incident lifetime. Every finding exposes a 7-question explainability card with evidence, limitations, contributors, and representative trace IDs.
