# TraceScope Helm Chart

Production-ready Helm chart for deploying the TraceScope Behavioral Observability & OTel Transaction Analytics Platform on Kubernetes.

## Architecture & Workloads

TraceScope consists of the following components:
1. **ClickHouse (`clickhouse`)**: Columnar analytics database (StatefulSet).
2. **Storage & Analytics Core (`storage`)**: StatefulSet with single-writer lock domain:
   - Init container: runs database schema migrations once.
   - `api`: FastAPI serving analytics queries, topology, and internal writes.
   - `analytics-worker`: Background worker running rollups, baselines, and anomaly detectors.
3. **Ingest Edge (`ingest`)**: Stateless Deployment (with HPA 3–12 pods) handling OTEL/ELK trace batches, decompression, WSSE/Basic auth sanitization, and transaction-atomic deduplication.
4. **Agent Stats (`agentStats`)**: Stateless Deployment (with HPA 2–6 pods) receiving oldkernel/eBPF agent heartbeat samples.
5. **UI Frontend (`ui`)**: Stateless Nginx Deployment serving the compiled React 19 SPA.
6. **Ingress**: Unified reverse proxy keeping all public endpoints identical to the host deployment.

---

## Deployment Modes & Merging Workloads

### 1. Full Distributed Mode (Default - High Scale)
Independent workloads for every tier. Best for high-throughput production estates:
```sh
helm install tracescope deploy/helm/tracescope
```

### 2. Balanced Mode (Merge UI + Merge Agent Stats)
Saves 4+ pods by:
- Merging UI into the Storage API pod (`ui.enabled: false`)
- Merging Agent Stats into the Ingest pods (`agentStats.enabled: false`)
```sh
helm install tracescope deploy/helm/tracescope \
  --set ui.enabled=false \
  --set agentStats.enabled=false
```

### 3. External ClickHouse Mode
Use an existing production ClickHouse cluster:
```sh
helm install tracescope deploy/helm/tracescope \
  --set clickhouse.enabled=false \
  --set clickhouse.host="clickhouse.prod.internal" \
  --set clickhouse.password="secret"
```

---

## Configuration Reference

| Parameter | Description | Default |
| :--- | :--- | :--- |
| `clickhouse.enabled` | Deploy bundled ClickHouse StatefulSet | `true` |
| `clickhouse.persistence.size` | Storage volume size for ClickHouse | `50Gi` |
| `storage.replicaCount` | Storage & Worker replicas (must remain 1) | `1` |
| `ingest.replicaCount` | Initial replicas for trace ingestion | `3` |
| `ingest.autoscaling.enabled`| Enable HPA for ingestion | `true` (3–12 pods) |
| `agentStats.enabled` | Deploy dedicated agent-stats workload | `true` |
| `ui.enabled` | Deploy dedicated Nginx UI workload | `true` |
| `ingress.enabled` | Create unified Ingress | `true` |
| `ingress.host` | Public Ingress hostname | `tracescope.local` |
| `secrets.existingSecret` | Name of pre-created secret | `""` |
| `secrets.internalApiToken` | Token for edge-to-storage internal communication | Auto-configured |

