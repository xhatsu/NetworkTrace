# TASK: Rebuild images via the build script, update helm chart tags — REPORT issues, do NOT fix them

You are preparing the next TraceScope rollout. Two files govern this task and you MUST read both in full before acting:
1. `scripts/build_and_push.sh` — the build script (POSIX, builds 2 images: target `api` → `:app-<ver>`, target `ingest` → `:ingest-<ver>` from `deploy/docker/Dockerfile`; pushes by default; `--no-push` and `--dry-run` flags exist).
2. `deploy/helm/tracescope/values.yaml` — the live chart values (current tags: `app-0.2.0`, `ingest-0.2.0`).

Also read `deploy/docker/Dockerfile` for build-stage context.

## Execute

1. **Rebuild + push** (host is aarch64 = cluster arch, so run WITHOUT `--platform` to use plain `docker build` path):
   ```
   sh scripts/build_and_push.sh xhatsu101/tracescope 0.2.1
   ```
   This builds both images and pushes to Docker Hub (script default). Version is 0.2.1 (next patch; do NOT overwrite 0.2.0). Expect the frontend build + pip install inside Docker to take a while — be patient, do not abort early. If docker login/push fails, capture the verbatim error and continue to step 2 with `--no-push` locally if needed, reporting the push failure.
2. **Update helm tags**: in `deploy/helm/tracescope/values.yaml` change ONLY the two image tags: `app.tag: app-0.2.0` → `app-0.2.1`, `ingest.tag: ingest-0.2.0` → `ingest-0.2.1` (and the identical `agentStats`/`ui` tags use `app-0.2.0` — update those two to `app-0.2.1` as well since they reference the same app image). Nothing else in the file changes.
3. **Render validation**: run `helm lint deploy/helm/tracescope` and `helm template deploy/helm/tracescope` (with default values). Capture output verbatim. EXPECTED: rendering may FAIL because `secrets.internalApiToken: ""` is empty and the hardened `secret.yaml` template now rejects empty/placeholder tokens at render time — that failure is a finding to REPORT, not something to work around.
4. Do NOT run `helm upgrade`, do NOT touch the cluster, do NOT set any secrets/tokens, do NOT bump `Chart.yaml` appVersion, do NOT add new env vars to the chart.

## Issues to verify and REPORT (evidence verbatim, no fixes)

- Empty `secrets.internalApiToken` → render/upgrade blocker (confirm by the lint/template output).
- Empty `secrets.apiKey` → unauthenticated public ingestion remains (live-verified previously).
- `clickhouse.resources.limits.memory: 2Gi` — CH self-caps ~1.8GiB; worker now bounds each query to 1GiB + 256MiB spill, but state the remaining headroom risk.
- New backend env knobs NOT exposed in chart config: `OTEL_INGEST_MAX_BATCH_BYTES`, `OTEL_AGGREGATION_MAX_MEMORY_USAGE`, `OTEL_AGGREGATION_EXTERNAL_GROUP_BY_BYTES`, `OTEL_AGGREGATION_SHADOW_ENABLED`, `OTEL_AGGREGATION_CUTOVER`, `OTEL_BASELINE_CADENCE_SECONDS`, `OTEL_BASELINE_SERIES_BUDGET`, `OTEL_ANOMALY_WINDOW_BUDGET`, `OTEL_ANALYTICS_STAGE_BUDGET_SECONDS` — they fall back to code defaults; chart lags the backend.
- `config.retentionDays: 30` exists in values but live-table TTLs are NOT applied by migrations (003 only covers the shadow table) — chart intent vs schema reality mismatch.
- `config.corsOrigins` lists localhost + tracescope.local but not `https://trace.n2d.id.vn` — check `backend/config.py` usage and report whether this can break anything (same-origin SPA may make it moot — verify, don't guess).
- `Chart.yaml` `appVersion`/`version` still 0.2.0 while image tags become 0.2.1 — stale metadata.
- Migration 003 (`metric_buckets_agg`) will auto-apply via the migrations initContainer on first boot of the new image — confirm `docker-entrypoint.sh`/initContainer path makes that true and report.
- Anything else you notice in Dockerfile, script, or rendered manifests (e.g. imagePullPolicy vs mutable tags, missing probes, resources).

## Constraints

- NO `git commit`/`git add`/`git stash`. Edit ONLY: nothing except... actually NO file edits at all except the four `tag:` value lines in step 2. Everything else is report-only.
- No cluster/production interaction (no helm upgrade, no kubectl mutations).
- If the build itself surfaces errors (Dockerfile, dependency, frontend build), REPORT them verbatim and stop that image's build — do not patch the Dockerfile.

## Deliverable

Write `DEPLOY_PREP_REPORT.md` at repo root:
1. Build result per image (verbatim script tail: tags, digest if pushed, duration).
2. Helm edit confirmation (the 4 tag lines, before→after).
3. lint/template output verbatim + render-blocker finding.
4. Issue list: each with severity (blocker / should-fix-before-rollout / note), evidence, and the fix you WOULD recommend — but did not apply.
5. Operator runbook: the exact remaining steps you did NOT execute (helm upgrade command shape, required --set values, post-rollout verification), left to the operator.
Honest reporting; real outputs only.
