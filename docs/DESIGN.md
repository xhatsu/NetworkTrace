# TraceScope design

## Product structure

The desktop shell has a narrow estate navigation rail, a persistent investigation filter bar, a visible freshness indicator, and four routes: Overview, Services, Accounts, Topology, and Anomalies. Filter state is encoded in the URL. Overview presents eight estate signals, comparative trends, a latency/failure heatmap, ranked service and operation tables, account distribution, and recent anomalies. Service and account routes preserve the same time window and drill into operations, callers, dependencies, instances, account usage, traces, and relevant anomalies. Canvas topology has an equivalent sortable edge table and selection panel.

React components are split into the shell/filter controls, reusable chart/card/table primitives, page-level data loaders, and an isolated `TopologyCanvas`. TanStack Query owns API caching/refetching; Recharts renders accessible SVG charts; the topology alone uses Canvas.

## Storage

Migrations create:

- `events`: sanitized transaction facts keyed by a deterministic `event_uid`; indexed by timestamp, service/time, operation/time, account/time, trace, parent, outcome, and status.
- `services`, `accounts`: first/last-seen inventory.
- `latency_rollups`: minute/service/operation/account aggregates with mergeable histogram JSON; only common dimensions are materialized.
- `topology_edges`: time-bucketed confirmed or inferred directed relationships with evidence text.
- `anomalies`, `anomaly_occurrences`: lifecycle and recurrence groups, current/baseline values, samples, evidence, representative traces, and detector details.
- `checkpoints`, `jobs`, `schema_migrations`: idempotent ingestion, worker state, and migration history.

SQLite runs in WAL mode with a 5 s busy timeout. Imports use bounded batches and `BEGIN IMMEDIATE` short transactions. A single worker process owns analytical writes. The repository protocol keeps SQL behind `SQLiteRepository`, allowing replacement without changing route or detector code.

## API

`GET /api/v1/dashboard/summary`, `/series`, `/heatmap`, `/rankings`; `GET /services`, `/services/{name}`; `GET /accounts`, `/accounts/{username}`; `GET /topology`; `GET/PATCH /anomalies`, `/anomalies/{id}`; `GET /traces/{trace_id}`; `GET /ingestion/status`; and `POST /ingestion/import` (local admin workflow only, disabled unless configured). Query models validate ISO time, a maximum 31-day interactive range, enumerated breakdowns, and bounded pagination.

## Ingestion and jobs

The importer streams JSON arrays, Elasticsearch `hits.hits`, bulk-style NDJSON, and one-object-per-line NDJSON. `_source` wins over `fields`, so an Elasticsearch hit is one event. Dot paths and nested paths are both accepted. Basic authorization is decoded in memory only; the username is stored, while the raw header and password are discarded before event construction, logging, hashing, or persistence. Invalid credentials become an unknown account marker without error detail.

The optional Elasticsearch reader uses a read-only search request sorted by `@timestamp,_id`, an incremental `search_after` checkpoint, and a configurable lookback for late arrivals. Deterministic event IDs make replay harmless. The worker recomputes affected minute rollups and edges, then baselines and anomalies. Late arrivals overwrite only impacted rollup buckets; they do not increment an existing aggregate.

Retention and `PRAGMA optimize` run as worker jobs. Interactive endpoints read aggregates and bounded indexed detail rows; they do not perform detection.

## Baselines and anomaly rules

For each current one-minute entity bucket, the preferred baseline is matching minute-of-week buckets over prior weeks. With less history, the fallback is the preceding 24 one-minute buckets, excluding the two persistence buckets. Numeric traffic and latency detectors use the median plus/minus `max(3 × 1.4826 × MAD, absolute_floor)`. Zero-MAD fallback uses an empirical 10th–90th range plus a measurement-specific absolute floor. Sparse series require more history and never infer a drop from absent data.

Error, auth-denial, and slow rates use Wilson proportion intervals and both a minimum count and absolute percentage-point impact. Novel account and dependency relationships compare first-seen time with the baseline window and require persistence/volume. Mix changes use total-variation distance. Dormant return requires a prior observation, a configurable absence period, and renewed minimum traffic. Instance imbalance compares operation-matched instance medians and shares, not unlike workloads.

Cold starts are labeled insufficient history. Missing buckets and known ingestion gaps suppress traffic-drop evaluation. Zero baselines yield absolute change only. Sampling changes are called out and can suppress volume detectors; unknown sampling is stated as a limitation. Two consecutive anomalous buckets are required by default. Recurrences share an entity/type fingerprint. See `docs/ANOMALIES.md` for detector-specific thresholds.

## Topology evidence and rendering

Confirmed edges require a child client span whose parent transaction/span resolves to a different service in the same trace, or a child server record with an explicit peer service and valid parent evidence. Shared trace IDs alone never create an edge. Inferred edges require a time-valid service/address mapping or an explicit destination service without parent linkage and are dashed. Account relationships are a separate view; usernames never identify callers. Unknown callers remain `Unknown caller`.

The API returns grouped nodes by default, with service nodes revealed by group/module expansion and neighborhood selection. The Canvas stores stable coordinates by node ID, runs layout only when graph membership changes, draws via `requestAnimationFrame` with DPR scaling, uses a grid spatial index for hit tests, and keeps selection/positions across refreshes. Traffic width uses a bounded square-root scale; color maps to selected health metric. The edge table provides the keyboard-accessible equivalent.

## Assumptions and limitations

The current event model treats transaction documents and server spans marked `span.kind=server` as server work; malformed or ambiguous span kinds are not counted as inbound RPS. Inferred topology depends on explicit destination-service fields until an authoritative mapping feed is provided. SQLite is appropriate for this single-node evaluation, but prolonged raw retention at millions of events requires aggressive retention or a production analytical store. Histograms trade exact tail values for bounded storage. Browser graph performance depends on grouping; rendering all 300 nodes and all edges is intentionally not the default.
