# TASK: Fix the deployment-prep findings and produce a rollout-ready chart

Read FIRST, in order: `DEPLOY_PREP_REPORT.md` (the findings you are fixing), `DEPLOY_PREP_TASK.md` (context), `deploy/helm/tracescope/values.yaml`, `deploy/helm/tracescope/templates/secret.yaml`, `Chart.yaml`, `deploy/docker/Dockerfile`.

The operator has AUTHORIZED you to: modify helm manifest values and templates as needed, generate random secrets (openssl rand or /dev/urandom), modify `Chart.yaml`, `backend/app/application.py` version string, `Dockerfile`, and add a migration file. You are still FORBIDDEN from: any cluster interaction (no helm upgrade/install/rollback, no kubectl), git commit/add/stash, and running the full pytest-less repo build more than once.

## Fixes to apply (from DEPLOY_PREP_REPORT.md severity list)

1. **Blocker — internal API token**: generate a cryptographically random token (≥48 chars, openssl rand -base64 48 | tr -d '\n'), write it into `values.yaml` `secrets.internalApiToken`. OPERATOR AUTHORIZATION for embedding in values.yaml is granted explicitly this time. NEVER print the full value in your report, logs, or stdout — reference it as `internalApiToken=<first4>…(<len> chars)`.
2. **High — ingest auth off**: generate a second independent strong random key (≥48 chars) into `secrets.apiKey`. Same redaction rule.
3. **Version consistency**: bump `Chart.yaml` `version:` and `appVersion:` 0.2.0 → **0.2.2** (NOT 0.2.1 — those image tags already exist on Docker Hub from the prep run and must never be overwritten; 0.2.2 becomes the rollout tag). Update `backend/app/application.py` FastAPI `version=` to "0.2.2". Rebuild + push images via the build script: `sh scripts/build_and_push.sh xhatsu101/tracescope 0.2.2` and update the FOUR tag lines in values.yaml (app, ingest, agentStats, ui) to `*-0.2.2`. Record new digests.
4. **ClickHouse memory**: `clickhouse.resources.limits.memory: 2Gi` → `4Gi` (requests 1Gi → 2Gi).
5. **Chart lags backend env knobs**: add typed, commented entries under `values.yaml` `config:` for all nine: `OTEL_INGEST_MAX_BATCH_BYTES` (33554432), `OTEL_AGGREGATION_MAX_MEMORY_USAGE` (1073741824), `OTEL_AGGREGATION_EXTERNAL_GROUP_BY_BYTES` (268435456), `OTEL_AGGREGATION_SHADOW_ENABLED` ("true"), `OTEL_AGGREGATION_CUTOVER` ("false"), `OTEL_BASELINE_CADENCE_SECONDS` (300), `OTEL_BASELINE_SERIES_BUDGET` (100), `OTEL_ANOMALY_WINDOW_BUDGET` (100), `OTEL_ANALYTICS_STAGE_BUDGET_SECONDS` (55) — and map them into the ConfigMap(s)/env that reach the app + worker + ingest pods (check which templates build those env blocks; values keys like `config.ingestMaxBatchBytes` etc. — pick clean names, keep defaults identical to backend code defaults).
6. **Retention mismatch**: create `backend/clickhouse_migrations/004_live_table_retention.sql` applying the commented-out live TTLs from 003: `traces` 30-day TTL on `toDateTime(intDiv(timestamp_ms,1000))`, `metric_buckets` 90-day TTL on `toDateTime(bucket_start)` (ALTER ... MODIFY TTL ... DELETE; guard idempotently per the migrator's filename-ledger behavior — a plain migration file applied once is fine). This aligns chart `config.retentionDays: 30` intent with schema reality; document that bucket TTL is fixed 90d.
7. **CORS**: add `https://trace.n2d.id.vn` to `config.corsOrigins` in values.yaml.
8. **Dockerfile**: remove the empty `ENV OTEL_CLICKHOUSE_PASSWORD=""` line (silences SecretsUsedInArgOrEnv; runtime injection via chart Secret is the real mechanism).
9. **UI note**: leave `ui.enabled: false`; add a one-line comment in values.yaml that enabling standalone UI requires a dedicated nginx `ui` image target (do not build one).

## Validation (must pass, verbatim output captured)

- `helm lint deploy/helm/tracescope` → no required-values WARN.
- `helm template tracescope deploy/helm/tracescope --namespace tracescope > /tmp/rendered-0.2.2.yaml` → exit 0. Then verify INSIDE the rendered output: Secret contains the generated token key; ingress has the `location ^~ /internal/ { return 404; }` snippet; the nine new env keys appear in the right pod specs; image tags all `*-0.2.2`; CH memory limit 4Gi. Grep-evidence each.
- Confirm migration 004 exists and follows the 001–003 file conventions.

## Constraints recap

- NO helm upgrade / kubectl / cluster writes. NO git mutations. Only the files listed above (+ the build script's normal operation).
- Full secret values must not appear in any output. Values live only in values.yaml (operator was warned it's git-tracked; note this in the report).
- pytest is NOT required (no backend behavior change beyond a version string), but run `.venv/bin/python -m pytest tests/ -q` anyway and report the line — expected 123 passed; a failure caused by your changes must be fixed.

## Deliverable

Write `DEPLOY_FIX_REPORT.md` at repo root:
1. Per-finding fix table (finding → fix applied → file:line).
2. New image digests for 0.2.2 (verbatim push tail).
3. Render validation evidence (greps listed above, redacted).
4. Secret handling note: where values live, git-tracking caveat, how the operator retrieves the apiKey for shippers (e.g. `kubectl get secret` after rollout, or from values.yaml locally) — without printing it.
5. Remaining operator-only rollout runbook (helm upgrade command shape with no extra --set needed now, post-rollout verification incl. 401-on-unauth check and migration 004 ledger check).
6. Verbatim pytest line.
Honest reporting; real outputs only.
