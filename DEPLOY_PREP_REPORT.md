# TraceScope 0.2.1 Deployment Preparation Report

Date: 2026-09-14 UTC

Scope: build and push the two TraceScope images, change only the four Helm image tag values, validate the chart with default values, and report findings. No rollout or cluster mutation was performed.

## 1. Build and push result

Command executed exactly, without `--platform`:

```text
sh scripts/build_and_push.sh xhatsu101/tracescope 0.2.1
```

Host and resulting local images:

```text
aarch64
[xhatsu101/tracescope:app-0.2.1] architecture=arm64 image_id=sha256:6e67a6d6962ba43298b394205604284de706666a441939b8db1edeb3e0ebd87a
[xhatsu101/tracescope:ingest-0.2.1] architecture=arm64 image_id=sha256:a6e67da94dfdc56ee8d774d9ec305c5aac4d3cd3d2b5c3511f28f8e5f6e99f54
```

Both builds and both Docker Hub pushes succeeded. Docker reported 5.2 seconds for the app build and 1.2 seconds for the ingest build; total build-script wall time, including pushes, was 29.87 seconds.

Verbatim successful push/build tail:

```text
app-0.2.1: digest: sha256:7f30068a3408093020accadbfcaa28f54fa4e79da1472b4c68e6e30c924a7275 size: 2622

==> Pushing Ingest Image: xhatsu101/tracescope:ingest-0.2.1...
The push refers to repository [docker.io/xhatsu101/tracescope]
ingest-0.2.1: digest: sha256:f23833bf512af1d1558f0faa6fb44214ed4ce3e6736048b0183a0518fdf55fda size: 2412

=================================================================
 Successfully built and pushed 2 TraceScope images!
   1. Main App: xhatsu101/tracescope:app-0.2.1
   2. Ingest:   xhatsu101/tracescope:ingest-0.2.1
=================================================================
real 29.87
user 0.29
sys 0.30
```

The same Dockerfile warning appeared once for each image:

```text
1 warning found (use docker --debug to expand):
 - SecretsUsedInArgOrEnv: Do not use ARG or ENV instructions for sensitive data (ENV "OTEL_CLICKHOUSE_PASSWORD") (line 44)
```

## 2. Helm values edit confirmation

Only these four value lines were changed by this task:

```text
app.image.tag:        app-0.2.0    -> app-0.2.1
ingest.image.tag:     ingest-0.2.0 -> ingest-0.2.1
agentStats.image.tag: app-0.2.0    -> app-0.2.1
ui.image.tag:         app-0.2.0    -> app-0.2.1
```

Resulting lines:

```yaml
app:
  image:
    tag: app-0.2.1
ingest:
  image:
    tag: ingest-0.2.1
agentStats:
  image:
    tag: app-0.2.1
ui:
  image:
    tag: app-0.2.1
```

No Chart metadata, secret, environment variable, Dockerfile, or other values were changed.

## 3. Helm validation with default values

### `helm lint deploy/helm/tracescope`

Exit status: `0`

Verbatim output:

```text
level=WARN msg="missing required values" message="secrets.internalApiToken is required when secrets.existingSecret is empty"
level=INFO msg="funcMap fail" message="secrets.internalApiToken must be a non-placeholder value of at least 32 characters"
==> Linting deploy/helm/tracescope

1 chart(s) linted, 0 chart(s) failed
```

### `helm template deploy/helm/tracescope`

Exit status: `1`

Verbatim output:

```text
Error: execution error at (tracescope/templates/secret.yaml:2:14): secrets.internalApiToken is required when secrets.existingSecret is empty

Use --debug flag to render out invalid YAML
```

Conclusion: default rendering is blocked. Helm 4.3.0 reports the problem during lint but still returns success, so a green lint result alone is not sufficient; `helm template` is the effective blocking check.

## 4. Severity-ranked findings

### Blocker — no internal API token in default values

Evidence: `secrets.existingSecret` and `secrets.internalApiToken` are both empty. `templates/secret.yaml` requires a non-placeholder token of at least 32 characters. The verbatim template failure above confirms that an upgrade using defaults cannot render.

Recommended but not applied: provision a Kubernetes Secret containing `OTEL_INTERNAL_API_TOKEN` and select it through `secrets.existingSecret`, or supply a cryptographically random token of at least 32 characters through a protected values mechanism. Do not store the token in Git or expose it in shell history.

### Should-fix-before-rollout — public mutation/ingestion authentication is disabled

Evidence: `secrets.apiKey: ""` becomes `OTEL_API_KEY=""`. In `backend/app/application.py`, mutation authentication is enforced only when `settings.api_key` is truthy:

```python
if expected and (supplied is None or not hmac.compare_digest(supplied, expected)):
```

Therefore an empty value leaves public POST/PATCH/DELETE routes, including ingestion, without API-key enforcement. This agrees with the prior live verification cited by the task.

Recommended but not applied: set a strong, non-empty `OTEL_API_KEY`, distribute it to authorized shippers, and verify unauthenticated writes return HTTP 401 before opening traffic.

### Should-fix-before-rollout — images were built from an already-dirty worktree

Evidence: before the build, `git status --short` showed extensive modified, deleted, staged, and untracked files across backend, frontend, Docker, chart, migrations, tests, and documentation. The Docker build context therefore represents that local filesystem state rather than a clean, immutable commit.

Recommended but not applied: before a production rollout, reproduce the build from a reviewed clean commit, record its commit SHA and source-tree digest, and publish image provenance/SBOM. The images pushed by this task are real, but their contents should be treated as tied to this workspace snapshot.

### Should-fix-before-rollout — ClickHouse has limited memory headroom

Evidence: `clickhouse.resources.limits.memory` is `2Gi`. The known effective ClickHouse cap is about 1.8 GiB. Backend defaults bound an aggregation query to 1 GiB and external group-by spill begins at 256 MiB, but ClickHouse still needs memory for merges, concurrent queries, caches, inserts, and process overhead.

Recommended but not applied: validate production concurrency under representative ingest plus analytics load and raise the ClickHouse pod memory limit (the prior operational recommendation was at least 4 GiB) with corresponding ClickHouse memory settings and alerts.

### Should-fix-before-rollout — Helm configuration lags backend resource controls

Evidence: all of the following are read in `backend/config.py`, but none appears in the chart ConfigMaps or values:

```text
OTEL_INGEST_MAX_BATCH_BYTES                         default 33554432
OTEL_AGGREGATION_MAX_MEMORY_USAGE                  default 1073741824
OTEL_AGGREGATION_EXTERNAL_GROUP_BY_BYTES           default 268435456
OTEL_AGGREGATION_SHADOW_ENABLED                    default true
OTEL_AGGREGATION_CUTOVER                           default false
OTEL_BASELINE_CADENCE_SECONDS                      default 300
OTEL_BASELINE_SERIES_BUDGET                        default 100
OTEL_ANOMALY_WINDOW_BUDGET                         default 100
OTEL_ANALYTICS_STAGE_BUDGET_SECONDS                default 55
```

The deployment will silently use code defaults, so operators cannot express or audit these controls through the chart.

Recommended but not applied: add typed values with documented defaults and map them into the appropriate app/worker/ingest ConfigMaps after workload testing.

### Should-fix-before-rollout — retention value does not implement live-table TTL intent

Evidence: the chart emits `OTEL_RETENTION_DAYS=30`, but the active `backend.worker` does not reference `settings.retention_days`. Migration 003 explicitly leaves live TTL changes commented out:

```sql
-- ALTER TABLE traces MODIFY TTL toDateTime(intDiv(timestamp_ms, 1000)) + INTERVAL 30 DAY DELETE;
-- ALTER TABLE metric_buckets MODIFY TTL toDateTime(bucket_start) + INTERVAL 90 DAY DELETE;
```

Only the shadow `metric_buckets_agg` table receives a 90-day TTL in migration 003. Migration 002 adds a one-day TTL to `agent_stats_history`, and the original schema has a seven-day TTL for ingest-batch records. A legacy `backend.analytics.run_jobs()` path contains application-level deletion logic, but it deletes from the legacy `events` table and is not the active `backend.worker` cycle.

Recommended but not applied: decide and test live-table retention, then apply explicit ClickHouse TTL migrations for `traces` and `metric_buckets` (or add a bounded, observable cleanup job). Align the chart value and schema documentation with the actual mechanism.

### Should-fix-before-rollout — chart and application version metadata remain 0.2.0

Evidence:

```yaml
version: 0.2.0
appVersion: "0.2.0"
```

In addition, `backend/app/application.py` still constructs FastAPI with `version="0.2.0"`. The deployed images would be tagged 0.2.1 while chart and API metadata report 0.2.0.

Recommended but not applied: in a separate authorized release change, bump chart package metadata and the application-reported version consistently, then package/review the chart.

### Should-fix-before-enabling standalone UI — UI values point at the API image

Evidence: `ui.enabled` is false by default, so this does not affect the requested default topology. If enabled, however, `ui.image.tag` points to `app-0.2.1`. That image's default command runs Uvicorn on port 8000 as UID 10001, while `ui-deployment.yaml` does not override the command and expects nginx on container port 80 under UID 101. The build script publishes only `api` and `ingest`, even though the Dockerfile has a separate `ui` target.

Recommended but not applied: before setting `ui.enabled=true`, build/publish the Dockerfile `ui` target under a distinct immutable image tag and point `ui.image` to it. Keep the current consolidated UI mode until that is done.

### Note — production hostname is absent from the CORS allowlist, but same-origin SPA use is not broken

Evidence: the chart configures:

```text
OTEL_CORS_ORIGINS=http://localhost:30102,http://tracescope.local
```

`backend/app/application.py` passes this list to FastAPI `CORSMiddleware`. The production SPA and API are both served through `https://trace.n2d.id.vn`; same-origin browser calls do not require an `Access-Control-Allow-Origin` response and therefore are not broken by the omission. Browser clients hosted on a different origin are affected and will not receive CORS authorization, even if the API hostname is `trace.n2d.id.vn`.

Recommended but not applied: add the exact production origin if supported cross-origin browser access is intended; otherwise document that only same-origin browser access is supported and keep the list narrow.

### Note — migration 003 will auto-apply through the init container

Evidence: `app.migrations.enabled` is true. `storage-statefulset.yaml` defines a `migrate` init container using the new app image and runs:

```text
python -m backend.cli migrate
```

The image copies the complete `backend/` directory, including `backend/clickhouse_migrations/003_aggregate_states_shadow.sql`. `clickhouse_migrator.py` sorts all `*.sql` files and applies those absent from `schema_migrations`, then records the filename. Consequently migration 003 will run before the API and worker containers start, provided it has not already been recorded and ClickHouse is reachable.

The repository-root `docker-entrypoint.sh` also invokes migrations, but `deploy/docker/Dockerfile` neither copies nor declares that file as an entrypoint. It is not the operative path for these two images; the Helm init container is.

Recommended but not applied: during rollout, inspect the init-container result and `schema_migrations` ledger before declaring the app ready.

### Note — Dockerfile declares an empty password environment variable

Evidence: Docker emitted `SecretsUsedInArgOrEnv` for `ENV OTEL_CLICKHOUSE_PASSWORD=""` in both builds. No actual password was embedded—the value is empty—and the chart supplies runtime secret data, but the declaration triggers the build security check and encourages secret-shaped ENV metadata in an image layer.

Recommended but not applied: remove the password declaration from the Dockerfile and rely only on runtime secret injection; retain a safe code-level empty default if required.

### Note — versioned tags use `IfNotPresent`, but tags remain mutable

Evidence: all four application image sections use `pullPolicy: IfNotPresent`. The new `0.2.1` tags are fresh, so nodes without them will pull them. If either Docker Hub tag is later overwritten, a node with a cached image may run different content from a new node.

Recommended but not applied: never overwrite release tags and preferably deploy digest-pinned image references or add chart support for digests.

## 5. Operator rollout runbook — not executed

All steps in this section are deliberately left to the operator. Replace bracketed placeholders; do not use literal placeholders as credentials.

1. Resolve the blocker and API authentication. Preferred approach: create a pre-existing Secret named, for example, `tracescope-secrets` in the target namespace with keys `OTEL_INTERNAL_API_TOKEN` (cryptographically random, at least 32 characters), `OTEL_API_KEY` (strong and non-empty), `OTEL_CLICKHOUSE_PASSWORD`, and `CLICKHOUSE_PASSWORD`. Then use:

   ```text
   --set-string secrets.existingSecret=tracescope-secrets
   ```

   If the operator intentionally lets Helm generate the Secret, the required value shape is:

   ```text
   --set-string secrets.internalApiToken='<RANDOM_NON_PLACEHOLDER_VALUE_AT_LEAST_32_CHARACTERS>' \
   --set-string secrets.apiKey='<STRONG_NON_EMPTY_INGEST_API_KEY>'
   ```

   A protected values file or existing Secret is preferred because command-line values can leak through shell history/process inspection and Helm release storage.

2. Re-run preflight rendering with the selected secret method. Existing-Secret example:

   ```sh
   helm lint deploy/helm/tracescope \
     --set-string secrets.existingSecret=tracescope-secrets

   helm template tracescope deploy/helm/tracescope \
     --namespace tracescope \
     --set-string secrets.existingSecret=tracescope-secrets \
     > /tmp/tracescope-0.2.1-rendered.yaml
   ```

3. Confirm the two remote digests against the build evidence and confirm the target cluster nodes are `arm64`. Review the full rendered diff, especially image names, ingress, Secret references, resources, probes, init container, HPA, PDB, PVC, and ClickHouse configuration.

4. Address or explicitly accept the should-fix findings above. In particular, do not enable standalone UI with the current `app-0.2.1` image reference.

5. Roll out only after approval. Command shape using an existing Secret:

   ```sh
   helm upgrade --install tracescope deploy/helm/tracescope \
     --namespace tracescope \
     --create-namespace \
     --set-string secrets.existingSecret=tracescope-secrets \
     --wait \
     --timeout 15m
   ```

   Helm-generated Secret alternative:

   ```sh
   helm upgrade --install tracescope deploy/helm/tracescope \
     --namespace tracescope \
     --create-namespace \
     --set-string secrets.internalApiToken="$TRACESCOPE_INTERNAL_API_TOKEN" \
     --set-string secrets.apiKey="$TRACESCOPE_API_KEY" \
     --wait \
     --timeout 15m
   ```

6. Verify migration and rollout state:

   ```sh
   helm status tracescope --namespace tracescope
   kubectl --namespace tracescope get pods -o wide
   kubectl --namespace tracescope logs tracescope-app-0 -c migrate
   kubectl --namespace tracescope rollout status statefulset/tracescope-app --timeout=10m
   kubectl --namespace tracescope rollout status deployment/tracescope-ingest --timeout=10m
   ```

   Confirm `003_aggregate_states_shadow.sql` is present in the ClickHouse `schema_migrations` ledger and `metric_buckets_agg` exists with its 90-day TTL.

7. Verify the deployed image IDs/digests and application health:

   ```sh
   kubectl --namespace tracescope get pods \
     -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.name}{"="}{.imageID}{" "}{end}{"\n"}{end}'
   curl -fsS https://trace.n2d.id.vn/livez
   curl -fsS https://trace.n2d.id.vn/readyz
   curl -fsS https://trace.n2d.id.vn/api/v1/health
   curl -fsS https://trace.n2d.id.vn/api/v1/ingestion/status
   ```

8. Verify security behavior: an unauthenticated mutation must return HTTP 401; an authorized, uniquely identified canary batch must be accepted once and deduplicated on replay. Confirm the canary in API/ClickHouse evidence without exposing either token in logs.

9. Observe at least one analytics cycle. Check API, ingest, worker, init-container, and ClickHouse logs; ingestion queue/commit/failure counters; HPA state; ClickHouse memory, spill, merge, and OOM metrics; and the shadow aggregation output. Keep the prior release values and image digests available for rollback.

10. If rollback is required, use the reviewed prior Helm revision rather than retagging images:

    ```sh
    helm history tracescope --namespace tracescope
    helm rollback tracescope <PRIOR_REVISION> --namespace tracescope --wait --timeout 15m
    ```

## 6. Explicit non-actions

- No `helm upgrade`, install, rollback, or other cluster interaction was performed.
- No `kubectl` command was executed.
- No token, API key, password, or placeholder credential was added.
- `Chart.yaml`, backend environment mappings, migrations, Dockerfiles, and entrypoints were not changed.
- No Git commit, add, stash, checkout, reset, or other index/history mutation was performed.
