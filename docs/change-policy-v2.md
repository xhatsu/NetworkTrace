# Evidence-gated Changes policy v2

## Implementation and rollout status

Implemented in `backend/app/services/change_policy.py`, called by the Changes adapter. API responses include `previous_evaluation` (v1) for comparison. No backend/worker restart or database migration was performed. The frontend production bundle was rebuilt and supports both old states and Watch.

**Activation requires review:** a bounded read-only replay of 182 existing episodes produced 31 critical → watch, 72 attention → watch, 13 attention → changed, 9 changed → watch, and 57 unchanged informational episodes. Historical records lack the new evidence fields. Downgrades indicate insufficient structured evidence, not proof of safety. Review historical critical findings and allow new worker observations before relying on the new attention counts. No notification sender was added.

## Levels

- `changed`: informational novelty; duplicate or related novelty signals do not establish harm.
- `watch`: metric or behavioral deviation without sufficient impact evidence.
- `needs_attention`: persistent material operational impact or explicit scoped authentication evidence.
- `critical`: measured severe operational impact.
- `expected`: retained compatibility state for explicit operator acceptance; `abnormality.impact_level` preserves evaluated impact separately.

Suppression remains workflow state and does not erase impact. `abnormality.disposition`, confidence, gates, reasons and evaluator version explain decisions. Limited confidence is not evidence of safety. L4 remains advisory; changed evaluator versions invalidate prior semantic assessments.

## Initial policy constants

These conservative initial defaults require fleet-specific calibration, not an SLO claim:

- Operational baseline readiness: at least 6 samples.
- Persistence: current abnormal aligned five-minute bucket plus at least one other distinct abnormal bucket among the previous two. Retries, occurrence counts, future timestamps and old windows do not count.
- Errors: at least 100 requests, 20 errors and +5 percentage points; critical after persistence with at least 200 requests, 100 errors and 50% errors.
- Immediate critical exception: at least 1000 requests, 900 errors, 90% error rate and +5 percentage points, without waiting for historical readiness.
- Latency: at least 100 requests, P95 >=500ms and +200ms; severe at >=200 requests and P95 >=5000ms. Persistence/readiness still required.
- Drop: baseline >=1 TPS, current <=25% and explicit healthy-telemetry evidence. Severe <=5%. No healthy-telemetry field is fabricated; current detector output therefore remains Watch.
- Spike: >=300 requests and explicit capacity-impact confirmation. Demand growth alone remains Watch. Current detector does not fabricate capacity evidence.
- Authentication: explicit security-event attribution and healthy collection; >=50 failures or >=20 failures followed by same caller/IP/target success warrants attention without a historical baseline. This does not establish account compromise or criticality.

## Evidence production

Service metric detectors emit counts, baseline sample count and observation bucket. Anomaly coalescing retains at most three distinct abnormal bucket timestamps. Old rows are not backfilled with invented persistence. Authentication emission stores structured failure/success counts, and success correlation is restricted to the same caller/IP/target. Resource-name substrings no longer elevate new principal-edge severity.

## Remaining boundaries

This is impact classification, not a persistent incident/notification lifecycle. The existing request-time 15-minute grouping and capped source loading remain; do not use its representative source ID as a notification idempotency key. Recovery hysteresis, durable episode identity, full operator-disposition migration, configurable service/SLO thresholds, independent security corroboration beyond explicit auth, notification deduplication and delivery are follow-up work.

Validation: 22 isolated evaluator, L4 contract, and mocked list/detail API checks passed. Tests ran from an isolated temporary directory to avoid the repository conftest's broad test-database cleanup hook. Frontend TypeScript/production build passed, Python compilation passed, diff whitespace check passed. No full database-backed suite or browser test was run.
