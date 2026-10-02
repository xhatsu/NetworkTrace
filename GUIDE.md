# TraceScope & OBI Stack Deployment & Generator Guide

This guide documents how to use the unified generator script (`deploy/helm/render-stack.sh`), explains all configuration parameters, and provides step-by-step instructions to set up, configure, and operate the TraceScope observability and behavioral analytics stack.

---

## 1. Architecture & Port Layout

The platform consists of two coordinated Helm charts deployed into Kubernetes (default namespace: `tracescope`):

1. **`tracescope`**:
   - `tracescope-app`: FastAPI analytical server and background behavioral analytics worker.
   - `tracescope-clickhouse`: Primary datastore for high-throughput traces, rollups, and topological state.
   - `tracescope-ingest`: Coalescing OTLP HTTP receiver (`/v1/traces`) with bulk ClickHouse insertion.
2. **`tracescope-obi`**:
   - `tracescope-obi`: Privileged eBPF daemonset (captures L7 kernel-level HTTP, JSON, XML/SOAP).
   - `tracescope-obi-collector`: OpenTelemetry Collector that processes, redacts, batches, and exports spans to `tracescope-ingest`.

### Port Allocations

| Port | Service / Component | Protocol / Interface | Purpose |
| :--- | :--- | :--- | :--- |
| **`30102`** | `tracescope-api` | NodePort / HTTP | Cluster UI and REST API. Also routed via Ingress (`https://trace.n2d.id.vn`). |
| **`30103`** | `tracescope-ingest` | NodePort / HTTP | High-throughput OTLP trace ingestion endpoint (`/v1/traces`). |
| **`30105`** | `nt-bootstrap` | HTTP (`127.0.0.1` / host) | Host bootstrap agent server (`bootstrap/start.sh`). |
| **`31102`** | `tracescope-local` | Local host dev (`0.0.0.0`) | Local FastAPI development instance (`./run_server.sh`). Runs concurrently with cluster NodePort `30102` without conflict. |

---

## 2. Generator Script (`deploy/helm/render-stack.sh`)

`deploy/helm/render-stack.sh` generates synchronized Helm values (`tracescope-values.yaml`, `tracescope-obi-values.yaml`) and optionally renders declarative Kubernetes YAMLs (`tracescope.yaml`, `tracescope-obi.yaml`).

### Command Syntax

```bash
./deploy/helm/render-stack.sh --mode <elk|clickhouse> [OPTIONS]
```

### Parameter Reference

| Parameter | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `--mode MODE` | **Yes** | — | `clickhouse`: OBI -> Collector -> TraceScope Ingest -> ClickHouse.<br>`elk`: OBI -> Collector -> APM Server -> Elasticsearch -> Worker sync. |
| `--obi VARIANT` | No | `standard` | `standard`: Upstream OpenTelemetry eBPF (`otel/ebpf-instrument:v0.13.0`, JSON/headers).<br>`custom`: Custom image (`xhatsu101/ebpf-instrument:xmlCustom-0.13.0`) capturing XML/SOAP payloads (WSSE authentication). |
| `--body on\|off` | No | `on` | Enables or disables payload body capture in eBPF. (If `off`, XML/JSON body inspection is omitted). |
| `--target NS[/GLOB]` | No | `default` | Target Kubernetes namespace and optional deployment glob to instrument (e.g. `--target default`, `--target prod/checkout-*`). Can be repeated multiple times. |
| `--exclude NS` | No | — | Namespace to exclude from eBPF instrumentation (e.g. `--exclude kube-system`, `--exclude tracescope`). Can be repeated. |
| `-n, --namespace NS` | No | `tracescope` | Unified namespace for both TraceScope and OBI (shorthand setting both `--ts-namespace` and `--obi-namespace`). |
| `--ts-release NAME` | No | `tracescope` | Helm release name for TraceScope app. |
| `--ts-namespace NS` | No | `tracescope` | Kubernetes namespace for TraceScope resources. |
| `--obi-release NAME` | No | `<ts-release>-obi` | Helm release name for the OBI stack (default: `tracescope-obi`). |
| `--obi-namespace NS` | No | `tracescope` | Kubernetes namespace for OBI resources (deployed into the same namespace as the app). |
| `--out DIR` | No | `./stack-out` | Target directory where generated values and rendered manifests will be written. |
| `--nodeport` | No | *(disabled)* | Disables Ingress and configures `tracescope-api` on NodePort `30102` and `tracescope-ingest` on NodePort `30103`. |
| `--render` | No | *(disabled)* | Runs `helm template` using generated values to produce `tracescope.yaml`, `tracescope-obi.yaml`, and the combined `tracescope-all.yaml`. |
| `--single-yaml [FILE]` | No | *(disabled)* | Bundles both charts into one single YAML file (default: `<out>/tracescope-all.yaml`; implies `--render`). Alias: `--all-in-one`. |
| `--tag TAG` | No | `0.4.6` | Custom image tag for TraceScope workloads (e.g. `0.4.6-amd64` to force AMD64). |
| `--pull-policy POLICY` | No | `IfNotPresent` | Image pull policy (e.g. `Always` to force re-pull and avoid stale local arch cache). |
| `--no-pvc` | No | *(disabled)* | Runs ClickHouse as an ephemeral pod using `emptyDir` (omits PVC; ideal for test clusters). |
| `--no-collector` | No | *(disabled)* | Disables the OpenTelemetry Collector deployment/service; deploys only the OBI eBPF DaemonSet agent. |
| `--export-endpoint URL` | No | — | OTLP destination endpoint for OBI traces (required when `--no-collector` is used). |
| `--no-cluster-rbac` | No | *(disabled)* | Uses namespace-scoped `Role` & `RoleBinding` instead of `ClusterRole` (for environments blocking cluster-wide RBAC). |
| `--no-rbac` | No | *(disabled)* | Omits all Role/ClusterRole resources and disables K8s metadata lookup. |
| `--apm-endpoint H:P` | No | `apm-server.tmp-elk.svc...:8200` | Elastic APM OTLP endpoint (only used when `--mode elk`). |
| `--es-url URL` | No | `http://tmp-elk-svc...:9200` | Elasticsearch base URL for worker queries (only used when `--mode elk`). |

---

## 3. How to Generate and Deploy

### Recommended Production Command (ClickHouse + Custom XML OBI + Single YAML)

To instrument the `default` namespace while setting a custom namespace (e.g. `tracescope` or `my-observability`) and bundling everything into a single YAML file:

```bash
./deploy/helm/render-stack.sh \
  --mode clickhouse \
  --obi custom \
  --body on \
  --target default \
  --exclude kube-system \
  -n tracescope \
  --single-yaml \
  --out ./stack-out
```

### Applying the Single Combined Manifest (`tracescope-all.yaml`)

> [!TIP]
> Every namespaced resource in the generated YAML explicitly includes `metadata.namespace: <namespace>`. You can apply the entire stack with a single command:

```bash
# 1. Ensure the namespace exists
kubectl create namespace tracescope --dry-run=client -o yaml | kubectl apply -f -

# 2. Apply all resources (ClickHouse, Ingest, App, OBI, Collector) from the single YAML:
kubectl apply -f ./stack-out/tracescope-all.yaml
```

### Applying Individual Manifests (Optional)

```bash
# Core TraceScope stack (ClickHouse, Ingest, App)
kubectl apply -f ./stack-out/tracescope.yaml

# OBI eBPF and Collector stack
kubectl apply -f ./stack-out/tracescope-obi.yaml
```

### Alternative: Deploying via Helm CLI

If managing installations directly with the Helm release manager:

```bash
# Install / Upgrade TraceScope app
helm upgrade --install tracescope deploy/helm/tracescope -n tracescope \
  -f deploy/helm/tracescope/values-secrets.yaml \
  -f ./stack-out/tracescope-values.yaml

# Install / Upgrade TraceScope OBI
helm upgrade --install tracescope-obi deploy/helm/tracescope-obi -n tracescope \
  -f ./stack-out/tracescope-obi-values.yaml
```

---

## 4. Operational Configuration Details

### Behavior Learning Always-On
Behavior learning is configured via `behavior.enabled: true` in `deploy/helm/tracescope/values.yaml` and is automatically propagated by `render-stack.sh`. This ensures `OTEL_BEHAVIOR_LEARNING_ENABLED: "true"` is rendered into `tracescope-config`. The background worker will continuously build profile baselines, detect credential anomalies, and generate topology entities.

### Concurrent Local Dev Server
To run a local copy of TraceScope on the host alongside the in-cluster NodePort `30102`:
- The local app runs on port **`31102`** (configured via `OTEL_PORT=31102` in `.env` and `run_server.sh`).
- Local worker is disabled (`OTEL_HOST_WORKER_ENABLED=false`) so the cluster worker in `tracescope-app-0` exclusively handles rollups and migrations.
- Manage local host instances with:
  ```bash
  ./run_server.sh start    # Starts uvicorn in tmux session tracescope-31102
  ./run_server.sh status   # Checks active sessions and ports
  ./run_server.sh stop     # Stops local dev instance
  ```

### Environments Blocking ClusterRole / ClusterRoleBinding
If your Kubernetes account or security policy forbids creating cluster-wide RBAC:
1. **Automated Flag**: Run `render-stack.sh` with `--no-cluster-rbac`. This automatically changes `ClusterRole` and `ClusterRoleBinding` into a namespace-scoped `Role` and `RoleBinding` targeting your namespace:
   ```bash
   ./deploy/helm/render-stack.sh --mode clickhouse -n <your-ns> --no-cluster-rbac --single-yaml
   ```
2. **Omit All RBAC**: If even namespace `Role` creation is blocked, use `--no-rbac`:
   ```bash
   ./deploy/helm/render-stack.sh --mode clickhouse -n <your-ns> --no-rbac --single-yaml
   ```

### Running ClickHouse Without PVC (Ephemeral / Test Clusters)
If your test cluster lacks dynamic volume provisioning (StorageClass) or you want a temporary deployment:
1. **Automated Flag**: Run `render-stack.sh` with `--no-pvc`. This automatically configures `emptyDir: {}` for ClickHouse and omits the `PersistentVolumeClaim`:
   ```bash
   ./deploy/helm/render-stack.sh --mode clickhouse -n <your-ns> --no-pvc --single-yaml
   ```
2. **Manual YAML Edit**:
   - Delete the `kind: PersistentVolumeClaim` document named `tracescope-clickhouse-data`.
   - In the `tracescope-clickhouse` StatefulSet, change `volumes.data`:
     ```yaml
     volumes:
       - name: data
         emptyDir: {}
     ```

### Deploying OBI Agent Only (Without OTel Collector)
If your cluster already has an existing OpenTelemetry Collector or you only wish to deploy the eBPF auto-instrumentation DaemonSet without the built-in collector deployment/service:

1. **Required Kubernetes Resources to Apply:**
   - `ServiceAccount`: `tracescope-obi`
   - `ClusterRole` & `ClusterRoleBinding`: `tracescope-obi` (or namespace `Role` & `RoleBinding`)
   - `ConfigMap`: `tracescope-obi` (contains `obi.yml`)
   - `DaemonSet`: `tracescope-obi`
   *(Do NOT apply `tracescope-obi-collector` Deployment, Service, or ConfigMap)*

2. **Crucial Setting (`otel_traces_export.endpoint`):**
   Because the built-in collector is omitted, you MUST specify the destination OTLP endpoint in `obi.yml` or Helm values, for example `http://my-existing-collector.monitoring.svc.cluster.local:4317`.

3. **Using the Generator Script (`render-stack.sh`):**
   ```bash
   ./deploy/helm/render-stack.sh --mode clickhouse \
     --no-collector \
     --export-endpoint "http://my-collector.monitoring.svc.cluster.local:4317" \
     -n tracescope --render
   ```
   This generates `stack-out/tracescope-obi.yaml` containing exclusively the OBI DaemonSet and RBAC resources.

4. **Using Helm CLI:**
   ```bash
   helm upgrade --install tracescope-obi deploy/helm/tracescope-obi -n tracescope \
     --set collector.enabled=false \
     --set obi.export.endpoint="http://my-collector.monitoring.svc.cluster.local:4317"
   ```

5. **Generating Standalone Manifest with `helm template`:**
   ```bash
   helm template tracescope-obi deploy/helm/tracescope-obi -n tracescope \
     --set collector.enabled=false \
     --set obi.export.endpoint="http://my-collector.monitoring.svc.cluster.local:4317" \
     > obi-agent-only.yaml
   ```


---

## 5. Verification & Health Checks

After deployment, verify that data flows through each stage of the pipeline:

### 1. Check Pod Status
```bash
kubectl get pods,svc -n tracescope
```
*Expected: `tracescope-app-0` (2/2), `tracescope-clickhouse-0` (1/1), `tracescope-ingest` (1/1), `tracescope-obi-collector` (1/1), and `tracescope-obi` daemonset (1/1 per node).*

### 2. Check Ingestion Logs
```bash
kubectl logs -n tracescope -l app.kubernetes.io/component=ingest --tail=20
```
*Expected: Continuous records of `POST /v1/traces HTTP/1.1 200 OK` from the collector.*

### 3. Check ClickHouse Ingestion Lag
```bash
curl -s 'http://10.108.134.22:8123/?query=SELECT+count(),+max(timestamp),+toUnixTimestamp(now())+-+max(timestamp)+AS+lag_sec+FROM+tracescope.traces+FORMAT+Vertical'
```
*Expected: `lag_sec` <= 10 seconds and trace counts actively incrementing.*

### 4. Check Behavior Analytics & API
```bash
# Health endpoint
curl -s http://127.0.0.1:30102/api/v1/health | jq .

# Behavior learning status
curl -s http://127.0.0.1:30102/api/v1/behavior/overview | jq '{mode: .mode, enabled: .enabled, profiles: .profiles}'

# Service Topology
curl -s http://127.0.0.1:30102/api/v1/topology | jq '{nodes: (.nodes | length), edges: (.edges | length)}'
```

---

## 6. Critical Operational Gotchas

1. **ClickHouse Persistent Volume Protection:**
   The ClickHouse PV must have `persistentVolumeReclaimPolicy: Retain` so that reinstalling Helm releases or deleting StatefulSets will never erase stored analytical history.
2. **CPU Scheduling Deadlock during Rollout:**
   On constrained 2-CPU nodes, rolling out a chart update while ingest pods are surging can cause ClickHouse to become `Pending` (`Insufficient cpu`). If this happens, scale ingest to 0 (`kubectl scale deploy/tracescope-ingest --replicas=0 -n tracescope`), wait for ClickHouse to become `Ready`, then scale ingest back to 1.
3. **Namespace Isolation:**
   When running `kubectl apply -f ./stack-out/tracescope.yaml`, always append `-n <namespace>`.
4. **InitContainer `migrate` Fails with `exec format error` (Architecture Cache Collision):**
   If the container exits with `exec format error`, an `x86_64 / amd64` node ran a previously cached ARM64 image because the default `imagePullPolicy` was `IfNotPresent`.
   - **Fix via Generator:** Re-render with `--tag 0.4.6-amd64 --pull-policy Always`:
     ```bash
     ./deploy/helm/render-stack.sh --mode clickhouse -n <your-ns> --tag 0.4.6-amd64 --pull-policy Always --single-yaml --out ./stack-out
     ```
   - **Fix via Manual YAML Edit:** In `tracescope-all.yaml`, set `image: "xhatsu101/tracescope:0.4.6-amd64"` and `imagePullPolicy: Always` under `tracescope-app`, then delete the pod:
     ```bash
     kubectl delete pod tracescope-app-0 -n <your-ns>
     ```
