# TraceScope Helm Chart

Production-ready Helm chart for deploying the TraceScope Behavioral Observability & OTel Transaction Analytics Platform on Kubernetes.

## Architecture & Workloads

TraceScope consists of the following components:
1. **ClickHouse (`clickhouse`)**: Columnar analytics database (StatefulSet).
2. **Application & Analytics Workload (`app` / `storage`)**: StatefulSet (`tracescope-app`) with single-replica schema and analytics coordination:
   - Init container: runs database schema migrations once.
   - `api`: FastAPI serving analytics queries, built-in React UI, agent stats, and internal writes on port 30102.
   - `analytics-worker`: Background worker running rollups, baselines, and anomaly detectors on a 60-second cadence.
3. **Ingest Edge (`ingest`)**: Stateless Deployment (with HPA 3–12 pods) handling OTEL/ELK trace batches, decompression, WSSE/Basic auth sanitization, and transaction-atomic deduplication on port 30103.
4. **Agent Stats (`agentStats`)**: Optional stateless Deployment (with HPA 2–6 pods) receiving oldkernel/eBPF agent heartbeat samples (merged into API pod by default).
5. **UI Frontend (`ui`)**: Optional stateless Nginx Deployment serving the compiled React 19 SPA (merged into API pod by default).
6. **Ingress**: Unified reverse proxy keeping all public endpoints identical to the host deployment (:30102).

---

## Deployment Modes & Merging Workloads

### 1. Consolidated 3-Tier Mode (Default - Balanced & Resource-Efficient)
Saves 4+ pods by default (`ui.enabled: false` and `agentStats.enabled: false`):
- UI is natively served by the Storage API pod (`/` and `/assets`).
- Agent stats are served directly by the Storage API pod (`/api/agent/stats*`).
- Ingestion runs in its horizontally auto-scaled Deployment (`tracescope-ingest`, 3–12 pods).
- ClickHouse runs as a dedicated StatefulSet.
```sh
helm install tracescope deploy/helm/tracescope
```

### 2. Full Distributed Mode
Independent workloads for every tier (5 workloads, 9–21 pods). Best for high-throughput production estates requiring dedicated Nginx UI and isolated agent telemetry scaling:
```sh
helm install tracescope deploy/helm/tracescope \
  --set ui.enabled=true \
  --set agentStats.enabled=true
```

### 3. External ClickHouse Mode
Use an existing production ClickHouse cluster:
```sh
helm install tracescope deploy/helm/tracescope \
  --set clickhouse.enabled=false \
  --set clickhouse.host="clickhouse.prod.internal" \
  --set clickhouse.password="secret"
```

### 4. Current ELK APM with ClickHouse Analytics
The default chart keeps analytics and rollups in ClickHouse, reads application trace details from Elasticsearch, and has the worker materialize ELK transaction metrics into ClickHouse. The configured service is `tmp-elk-svc` in namespace `tmp-elk`:
```sh
helm upgrade --install tracescope deploy/helm/tracescope \
  --namespace tracescope --reuse-values \
  --set storage.backend=clickhouse \
  --set storage.traceBackend=elasticsearch \
  --set elasticsearch.enabled=true \
  --set elasticsearch.url="http://tmp-elk-svc.tmp-elk.svc.cluster.local:9200"
```
For another cluster, replace the URL with its Elasticsearch service DNS name. `elasticsearch.enabled=false` clears the configured URL from the worker environment, so the worker skips ELK processing.

### 5. External OpenTelemetry Collector Ingestion
If an OpenTelemetry Collector already receives and exports application traces, disable TraceScope's ingest edge. The chart then omits the ingest Deployment, Service, HPA, and public OTLP/ingest routes; TraceScope continues to serve the UI, queries, analytics worker, and agent telemetry.
```sh
helm install tracescope deploy/helm/tracescope \
  --set ingest.enabled=false \
  --set storage.backend=clickhouse \
  --set storage.traceBackend=elasticsearch \
  --set elasticsearch.enabled=true \
  --set elasticsearch.url="http://tmp-elk-svc.tmp-elk.svc.cluster.local:9200"
```

---

## Configuration Reference

| Parameter | Description | Default |
| :--- | :--- | :--- |
| `clickhouse.enabled` | Deploy bundled ClickHouse StatefulSet | `true` |
| `clickhouse.persistence.size` | Storage volume size for ClickHouse | `5Gi` |
| `storage.backend` | Analytics and rollup storage backend | `clickhouse` |
| `storage.traceBackend` | Backend for raw trace search and waterfall details | `elasticsearch` |
| `storage.clickhouseOnlyAgentTraces` | Retain ClickHouse strictly for agent trace data | `true` |
| `elasticsearch.enabled` | Enable Elasticsearch trace reads and worker metric aggregation | `true` |
| `elasticsearch.url` | Elasticsearch HTTP/HTTPS cluster URL | `http://tmp-elk-svc.tmp-elk.svc.cluster.local:9200` |
| `elasticsearch.index` | Elasticsearch index pattern for trace queries | `traces-apm*,apm-*,traces-*` |
| `elasticsearch.apiKey` | Elasticsearch API key for authentication | `""` |
| `elasticsearch.verifyTls` | Verify Elasticsearch TLS certificates | `true` |
| `elasticsearch.timeout` | Elasticsearch HTTP request timeout (seconds) | `10` |
| `global.image.tag` | Unified global image tag for all TraceScope workloads | `0.4.0` |
| `app.replicaCount` | Storage & Worker replicas (must remain 1) | `1` |
| `app.image.tag` | Application image tag (defaults to `global.image.tag`) | `""` |
| `ingest.replicaCount` | Initial replicas for trace ingestion | `2` |
| `ingest.enabled` | Deploy TraceScope's built-in ingest edge; set `false` when an external OpenTelemetry Collector owns ingestion | `false` |
| `ingest.image.tag` | Ingestion image tag (defaults to `global.image.tag`) | `""` |
| `ingest.autoscaling.enabled`| Enable HPA for ingestion | `true` (3–12 pods) |
| `agentStats.enabled` | Deploy dedicated agent-stats workload | `false` |
| `ui.enabled` | Deploy dedicated Nginx UI workload | `false` |
| `ingress.enabled` | Create unified Ingress | `true` |
| `ingress.serverSnippet.enabled` | Enable nginx `server-snippet` annotation (disable on hardened clusters) | `false` |
| `ingress.host` | Public Ingress hostname | `trace.n2d.id.vn` |
| `secrets.existingSecret` | Name of pre-created secret | `""` |
| `secrets.internalApiToken` | Token for edge-to-storage internal communication | Auto-configured |
