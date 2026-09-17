# OtelTrace — Current Abnormal-Detection System and How It Scores

Grounding: live code in `~/Viettel/OtelTrace` @ `4a93014` and live ClickHouse
`10.105.101.253:8123`, database `tracescope` (queried 2026-09-16). Every threshold, point value
and count below was read from source or measured in the live DB — none are inferred from docs.

---

## 0. Shape of the system

Two **independent** detection paths that never share a score. There is no ML anywhere
(`backend/requirements.txt` = fastapi, uvicorn, pydantic, httpx, anyio, python-multipart,
clickhouse-connect, pytest — not even numpy).

| | Path A — service | Path B — principal |
|---|---|---|
| Code | `app/services/anomaly_detection.py` | `app/services/behavioral_engine.py`, `app/services/principal_relationships.py` |
| Entity | `target_service` | `principal_id` = `{environment}:{principal_name}` |
| Window | 5m only | per-row facts + 15m window rules |
| Baseline source | `baseline_repository.get_baseline("service", svc, hod, dow)`, `bucket_size=300` | `historical_registry`, `principal_baselines`, `principal_readiness_summary` |
| Output table | `anomaly_events` (own `score` + `severity`) | `principal_change_events` → `incidents` |
| Nature | numeric threshold vs median/MAD | set-membership facts + hardcoded thresholds |
| Surface | `/anomalies`, service pages | `/incidents`, `/user-changes`, principal pages |

Worker order (`backend/worker.py::run_jobs`, 60s cadence):
`sync_elasticsearch` → `aggregate_traces` → `rebuild_baselines` → `detect_anomalies` →
`process_principal_intelligence`.

---

## 1. Path A — service-level numeric detectors

Loop aggregates 5m rows per `target_service`:
`reqs = Σ request_count`, `errors = Σ error_count`, **`p95 = MAX(latency_p95)`** (max-of-maximums,
not a true service-level percentile), plus distinct callers / principals / operations.
Gate: `base["sample_count"] >= 2`, otherwise the service is skipped entirely.

| Detector | Trigger as coded | Score | Severity mapping |
|---|---|---|---|
| `traffic_spike` | `current_rps > max(2.0×rps_median, rps_median + max(1.0, 3.0×rps_mad))` **and** `reqs >= 50` | `min(100, int(50 + Δ%/10))` | ≥85 critical, ≥70 high, else medium |
| `traffic_drop` | `rps_median > 5.0` **and** `current_rps < 0.25×rps_median` | `min(100, int(60 + abs(Δ%)/2.5))` | ≥75 high, else medium |
| `latency` | `current_p95 > max(1.8×p95_median, p95_median + max(50.0, 3.0×p95_mad))` **and** `p95 > 150.0` **and** `reqs >= 10` | `min(100, int(55 + Δ%/8))` | ≥80 critical, ≥65 high, else medium |
| `error_rate` | `current_err > error_rate_median + 0.04` **and** `errors >= 5` | `min(100, int(60 + current_err×200))` | ≥0.10 critical, else high |

Δ% is always `(current − baseline)/max(ε, baseline)×100` with ε = 0.01 (rps), 1.0 (p95), 0.001 (error).

Fixed-score fact detectors in the same path: `new_service_edge` (score 65, medium),
`new_principal_edge` (score 75; severity = high if target contains `admin` or `pay`, else medium),
`unusual_time` (score 60, medium, hardcoded 02:00–04:00 UTC + hardcoded service exclusion list),
`user_new_source_ip` (75, high), `ip_new_user` (score computed, severity high if ≥75 else medium).

`confidence` is a **hardcoded constant per detector** (0.80 / 0.85 / 0.88 / 0.90 / 0.92 / 0.95) —
it is never computed from data.

Identity: `deterministic_anomaly_id` = `blake2b(anomaly_type \x1f caller \x1f target \x1f principal
\x1f source_ip \x1f operation \x1f first_seen \x1f last_seen, digest_size=8)`, `0 → 1`. Stored in a
`ReplacingMergeTree`, so the same detector+dimensions+window replaces its previous row instead of
duplicating. Each anomaly carries `reasons: [{type, contribution, baseline, current, text}]`,
`baseline_value`, `current_value`, `delta_percentage`.

**No 1-minute path exists.** `detect_anomalies` only ever queries `bucket_size = 300`. The 1m
rollups (`bucket_size = 60`) are read by `/overview` and blast-radius only.

---

## 2. Path B — principal-level: facts, points, then additive-with-caps

### Step 1 — deterministic facts emit a constant point value

`EVENT_SCORES` (verbatim; point values confirmed against live rows):

| Family | Change type | Points |
|---|---|---|
| origin | `NEW_CALLER` | 30 |
| origin | `NEW_PRINCIPAL_ON_SOURCE` | 15 |
| origin | `NEW_SOURCE_IP` | 10 |
| origin | `NEW_IP_CALLER_PAIR` | 10 |
| origin | `SOURCE_IP_DISTRIBUTION_SHIFT` | 10 |
| origin | `SOURCE_FANOUT_SURGE` | 25 |
| access | `NEW_TARGET` | 25 |
| access | `NEW_OPERATION` | 15 |
| access | `NEW_RELATIONSHIP` | 15 |
| access | `TARGET_FANOUT_SURGE` | 25 |
| access | `OPERATION_MIX_SHIFT` | 25 |
| activity | `DORMANT_REACTIVATED` | 30 |
| activity | `PRINCIPAL_RATE_SURGE` | 20 |
| activity | `UNUSUAL_TIME` | 10 |
| identity_mapping | `CALLER_PRINCIPAL_SWITCH` | 30 |
| authentication | `FAILURE_THEN_SUCCESS` | 35 |
| authentication | `AUTH_FAILURE_BURST` | 30 |
| authentication | `SOURCE_IDENTITY_FANOUT` | 20 |
| audit / operational / data_quality | `USERNAME_FIRST_SEEN`, `RELATIONSHIP_DISAPPEARED`, `RELATIONSHIP_REAPPEARED`, `IDENTITY_FAILURE_RATE_SHIFT`, `DATA_QUALITY_GAP`, `DATA_QUALITY_EXTRACTION_DROP` | 0 |

The `severity` column on `principal_change_events` is written from `base_importance`
(a high/medium/low label per change type), **not** derived from the score.
`principal_change_events.reason_json` is a fixed 7-question explanation blob:
`what_changed`, `compared_with`, `where`, `how_reliable`, `why_priority`
(`base_importance`, `base_points`, `family`, `family_cap`), `what_proves_it` (representative
trace ids), `what_happened_afterward`.

Event fingerprint = `sha256(principal_id | change_type | caller | source_ip | target | operation |
detected_at // 900_000)` — i.e. **15-minute dedup bucket**. Event id =
`sha256(fingerprint)[:15] % 9e15 + 1`.

The statistical rules that compare the user against their own history, with thresholds as coded:

| Detector | Trigger | Guard |
|---|---|---|
| `OPERATION_MIX_SHIFT` | per (principal, target): one operation's share rises **≥ 20 percentage points** over its historical share | ≥25 current obs, ≥100 current window, ≥200 historical, ≥10 historical 15m windows |
| `TARGET_FANOUT_SURGE` | distinct targets `cur > hist_max` **and** `cur ≥ 2.5 × hist_median` | distinct targets ≥ 3 |
| `SOURCE_FANOUT_SURGE` | distinct `source_group` `cur > hist_max` **and** `cur ≥ 2.0 × hist_median` | distinct source groups ≥ 3 |
| `PRINCIPAL_RATE_SURGE` | `cur > p99` **and** `cur > 3 × median` **and** `(cur − median) ≥ 50` | same (dow, hod) history only, ≥5 prior windows |
| `CALLER_PRINCIPAL_SWITCH` | historical dominant principal share ≥ 80%, then a different principal ≥ 10 reqs | — |
| `AUTH_FAILURE_BURST` / `FAILURE_THEN_SUCCESS` | ≥5 explicit failures in window / failure followed by success | — |
| `DORMANT_REACTIVATED` | gap ≥ `principal_dormant_days` (default 30) | ≥5 prior obs |
| `UNUSUAL_TIME` | hardcoded 02:00–04:00 UTC, hardcoded service exclusion list | readiness ≥28d + ≥10 active days |
| novelty (`NEW_CALLER/TARGET/OPERATION/RELATIONSHIP/SOURCE_IP/IP_CALLER_PAIR/PRINCIPAL_ON_SOURCE`), `USERNAME_FIRST_SEEN` | membership test against `historical_registry` / `principal_baselines` / `principal_sources` / `established_baselines` | readiness gate, see §3 |

### Step 2 — incident aggregation (`recalculate_incident_score`)

Documented formula: `family_score = min(family_cap, Σ eligible distinct contributions)`,
`incident_score = min(100, Σ family_scores)`.

Four suppression rules run before summing; every suppressed contribution is persisted in
`suppressed_contributions_json`:

1. **Duplicate value** — same `(change_type, new_value)` already scored in this incident → suppressed.
2. **Logical relationship** — `NEW_RELATIONSHIP` suppressed when a scored `NEW_CALLER` /
   `NEW_TARGET` / `NEW_OPERATION` already explains it.
3. **Authentication** — `FAILURE_THEN_SUCCESS` (35) replaces `AUTH_FAILURE_BURST` (30) when both
   are present; the weaker one is removed and logged as replaced.
4. **IP attribution confidence** — `NEW_SOURCE_IP`, `NEW_IP_CALLER_PAIR`,
   `SOURCE_IP_DISTRIBUTION_SHIFT` are suppressed or down-weighted when CRITIC's
   `classify_source_ip_role` says the address is a load balancer / proxy / trusted gateway.

Family caps (`FAMILY_CAPS`): **origin 35 · access 40 · activity 35 · identity_mapping 30 ·
authentication 45 · audit 0 · operational 0 · data_quality 0**.
`incident.score = min(100, Σ family_scores)`;
`investigation_priority = high if score ≥ 50, medium if score ≥ 20, else low`.

Incident lifecycle: created/updated via `get_or_create_incident` on
`(principal_id, environment, category, scope = "{target_service or global}:{caller_service or direct}")`,
closed after 30 minutes idle, hard lifetime 24 hours, successor chain on re-open. Incidents are
appended as complete replacement rows (`insert_incident_version`) — never ClickHouse mutations.

`priority` is the *only* thing that distinguishes "34 high" from "18 low"; the underlying score is
always 0–100 and always a sum of capped family contributions.

---

## 3. Readiness gating (`evaluate_readiness_from_stats`, on `principal_readiness_summary`)

| Detector group | `ready` requires | Fallback |
|---|---|---|
| all `NEW_*` novelty + `SOURCE_IP_DISTRIBUTION_SHIFT` | elapsed ≥ **7 days** and active days ≥ 3 and total obs ≥ 100 | `True, "low_confidence"` at total obs ≥ 10, or elapsed ≥ 1 day and obs ≥ 5 |
| `OPERATION_MIX_SHIFT`, `PRINCIPAL_RATE_SURGE`, `CALLER_PRINCIPAL_SWITCH`, `TARGET_FANOUT_SURGE`, `SOURCE_FANOUT_SURGE` | elapsed ≥ **14 days** and active days ≥ 5 and obs ≥ 200 | none — `False, "insufficient_history"` |
| `UNUSUAL_TIME` | elapsed ≥ **28 days** and active days ≥ 10 | none |
| `DORMANT_REACTIVATED` | obs ≥ 5 | none |
| `RELATIONSHIP_DISAPPEARED` | elapsed ≥ 7 days and obs ≥ 50 | none |
| anything unmapped | — | always `True, "ready"` |

**The gating loophole:** callers do `ready, _ = readiness(...)` and discard the tier, so the
`low_confidence` fallback counts as a **full pass**. The ≥7-day requirement is therefore not
effective for novelty — a principal with 10 observations produces production-scored novelty events.

---

## 4. Live state — and the mechanical cause of the current flood

Measured in `tracescope` on 2026-09-16:

- `traces` — 59,483 rows, 18 principals, 10 targets, 38 operations, spanning **08:04 → 11:50 PT
  (~3.9 h)**, i.e. one calendar day.
- `anomaly_events` — **1,637 rows**:
  `new_principal_edge` 1,174 medium + 74 high (both score 75; the 74 are the `admin`/`pay` keyword
  hit), `new_service_edge` 372 medium (65), `traffic_spike` 6 medium (62–69) / 2 high (70–72) /
  2 critical (90–97), `error_rate` 4 critical (100) + 1 high (79), `latency` 2 critical (100).
- `principal_change_events` — **44,010 rows**, 8 types:
  `NEW_IP_CALLER_PAIR` 9,528 @10 · `NEW_SOURCE_IP` 8,343 @10 · `NEW_OPERATION` 8,130 @15 ·
  `NEW_TARGET` 7,953 @25 · `NEW_CALLER` 6,340 @30 · `NEW_RELATIONSHIP` 3,666 @15 ·
  `NEW_PRINCIPAL_ON_SOURCE` 32 @15 · `USERNAME_FIRST_SEEN` 18 @0.
- `incidents` — **70 open**: 34 high (score 50–75), 18 medium (30–40), 18 low (0).
- `established_baselines` — **0 rows**. `historical_registry` 7,092 · `principal_baselines` 4,920
  (caller 80, source 129, target 145, operation 465, hour 33, relationship 4,068) over 17
  principals.
- **No statistical detector has ever fired** — zero `OPERATION_MIX_SHIFT`,
  `TARGET_FANOUT_SURGE`, `SOURCE_FANOUT_SURGE`, `PRINCIPAL_RATE_SURGE`, `DORMANT_REACTIVATED`,
  `AUTH_FAILURE_BURST`, `CALLER_PRINCIPAL_SWITCH`, `UNUSUAL_TIME` rows. Their ≥14-day / ≥28-day
  gates are unreachable on a 3.9-hour dataset. **100% of principal-side scoring today is pure
  novelty facts**, i.e. the exact facts the ML design says must stay outside ML.

**Why 44,010 events: the bootstrap is not incremental.** The `principal_intelligence` checkpoint
reads `{"bootstrap_cutoff_ms": 1789552894000, "ratio": 0.75}` (cutoff = 2026-09-16 10:01:34 UTC).
`_bootstrap` seeds `principal_baselines` / `principal_callers` / `principal_sources` /
`principal_targets` / `principal_operations` / `principal_hourly_activity` / `principal_daily_stats`
from the **first 75%** of the trace range only, then replays everything after the cutoff as
"never observed before" → every (caller, ip, target, operation, relationship) combination in the
last ~1 h of traffic becomes a `NEW_*` event. By construction, not a bug — but it means the point
score distribution today reflects the bootstrap split, not user behaviour.

`principal_baselines.distribution_share` is a single **global** share per principal
(`COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY principal_name)`), computed once at bootstrap — no
(dow, hod) conditioning, no decay, no windowing. That is the only "distribution" notion in the
system.

---

## 5. What this means for the ML target

Every decision in the current system is **one-dimensional and independent**:

- each detector compares **one metric** against either a fixed constant (0.04 error delta, 150 ms,
  reqs ≥ 50/10, 20 pp, 2.5× / 3.0×, p99 + ≥50 excess, 02:00–04:00 UTC) or a median/MAD plus a
  hand-picked multiplier;
- each deterministic fact contributes a **constant** number of points regardless of context;
- the aggregate score is an **additive sum with per-family caps** — so two individually-normal
  deviations that co-occur score identically to two unrelated ones;
- the user's own historical **shape** is never modelled: no joint state vector, no entropy, no
  distribution distance, no consecutive-window persistence, no covariance.

So the current system can answer *"did metric X cross threshold Y for entity Z"* and *"is fact F
new for user U"*, but it cannot answer *"is this combination of simultaneous changes unusual **for
this user at this time of week**"* — which is exactly the gap the multivariate per-user 5m model
(with 1m as an early-change signal) is meant to fill. The deterministic layer stays authoritative
for *what changed*; the ML layer becomes authoritative for *whether the combination is unusual*.