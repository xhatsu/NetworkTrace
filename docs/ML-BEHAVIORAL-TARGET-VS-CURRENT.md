# ML Behavioral Anomaly Target vs Current OtelTrace Implementation

Source of truth: live code in `~/Viettel/OtelTrace` @ `4a93014` + live ClickHouse `10.105.101.253:8123` db `tracescope`.
Purpose: map each element of the proposed ML design (per-user multivariate behavioral anomaly,
5m primary / 1m early-signal) onto what already exists, what is partly there, and what is missing.

---

## 1. What the current system actually is

Pipeline (`backend/worker.py::run_jobs`, 60s cadence, order matters):

1. `sync_elasticsearch` — pull APM docs from ES into `traces`
2. `aggregate_traces` — build 1m (`bucket_size=60`) and 5m (`300`) rollups
3. `rebuild_baselines` — median/MAD baselines over **5m only**
4. `detect_anomalies` — service-level univariate detectors (revised 5m buckets only)
5. `process_principal_intelligence` — per-principal rule/novelty detectors, row-by-row over raw traces

**There is no ML anywhere.** No sklearn/torch/xgboost/onnx in `backend/requirements.txt`; no model
artifact, no model registry, no training job, no scoring service. Detection is 100% deterministic:
set-membership facts + hardcoded numeric thresholds + a fixed additive point table with family caps.

### 1.1 Data substrate (this part is already right)

| Store | Grain | Notes |
|---|---|---|
| `traces` | span | `principal_id`, `principal_name`, `caller_service`, `caller_ip`, `source_group`, `target_service`, `operation_key`, `auth_result`, `status_class`, `duration_ms` |
| `metric_buckets` | 1m + 5m × (caller, target, principal, operation) | exact p50/p95/p99 (`quantilesExact`, parity-tested vs Python nearest-rank) |
| `metric_buckets_agg` | same, AggregatingMergeTree states | shadow path, **cutover OFF** (needs identity-rich data) |
| `service_edges`, `principal_service_edges` | edge | topology + first_seen/last_seen |
| `principal_baselines`, `principal_hourly_activity` (dow,hod), `principal_daily_stats`, `principal_sources`, `principal_operations`, `principal_relationships` | per-user | the existing "normal shape" stores |
| `historical_registry`, `established_baselines`, `candidate_behaviors` | per-user × dimension value | novelty facts; promotion rule = 3 distinct days **and** 5 distinct 15m windows |
| `principal_change_events`, `incidents`, `anomalies`, `operator_overrides` | event | output contract |
| `telemetry_quality_windows` | window | collection-gap / linkage-rate gates |

Live volume (measured just now): 59,483 traces, **18 principals**, 10 targets, 38 operations,
spanning only **2026-09-16 08:04 → 11:50 PT (~3.9 h)**. 5m buckets: 11,425 rows; 1m: 25,833 rows.
Per `(principal, 5m)` window: median **29** rows (p95 51, max 84) — i.e. 29 distinct
(caller,target,operation) combinations per user-window. Vector material is plentiful;
*history length* is the binding constraint, not density.

### 1.2 Baseline model as built (`backend/app/services/baseline.py`)

- Keyed by `(dimension_type, dimension_value, hour_of_day, day_of_week)`.
- Dimensions: `service`, `caller_target`, `target_operation`, `principal_target`.
- Metrics per key: `rps_median/mad`, `latency_p50_median`, `latency_p95_median/mad`, `error_rate_median`.
- `WHERE bucket_size = 300` — **the 1m rollups are never baselined today**.
- One metric at a time. No joint/covariance/combination notion anywhere.

### 1.3 Detector inventory and its real thresholds

Service-centric (`anomaly_detection.py`, entity = service, 5m only):
`traffic_spike` (cur > max(2×med, med+3MAD) and reqs≥50), `traffic_drop` (cur < 0.25×med),
`latency` (p95 > max(1.8×med, med+3MAD)), `error_rate` (cur > med+0.04), `new_service_edge`,
`new_principal_edge`, `unusual_time` (hardcoded 02:00–04:00 UTC + hardcoded service exclusion list),
`user_new_source_ip`, `ip_new_user`. Note p95 is aggregated as `MAX(latency_p95)` across rows — a
max-of-maximums, not a true service-level percentile.

Principal-centric (`behavioral_engine.py`, entity = `principal_id`):

| Detector | Trigger (as coded) |
|---|---|
| `OPERATION_MIX_SHIFT` | per (principal,target): one op's share ≥ hist share **+20pp**, ≥25 obs, cur ≥100, hist ≥200 |
| `TARGET_FANOUT_SURGE` | distinct targets ≥3, `cur > hist_max` **and** `cur ≥ 2.5 × hist_median`, ≥10 historical 15m windows |
| `SOURCE_FANOUT_SURGE` | distinct `source_group` ≥3, `cur > hist_max` and `≥ 2.0 × hist_median` |
| `PRINCIPAL_RATE_SURGE` | `cur > p99` **and** `> 3 × median` **and** excess ≥50, same-hour history only, ≥5 windows |
| `CALLER_PRINCIPAL_SWITCH` | historical dominant principal ≥80% share, then a different principal ≥10 reqs |
| `AUTH_FAILURE_BURST` / `FAILURE_THEN_SUCCESS` | ≥5 explicit failures in window / failure then success |
| `DORMANT_REACTIVATED` | gap ≥ `principal_dormant_days`, ≥5 prior obs |
| `UNUSUAL_TIME` | readiness ≥28 days + ≥10 active days, then year-of-week style logic |
| `NEW_CALLER/TARGET/OPERATION/RELATIONSHIP/SOURCE_IP/IP_CALLER_PAIR/PRINCIPAL_ON_SOURCE`, `USERNAME_FIRST_SEEN`, `RELATIONSHIP_DISAPPEARED/REAPPEARED`, `IDENTITY_FAILURE_RATE_SHIFT`, `DATA_QUALITY_*` | pure set-membership facts + readiness gate |

Scoring: `EVENT_SCORES` fixed points (NEW_TARGET 25, DORMANT 30, FAILURE_THEN_SUCCESS 35, …) →
`family_scores = min(cap, Σ contributions)` with caps origin 35 / access 40 / activity 35 /
identity_mapping 30 / authentication 45 → `incident.score = min(100, Σ family_scores)` →
priority ≥50 high, ≥20 medium. Incidents: 30m idle close, 24h lifetime, successor chain.
Explainability: a fixed 7-question JSON blob per event + `suppressed_contributions_json`.

Readiness gates already in code (`evaluate_readiness_from_stats`): novelty ≥7 days + ≥3 active days
+ ≥100 obs (low-confidence tier at ≥10 obs); rate/mix/fanout ≥14 days + ≥5 active days + ≥200 obs;
time-of-week ≥28 days + ≥10 active days.

---

## 2. Element-by-element comparison

| Proposed ML element | Current status | Detail |
|---|---|---|
| **5m per-user multivariate anomaly (primary task)** | ❌ missing | Baselines are per-dimension, per-metric, univariate. No joint vector, no combination scoring, no per-user 5m expectation at all. |
| 1m early-change signal | ⚠️ substrate only | 1m rollups are computed and read by `/overview` + blast radius, but **no detector reads `bucket_size=60`**. No spike/delta logic on 1m. |
| Sudden spike (traffic/error/scope) | ⚠️ 5m univariate only | `traffic_spike`/`error_rate` exist at 5m service grain; no 1m responsiveness layer; no scope-count jump (caller/op/target) spike. |
| Behavior distribution shift | ⚠️ wrong shape | `OPERATION_MIX_SHIFT` is a single-op ≥20pp delta. No target-distribution shift detector at all. No whole-distribution distance. |
| Behavior regime change (5m sequence) | ❌ missing | Each window is judged independently. Incidents aggregate discrete events by principal+category, but nothing models "stayed different N consecutive windows". |
| Multivariate combination judgment | ❌ missing | Scoring is additive points with caps — independent evidence, not joint likelihood. Two individually-normal deviations that co-occur score exactly the same as two unrelated ones. |
| Feature: rps / error_rate / p95 + ratio-to-baseline + MAD score | ⚠️ internal only | Stored as `BaselineMetric` medians/MADs for 4 dimension types; never materialized as a per-user feature vector, never combined. |
| Feature: distinct callers / targets / operations / IPs | ⚠️ partial | targets → `TARGET_FANOUT_SURGE`; IPs → `SOURCE_FANOUT_SURGE` via `source_group`; callers/operations have no per-window distinct count (only `principal_daily_stats` at day grain: unique_callers/sources/targets/operations). |
| Feature: *_count_change (caller/target/op/ip) | ❌ missing | Only implicit `cur vs hist_max/median` inside the two fanout surge rules. No stored delta. |
| Feature: target_entropy / operation_entropy | ❌ missing | `grep -ri entropy|js_divergence|jensen|kl_div backend` → **zero hits**. |
| Feature: target/operation JS divergence, top_*_share | ⚠️ partial | `distribution_share` exists in `principal_baselines` (top-share readable), but no divergence computation against a historical distribution. |
| Feature: new_callers/targets/operations/ips/relationships | ✅ as facts, ❌ as features | Exactly the separation the design asks for — these are deterministic set-membership facts, no ML. Missing only the *aggregation into numeric counts* (`new_target_count = 1`) that a vector needs. |
| Feature: hour_of_day / day_of_week | ✅ | Present in baseline keys and `principal_hourly_activity(dow, hod)`. |
| Feature: activity_time_deviation | ⚠️ crude | `DORMANT_REACTIVATED` (day-scale gap) + `UNUSUAL_TIME` (hardcoded 02:00–04:00 UTC with a hardcoded exclusion list). Not a per-user learned temporal profile. |
| Feature: minutes_since_last_activity | ⚠️ partial | Used only for the `Active/Inactive` label (`principal_active_minutes`); not a feature. |
| Output `{anomaly_score, feature_deviations}` | ❌ different contract | Current output = discrete `change_type` events + integer 0–100 additive score + family caps + priority + 7-question text. API/UI (`/incidents`, `/user-changes`, `/anomalies`) renders that shape. |
| Model learns the user's normal behavioral shape | ⚠️ partial, univariate | `principal_baselines` / `_hourly_activity` / `_daily_stats` / `_sources` / `principal_service_edges` hold the right *reference material*, but as independent per-dimension counters, not as a conditional joint state. |

---

## 3. Conceptual divergences worth deciding explicitly

1. **Unit of analysis.** `anomaly_detection.py` is service-centric (entity = `target_service`);
   the proposed ML is `(principal × 5m window)`. The ML layer belongs on the
   `behavioral_engine` / `principal_relationships` side, reusing `principal_id` normalization
   (`{environment}:{principal_name}`), not on the service side.
2. **Points vs probability.** The current additive-with-caps score answers *"how much independent
   evidence?"*; ML answers *"how unlikely is this joint state for this user?"* These are
   complementary, not competing. Keep the point table authoritative for *what* changed; add the
   ML score as a sibling signal. The 7-question explainability blob stays as-is — the ML layer
   adds `feature_deviations` beside it, matching the design's own "don't make ML write the prose".
3. **Hardcoded magic numbers.** 20pp / 2.5× / 3× / p99 / ≥50 excess / 02:00–04:00 UTC / service
   exclusion list are all hand-picked constants. ML should replace the *combination* judgment —
   not necessarily these rule triggers, which are useful deterministic scaffolding.
4. **Scale reality the design does not address.** The live testbed has **18 principals and 3.9 h of
   history**. Every existing readiness gate (≥7 / ≥14 / ≥28 days) blocks almost everything today.
   Consequences:
   - per-user *supervised* or deep models are impossible here; the only viable first model is
     per-user **unsupervised** anomaly scoring (robust z/MAD-normalized distance, or
     IsolationForest/LOF on peak ~288 windows/day/user) plus a shared global prior across users;
   - a **warm-up/backfill** path is mandatory before the model can produce anything: the demo
     generator (`backend/scripts/generate_15day_demo_data.py`) and ES (`apm-7.17.24-transaction-000001`,
     57,990 docs) are the two available history sources;
   - the ML readiness gate must be a **new** detector class (suggested
     `MULTIVARIATE_BEHAVIOR`) that emits at most a low-confidence score until ≥7 days / ≥100
     user-windows exist, rather than silently producing noise.
5. **Do not walk raw traces again.** `principal_relationships._process_incremental_row` already
   iterates row-by-row (batched, after the 10×/52× perf fix). Feature vectors must be built from
   `metric_buckets`/`metric_buckets_agg` via SQL (`countDistinct`, `quantiles`, share/entropy in
   SQL), not from another per-row Python pass, or this becomes a second CPU hog on the 2-core
   aarch64 node.

---

## 4. Minimal integration plan consistent with the existing design

1. **Vector builder (SQL, per user per 5m):** one aggregate query over `metric_buckets`
   (`bucket_size=300`, grouped by `principal_name` + `bucket_start`) producing the ~20 features:
   volume (rps, request_count), performance (error_rate, p95, latency p50/p95 from `quantilesExact`
   rows), scope (`countDistinct` callers/targets/operations/ips), novelty (left-join counts against
   `historical_registry`/`principal_sources` by `first_seen`, so the same facts feed both the rule
   engine and the vector), distribution (`entropy` of target/operation shares + `top_target_share`),
   temporal (dow, hod, minutes since previous window for that user).
2. **New per-user 5m baseline store**, e.g. `principal_window_baselines`
   (`principal_id, dow, hod, feature_name, median, mad, p95, sample_count, updated_at`), rebuilt
   from the user's own history by a new worker stage after `rebuild_baselines`.
3. **Derived deviation features:** `rps_ratio_to_baseline`, `rps_mad_score`,
   `error_mad_score`, `p95_mad_score`, `*_count_change` (cur − rolling median of the same
   feature over the user's recent windows), `target_js_divergence` / `operation_js_divergence`
   (current share vector vs the user's conditional distribution for that (dow, hod) bucket).
4. **Scoring stage** `score_behavioral_anomaly` inserted after `rebuild_baselines` and before
   `detect_anomalies`; output row
   `{principal_id, window_start, window_size, features_json, anomaly_score, feature_deviations_json, model_version}`
   into a new `behavior_feature_vectors` table (MergeTree ORDER BY
   `(principal_id, window_size, window_start)`, TTL 90d to match `metric_buckets_agg`).
5. **1m layer:** same vector builder at `bucket_size=60`, but only the spike/delta subset is
   computed; result is a `sudden_change` flag + timestamp only. It never opens an incident on its
   own — 1m says "something just changed", 5m confirms (matching the design's intent and avoiding
   one noisy minute becoming an incident).
6. **Regime change:** require the 5m `anomaly_score` to stay above threshold for N consecutive
   windows for that user before escalating priority; the existing incident lifecycle (30m idle
   close, 24h lifetime, successor chain) already gives the natural container.
7. **Output exposure:** add `anomaly_score Float64` and `feature_deviations_json String` to
   `incidents` and the anomaly explainability payload; keep the 7-question text, `family_scores`,
   and `suppressed_contributions` untouched. The UI's "Behavior anomaly: 0.91 / Main changes: …"
   block is then a render of `feature_deviations` sorted by magnitude — no LLM needed.
8. **Model artifact:** IsolationForest (sklearn, CPU-cheap, no GPU on this node) per user once
   ≥N windows exist, else robust MAD-distance fallback; persist `model_version` on every scored
   row so shadow-vs-live comparison is possible before cutover (same discipline already used for
   `metric_buckets_agg` shadow states, currently OFF).

---

## 5. Bottom line

- The **substrate** the design needs already exists: 1m and 5m rollups with exact percentiles,
  per-user reference stores, a clean principal identity model, and — importantly — the
  deterministic facts (`NEW_TARGET`, `NEW_CALLER`, `NEW_OPERATION`, `NEW_IP`, `NEW_RELATIONSHIP`,
  `DORMANT_REACTIVATED`) already implemented as exact set-membership checks, which is exactly what
  the design says must stay outside ML.
- The **judgment layer** is entirely missing: there is no joint/multivariate per-user state, no
  entropy or distribution-divergence feature, no 1m detection path, no consecutive-window regime
  logic, and no learned model of "this user's normal shape" — current abnormality decisions are
  one-metric-at-a-time comparisons against either a fixed constant or a median/MAD plus a
  hand-picked multiplier.
- The two designs are **compatible, not conflicting**: the deterministic engine stays the "what
  changed" authority (and the source of the novelty features), while the ML layer becomes the
  "is this combination unusual for this user" authority. The main work is a SQL-based feature
  builder over the existing 5m rollups, a per-user 5m baseline store, a scoring stage in
  `worker.py`, and two new columns on the explainability contract.
- The binding constraint is **history, not code**: 3.9 h of data / 18 principals on the live
  testbed means the first model must be per-user unsupervised with a readiness gate and a
  backfill/warm-up path, or it will report noise as anomaly.