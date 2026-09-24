# Topology and API read-model boundary

## Data access

FastAPI dashboard and topology reads use `metric_buckets`, `topology_*` relationship rollups, `service_instance_edges_5m`, and the existing principal, anomaly, change, and incident read models. Interactive handlers in `InteractiveTopologyRepository` use a bounded time range and keyset pages for API, principal, and user-service lists.

`traces` remains an ingestion and worker input table. The aggregation worker may read it while materializing five-minute topology rows. API handlers and read repositories must not add `FROM traces` or `JOIN traces` queries, except for the explicitly temporary Trace Explorer routes described below. A regression test checks API modules, topology methods, user repositories, investigation evidence, and limits trace-table access to ingestion and those two Trace Explorer methods.

In Elasticsearch mode, topology graph and drill-down queries project the worker's five-minute `metric_buckets` into the same service/API/principal relationships. They do not issue interactive aggregations against Elasticsearch documents. Source-IP evidence is available only where `topology_principal_ip_5m` has been materialized.

Trace Explorer's `/api/v1/traces` list and waterfall routes remain a temporary exception: they read the configured trace store, which is Elasticsearch in ELK mode or ClickHouse `traces` in ClickHouse mode. The API role therefore needs `SELECT traces` when Trace Explorer is enabled in ClickHouse mode; in Elasticsearch mode it does not. A future `trace_explorer_spans` read model can remove this exception while preserving the waterfall UI.

## Database roles

`OTEL_CLICKHOUSE_ROLE` selects the connection identity per process:

| Role | Credential variables | Access needed |
| --- | --- | --- |
| `api` | `OTEL_CLICKHOUSE_API_USER`, `OTEL_CLICKHOUSE_API_PASSWORD` | Select read models and insert ingested spans; add `SELECT traces` only for the temporary ClickHouse-mode Trace Explorer exception |
| `worker` | `OTEL_CLICKHOUSE_WORKER_USER`, `OTEL_CLICKHOUSE_WORKER_PASSWORD` | Read raw spans, insert/update rollups, and read worker checkpoints |
| `owner` | `OTEL_CLICKHOUSE_USER`, `OTEL_CLICKHOUSE_PASSWORD` | Schema migration and administration |

If role-specific variables are empty, the existing `OTEL_CLICKHOUSE_USER` and `OTEL_CLICKHOUSE_PASSWORD` are used for compatibility. The Kubernetes and Helm app workloads set `api`, `worker`, and `owner` roles for their API, worker, and migration containers. User provisioning and grants remain deployment-owned. In ClickHouse mode, removing the Trace Explorer grant requires first migrating that UI to a dedicated read model.

## Topology contract and interaction

- The graph endpoint is `GET /api/v1/topology/services`; it returns only service nodes and service-to-service edges.
- Expand APIs with `GET /api/v1/topology/services/{service}/apis`; load users for a selected API with the nested `/principals` endpoint.
- User-first navigation uses `GET /api/v1/topology/users`, then `/users/{principal}/services`, then `/users/{principal}/services/{service}/apis`.
- The same read-model relationships drive both directions. API and user rows are returned as bounded pages with `limit`, `search`, and keyset `cursor` parameters.
- Service edge IDs are `service-edge:` plus the first 24 hex characters of SHA-256 over canonical source, the unit separator, and canonical target. API and user rows return these IDs so the UI highlights the existing edge.
- API selection resolves focused edge metrics through `/api/v1/topology/services/{service}/api-connections`. User selection resolves them through `/api/v1/topology/principals/{principal}/connections`, optionally filtered by `service` and `api`. The highlighted line and its TPS label use these scoped rollups.
- Service graph coordinates change on initial load or explicit Re-layout. Opening panels and selecting APIs/users only changes selection styling. Normal edges stay faint blue; selected relationships are yellow.
- Interactive time ranges aggregate five-minute worker rows; the UI never reconstructs a path from raw spans.
