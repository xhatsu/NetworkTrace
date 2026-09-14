# TraceScope / OtelTrace on Kubernetes

The Kubernetes layout provides a lightweight, production-ready architecture using two purpose-built container images and three streamlined workloads.

| Workload | Kind | Replicas | Image | Responsibility | Storage |
|---|---|---:|---|---|---|
| `tracescope-clickhouse` | StatefulSet | 1 | `clickhouse/clickhouse-server:24.8` | High-performance analytical database | PersistentVolumeClaim (`clickhouse-data`) |
| `tracescope-app` | StatefulSet | 1 | `xhatsu101/tracescope:app-0.2.0` | `migrate` init container, `api` container (FastAPI, built-in React UI, Agent Stats on :30102), and `analytics-worker` sidecar | None (stateless app tier connected to ClickHouse) |
| `tracescope-ingest` | Deployment | 3–12 (HPA) | `xhatsu101/tracescope:ingest-0.2.0` | Decompression, parsing, credential sanitization, normalization, and OTLP ingestion on :30103 | Stateless edge pool |

## Architecture & Traffic Flow

The Ingress preserves the existing API surface exactly:

```text
                                  public Ingress
                                 /              \
                     ingest paths                all other paths
               (/api/v1/ingest, /v1/traces,        (/, /assets, /api,
               /api/v1/ingestion/status)           /api/agent/stats)
                           |                               |
                 tracescope-ingest                 tracescope-api
                    3..12 pods                         1 pod
                         \                               /
                          \                             /
                           +---------------------------+
                                         |
                               tracescope-clickhouse
                                      1 pod
                                one RWO block PVC
                                 clickhouse-data
```

## Lightweight Two-Image Strategy

Instead of managing separate repositories or heavy multi-image overhead, all components are built from a single multi-stage Dockerfile into two focused container images under a single repository with tag differentiation:

1. **`xhatsu101/tracescope:app-<version>`**
   - Contains: Backend API, built React UI distribution, analytics worker, and migration runner.
   - Used by: `tracescope-app` pod (`migrate` init, `api`, `analytics-worker`).
2. **`xhatsu101/tracescope:ingest-<version>`**
   - Contains: Lightweight, optimized OTLP & ELK ingestion receiver and deduplication engine.
   - Used by: `tracescope-ingest` Deployment (auto-scaled by HPA).

### Building and Pushing Images

Use the POSIX-compliant build script `scripts/build_and_push.sh`:

```sh
# Build and push both images:
./scripts/build_and_push.sh xhatsu101/tracescope 0.2.0

# Or build locally without pushing:
BUILD_ONLY=true ./scripts/build_and_push.sh xhatsu101/tracescope 0.2.0
```

## Configuration & Manifest Structure

- `00-namespace.yaml`: Creates the `tracescope` namespace.
- `10-configmap.yaml`: Non-sensitive configuration (ClickHouse host, log levels, batch sizes).
- `11-secret.example.yaml`: Example secret template for API credentials.
- `20-pvc.yaml`: 5Gi ReadWriteOnce persistent volume claim for ClickHouse.
- `25-clickhouse-statefulset.yaml`: ClickHouse server StatefulSet (`clickhouse/clickhouse-server:24.8`).
- `26-clickhouse-service.yaml`: Internal headless/ClusterIP service for ClickHouse (`8123`, `9000`).
- `30-storage-statefulset.yaml`: App StatefulSet (`tracescope-app`: `migrate` init, `api`, `analytics-worker`).
- `31-api-service.yaml`: ClusterIP service for API, UI, and agent stats (`30102`).
- `32-ingest-deployment.yaml`: Horizontally scalable ingest edge pool (`30103`).
- `33-ingest-service.yaml`: ClusterIP service for ingest (`30103`).
- `37-storage-service.yaml`: Internal headless service for app pods (`tracescope-app`).
- `40-ingress.yaml`: Unified ingress routing rules.
- `41-pdb.yaml`: Pod disruption budgets for high availability.
- `42-hpa.yaml`: Horizontal pod autoscaler for `tracescope-ingest` (3–12 replicas).
- `kustomization.yaml`: Kustomize composition listing all production manifests.

## Validation & Testing

Manifests and deployment topology can be validated without cluster access:

```sh
# 1. Validate manifest syntax, schemas, PVC ownership, and references:
python3 deploy/k8s/validate_manifests.py deploy/k8s

# 2. Run deployment topology and role isolation unit tests:
.venv/bin/pytest tests/test_deployment_topology.py

# 3. Lint the accompanying Helm chart:
helm lint deploy/helm/tracescope
```
