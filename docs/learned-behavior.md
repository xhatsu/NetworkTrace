# Learned Behavior workspace

`/behavior` is a separate shadow-learning workspace. It does not emit existing
Changes, change detector severity, send notifications, or enforce network access.
Its tabs are Overview, Learning graph, Profiles, Deviations, and Contracts. Profile and deviation
detail routes expose TPS first, a keyboard-accessible typed relationship graph,
coverage, history, trace references, and scoped review actions. EN/VI are supported.

## Runtime and ownership

- Python worker, FastAPI/Pydantic, ClickHouse, React/TypeScript/TanStack Query,
  Recharts for TPS/history, and SVG for the relationship graph. No new runtime
  dependency or graph database.
- `OTEL_BEHAVIOR_LEARNING_ENABLED=true` enables standalone shadow learning by
  default. `OTEL_BEHAVIOR_BUDGET_SECONDS=20` is the cooperative source-stage budget
  (clamped 5–60 seconds). Existing source request/query timeouts still apply; this
  is not a hard process deadline. Each ES pass reads at most two 250-bucket pages.
- Helm `behavior.enabled` defaults false. Enabling it requires `app.replicaCount=1`.
  One standalone worker owns scheduling. Local file locks serialize worker/replay
  and contract writes; they are not distributed locks. Do not run a second owner
  on another host against these tables.
- Migrations `016_learned_behavior.sql` and `017_online_behavior_graph.sql` are additive. Rollback: disable the behavior
  worker setting and restart; preserve tables and contract audit history.

## Sources and limits

Each source has its own namespace, cursor, completeness markers and profiles.
Never sum counts across sources or treat their differing operation normalization as
an observed behavioral change.

| Source | Input | Initial window | Attribution |
| --- | --- | --- | --- |
| `legacy_metrics` | Existing five-minute metric buckets | Up to 30 retained days | Environment unknown, historic compressed operation keys, no exact trace examples |
| `elasticsearch` | Transaction/server observations, grouped directly from ES | Up to 7 days | Preserves recorded environment and operation; only explicit caller fields; missing attributes stay unknown |
| `clickhouse` | Retained server traces | Up to 1 day | Uses stored canonical fields, which may include normalizer defaults |

The first live audit found 40,641 five-minute metric rows and no retained ClickHouse
raw traces. A sampled current ES bucket had no environment/caller/IP evidence;
that absence is disclosed, never inferred from legacy relationships. These counts
are audit observations, not hardcoded assumptions.

Environment, source, caller, observed credential name, target, and operation form
the exact relationship key. Credential names are observed identifiers, not proof
of a human actor or globally verified identity. Different authentication realms
with indistinguishable recorded names cannot be separated without more telemetry.
IPs are bounded observed-peer samples (10/bucket, 20/profile), explicitly labeled
infrastructure or unverified. IP presence does not establish original client
identity; IP novelty is not used to accuse a user. Sources lacking IPs show unknown.

Source windows disclose materialization progress, observed-field fractions and
unknown collection/sampling coverage. Completing a query is not proof of complete
instrumentation. Authentication counts use explicit outcomes, never infer success
from HTTP 2xx. Known collection-gap and metric-incident windows are excluded from
reference training. No availability/traffic-drop finding is emitted from silence.

Hard bounds fail without replacing the previous profile snapshot: 100,000
relationship windows/day, 400 ES pages/day, 100,000 relationship days/source,
5,000 profiles/source, and 10,000 contract audit events. API pages are 25 by default,
100 maximum. Cap errors appear as source update failures; raising caps requires a
capacity review. The first integration is intentionally bounded, not unlimited.

## Learning and graph features

Repeated bucket rows replace earlier versions. Exact sets of bucket timestamps
and days avoid arrival-order promotion errors. Completed day generations are
published only after all pages and summaries are durable; partial generations are
invisible. Profile/deviation snapshots have a separate generation pointer.

Familiarity: emerging, established, dormant. Established requires seven observed
days of elapsed history, three eligible active days, five reference windows and
100 eligible requests. Dormancy means no observation for seven days, not proven
absence of traffic. Familiarity and operator approval are independent.

Access expansion compares a relationship's first observed day against earlier
credential history in the same source/environment: at least seven elapsed days,
three prior active days and 100 prior requests. Three distinct observed windows
establish repetition. Claims are limited to available history. A new combination
can be detected even if its caller and API were individually familiar. Unreviewed
expansions cannot train their own clean reference. Historical samples used to
bootstrap familiarity were not operator-approved ground truth.

The online graph persists typed Service, API, Credential and observed-IP nodes,
with `calls`, `owns`, `credential_on_call` and `peer_on_call` edges. Unknown nodes
are omitted. Credential/IP association keys include the complete relationship,
preventing invented cross-products. Both identified and anonymous observations enter Service/API learning; anonymous observations never create credential nodes or credential profiles. Its TPS is scoped observed traffic, not a guarantee of total fleet coverage. IP samples have no assigned
request count or TPS because their exact volume is unavailable.

For each completed five-minute window, the engine scores against previous state,
then reinforces each observed node and edge exactly once. Decayed support follows
`support = previous_support * 2^(-elapsed_days/7) + 1`; displayed strength is
`1 - exp(-support/20)`. This measures familiarity, not authorization or safety.
Missing windows decay support but never train zero traffic.

Each relation, node and volume-bearing edge learns an exponentially weighted TPS
mean and variance (alpha 0.05). Rate scoring needs 12 eligible samples across three
active days. The previous mean/variance score the next observation before any
update. Material surges (at least 3x the mean, +100 requests/window and 6 scaled
standard deviations) are withheld from reference updates; three contiguous
surging windows produce a `graph_tps_shift` Watch candidate. Influence after warmup
is bounded to three scaled standard deviations.

Persistent new levels are accepted rather than withheld forever. When at least 27
of the last 36 eligible observed windows (three hours of observations) are material
surges, the reference is re-seeded to their median TPS with a MAD-based spread, the
surge streak resets, and `level_shift` (`at`, `from_tps`, `to_tps`, `windows`) is
recorded on the entity and exposed in `graph_learning`. Shorter surges stay withheld.
Incident/collection-gap windows never count toward acceptance. The profile same-UTC-hour
TPS reference then restarts at the first window of the new level (`tps.reference_start`),
so it needs fresh readiness instead of comparing against the old level for days.
Trade-off: a sustained malicious surge also stops alerting after about three hours;
the recorded `level_shift` keeps that acceptance visible. The worker now advances the
graph before building profiles so shift points are available. Algorithm version is
`online-behavior-graph-v4`; older snapshots replay automatically. Known incident/collection-gap
windows reinforce observation support but cannot train TPS. Missing caller fields
still permit measured credential/API rate learning within an isolated unknown-caller
scope; they never fabricate a service-call edge.

A new relationship attached to a credential with at least 12 effective observation
windows over three days can produce `graph_edge_novelty` after three observations.
Existing equivalent deviations are not duplicated. Only observations within 30
minutes produce new graph candidates. Familiarity can increase while a suspicious
volume remains excluded from the traffic reference. These scores are not calibrated
probabilities. This is online statistical learning, with no neural network or
reinforcement-learning policy.

Per-window input digests make retries idempotent. Late corrections, earlier inserted
windows, quality revisions, retention eviction or algorithm-version changes trigger
deterministic replay from retained daily memory. Graph snapshots are stored before
the same source publication pointer switches profiles and graph together. Limits:
40,000 nodes, 50,000 edges and 5,000 relationships per source; overflow preserves
the previous snapshot. `/api/v1/behavior/graph` returns at most 300 edges, with
source/search/neighborhood filters and disclosed counts. The UI draws at most 80
matching edges, supports keyboard node selection and neighborhood focus, and shows
strength, observed TPS, learned next-window TPS and pre-update surprise.

## TPS-aware learning

TPS is requests / 300 for each original five-minute bucket, including fractional
values. Missing windows remain null and are not imputed as zero. The detail plot
shows the latest observed day using original buckets and the selected display
timezone, with reference values grouped by UTC hour.

Baseline uses eligible active windows from earlier days at the same UTC hour;
the current day cannot train its own reference. Readiness needs at least 12
comparable windows, three prior days, and seven elapsed days for the relationship.
Median and MAD describe active windows, not an unconditional traffic expectation.
The displayed preliminary baseline can exist before detection readiness is met.

A `traffic_surge` candidate requires all three latest contiguous five-minute
buckets to exceed the maximum of 3x median, median + 6 MAD, and median + 100/300 TPS.
The latest observation must be within 30 minutes and the reference must be positive.
It remains Watch; access approvals do not approve volume surges. No TPS-drop
claim is made without reliable coverage. Daily latency is maximum bucket P95,
never an averaged percentile.

## Contracts and advisory results

Contracts append immutable events for one exact relationship/source/environment:
approved, temporary, prohibited or unreviewed (revoke/reopen). Temporary approvals
expire within 90 days. Expiry never revives an older approval. Prohibitions are
evaluated at observed bucket times, without retroactively condemning earlier
activity. An `expected_event_id` check returns HTTP 409 on concurrent stale review.

Writes honor `OTEL_API_KEY` if configured, matching existing dashboard access
conventions. Reviewer identity is operator supplied and labeled as such, not an
authenticated-person assertion. Contract events currently have no TTL; the bounded
10,000-event limit fails closed rather than silently discarding audit history.

One additional bounded Jev assessment per worker pass is allowed when the existing
semantic integration is enabled (five-second advisory budget). Only hashed IDs and
bounded structured facts leave the worker. Names, addresses and raw payloads do not.
Reads return stored assessments, with prior versions marked stale. Jev cannot
approve contracts, enforce access or change deterministic findings.

## Retention, late data and recovery

Full observation records expire after 30 days. Daily memory (including compact
bucket times/counts needed for distinct-window/TPS calculations) expires after 90
days. Old profile and graph snapshots expire after seven days. Hourly asynchronous cleanup
reclaims obsolete generations after a one-hour reader grace period, protecting
published and in-progress generations. Raw ES/ClickHouse retention is unchanged.

Completed source windows refresh as new five-minute windows become available.
A window becomes learnable `OTEL_BEHAVIOR_LEARN_GRACE_SECONDS` (default 90,
range 30-300) after it closes, once the metric stage has written its one-minute
buckets. Idle windows and windows the metric stage has not reached fall back to
the former one-window lag; 300 restores that lag everywhere. The learned-through
point never moves backwards. Late arrivals that change a learned window trigger
the graph's deterministic replay. Topology ages count from the window end.
Yesterday is refreshed periodically for late data; current-day history is also
replaced, never incremented. Older late data needs a retained-source replay. This
cannot reconstruct raw facts that have already expired. ClickHouse refreshes preserve already learned bucket prefixes outside the one-day raw TTL.

With the same environment as `run_server.sh`, run:

```sh
timeout 60s .venv/bin/python -m backend.scripts.replay_behavior --source elasticsearch --days 7 --budget-seconds 45
```

The script acquires the same local owner lock. Retry if a worker cycle owns it.
Pending pages and replay progress survive bounded invocations. Contracts are
preserved. Source errors preserve the previous published snapshot and are retried.
The initial backfill is chronological; coverage progress is visible on Overview.

## Labelled replay benchmark

`backend/scripts/benchmark_behavior.py` replays synthetic five-minute buckets with
known injected events through the same pure worker path (`summarize_day`,
`advance_graph`, `build_profiles`, `graph_deviations`) at worker cadence. It uses
no database. Scenarios: steady diurnal and sparse Poisson controls, a 1-hour 5x
surge, a permanent 4x level shift, a new API for an established credential, and a
2.5x surge on a high-volume API. It reports detection, delay and stale/false alert
steps; known gaps are reported without failing the gate.

```sh
.venv/bin/python -m backend.scripts.benchmark_behavior [--seed N] [--step 3] [--json]
```

Current result (seeds 1, 2, 3 and 7): 6/7 pass. The level shift alerts for about
2h45m, then stops (previously 61 stale steps over roughly 22 hours). Known gap: the
2.5x high-volume surge is missed because of the fixed 3x material floor; count-based
scoring is the planned fix. Run this benchmark before changing thresholds.

## Validation

- Isolated pytest harness excludes the root conftest's broad database cleanup.
- Tests cover exact keys, late/repeated windows, partial publication, empty
  replacement, snapshot reads/cleanup, familiarity vs approval, nonretroactive
  prohibitions, expiry, optimistic conflicts, auth, source/operation mapping,
  infrastructure IPs, TPS persistence/materiality/fractional baselines, API bounds,
  and sanitized advisory input. Graph tests cover reinforcement, decay, score-before-update, withheld spikes, deterministic correction replay, idempotency, IP evidence windows, source isolation, missing callers, and API bounds.
- Opt-in `tests/test_behavior_storage.py` creates and drops only a UUID-named test
  database. Set `OTEL_BEHAVIOR_STORAGE_TEST=true` to run this integration test.
- Live source/API smoke checks and Chromium cover EN/VI, all five tabs, profile and
  deviation details, graph keyboard selection, TPS charts, mocked temporary review
  submission, and 1440/390/844px layouts. No production contract is created by tests.

## Learned topology replacement

`/topology` now uses `/api/v1/behavior/topology`, replacing the window-based
seven-day/selected-window merge and its separate legacy drilldown queries. The old
backend topology endpoints remain available for other consumers. The new page
keeps the existing canvas, free card dragging, zoom/reset, re-layout, service
expansion, API/credential lists, reverse credential navigation, search, selected
path highlighting, and entity navigation from the floating inspector.

The graph engine now also reinforces `service_call` edges once per completed
window, aggregating API observations before updating each service pair. The
algorithm version is `online-behavior-graph-v3`; older snapshots replay automatically.
The canvas projects these persisted service edges. It never creates a service edge
from a credential association or substitutes a target for a missing caller.

Source and environment selectors replace the time slider. A missing environment
selection defaults to `unknown` if present, otherwise the first recorded environment.
Sources/environments never merge. Global dashboard time filters do not truncate
learned memory. Connection width represents decayed observation strength; dashed
connections mean last observed more than 30 minutes ago, not proven inactivity.

Node/edge inspectors show last observed TPS, learned next-window TPS, pre-update
surprise, reference/withheld window counts, retained request counts, and observation
times. The small chart uses the last observed day's original buckets, fractional
scales and gaps. No missing latency, error, availability, or health values are
fabricated. Node metrics describe its full learned neighborhood within the chosen
source/environment; path selection scopes highlighting and IP evidence. Service
nodes can represent both incoming and outgoing observed calls. IP samples disclose
observation support without invented per-IP TPS.

The snapshot is bounded to 500 services and 2,000 service edges. All related API
and credential entities within that projection remain searchable; lists page
locally in increments of 100. Display truncation and loaded/total counts are shown.
The model retains its separate source capacity limits. Empty/learning/error states
never fall back silently to the legacy topology data.

Initial topology placement uses a bounded deterministic force layout with hub attraction, card repulsion and spiral collision resolution. Anonymous service traffic is retained independently of credential-profile eligibility. The plain canvas and straight edges form a scattered spider mesh. Re-layout repeats this arrangement; manual dragging remains unrestricted.

## Metrics-only learning input

The learning engine consumes only the worker-owned `metric_buckets` read model at five-minute grain (`legacy_metrics`). It does not read raw ClickHouse `traces` or Elasticsearch APM transactions. Elasticsearch and raw traces may continue to support ingestion, Trace Explorer, or upstream metric materialization, but they are not direct learning inputs. Missing or late metric buckets remain data-quality gaps and never trigger a raw-trace fallback.

## Operator UI and Changes integration boundary

Topology exposes observed TPS, expected TPS when reference-ready, recent trend,
relative freshness and a plain-language behavior state. Cumulative training/request
counters and first-seen timestamps remain internal model data; they are not shown
in the operator inspector. The UI consumes bounded summaries on a one-minute
refresh, independent of the number of individual traces ingested. Relationship
cardinality and peak ingestion rate still determine system capacity.

Changes now includes learned metric deviations from the `legacy_metrics` snapshot as explicit `learned_behavior` signals. Each signal carries the metric-bucket source scope, reference sample/day counts, observation bucket, persistence, and learned baseline/current TPS values. Existing detector signals remain intact and are correlated into the same bounded episodes. Learned novelty or elevated TPS alone is a Watch/review candidate and cannot escalate severity without the existing measured-impact, persistence, and baseline gates. Jev remains advisory; raw trace evidence is not used to create these learned signals.

## Access flow and matrix

`GET /api/v1/behavior/access` joins the learned graph with current-window observation state for the Sankey (`view=flow`) and credential × API matrix (`view=matrix`). It reads only the graph snapshot and profile/deviation read models. See the 2026-09-30 section of `AGENTS.md` for states, caps and IP-role rules.

## Trace-free user behavior

User behavior (principal profiles, behavioral detectors, user/IP anomalies) never reads raw `traces`. The worker builds `principal_activity_5m` (35-day TTL) from the caller-resolved trace source for each aggregation slice, and every consumer reads that rollup. `principal_activity_consumed` records what was already processed per row so a rewritten bucket contributes only its increase. Raw traces can expire after one day without losing behavior history. Re-resolved callers can be counted again under a new row key; decreases are never subtracted. See AGENTS.md "Trace-free user behavior and mid-request dependency edges".
