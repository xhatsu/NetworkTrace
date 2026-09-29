# Jev advisory labels and recommendations

The existing semantic assessment layer now runs from the analytics worker. It uses
OpenRouter's typed `POST https://openrouter.ai/api/alpha/decisions` contract with
`typesafe/jev-1.13`. The request uses Noul for abnormality and Choice for category,
priority, and a single suggested next step. Contract reference:
[OpenRouter Jev examples](https://openrouter.ai/blog/insights/what-is-jev/).

Jev never updates detector findings, episode state/severity, operator decisions,
or alert delivery. Recommendations are read-only: observe, inspect related Traces,
compare Baseline, review access, check dependencies, or collect evidence.

## Configuration and ownership

Disabled by default. The Helm `semantic` values populate the ConfigMap:

| Value | Environment setting | Default |
| --- | --- | --- |
| enabled | OTEL_SEMANTIC_ASSESSMENT_ENABLED | false |
| provider | OTEL_SEMANTIC_PROVIDER | openrouter |
| baseUrl | OTEL_SEMANTIC_BASE_URL | https://openrouter.ai |
| model | OTEL_SEMANTIC_MODEL | typesafe/jev-1.13 |
| timeoutSeconds | OTEL_SEMANTIC_TIMEOUT_SECONDS | 15 in Helm, 30 in standalone config |
| batchSize | OTEL_SEMANTIC_BATCH_SIZE | 2 |
| budgetSeconds | OTEL_SEMANTIC_BUDGET_SECONDS | 20 |
| retrySeconds | OTEL_SEMANTIC_RETRY_SECONDS | 900 |

Configure `secrets.semanticApiKey` only in the existing ignored
`deploy/helm/tracescope/values-secrets.yaml`, or provide `OTEL_SEMANTIC_API_KEY` in
the Secret named by `secrets.existingSecret`. No credential was added or changed
by this implementation. The API key is not part of the ConfigMap or API output.

The chart requires `app.replicaCount=1` when semantic assessments are enabled.
Standalone installations must likewise run one analytics worker. Deduplication
uses the existing versioned store, not a distributed lease. Migration
`015_semantic_adviser.sql` adds the recommendation, confidence/distribution, and
submitted signal IDs; the normal storage-owner migration runner applies it.
The initial implementation did not activate a workload; see the standalone activation record below.

## Lifecycle, bounds, and API

Each cycle reads a bounded last-24-hour candidate set (at most 500 source findings
per repository), prioritizing Critical, Needs attention, Watch, then Changed.
Resolved, Expected, and infrastructure-only episodes remain excluded. The batch
limit is clamped to 1–20; the asynchronous assessment stage has a 1–60-second
overall budget. Provider work never runs on Changes GET requests.

Successful results are cached by episode key/version. Failed and abandoned pending
results are retryable after the cooldown (minimum 60 seconds). Duplicate candidates
within a batch are skipped. Legacy results without recommendations can be refreshed
after the cooldown. Evidence, observation time, and deterministic impact gates are
included in episode versioning; old versions remain visible as stale assessments.

Inputs contain at most 100 signal IDs/types, 100 structured impact gates, and eight
numeric metric comparisons. Raw reasons, entity names, IP addresses, credentials,
and request payloads are excluded. The provider rejects input beyond 24 KiB and
responses beyond 16 KiB. Inputs and results retain their existing SHA-256 digests.
`input_signal_ids` means submitted evidence, not Jev attribution;
`supporting_signal_ids` remains empty for Jev.

`GET /api/v1/changes` and `GET /api/v1/changes/{id}` return the existing
`semantic_assessment` plus `recommendation`, `recommendation_confidence`,
`recommendation_probabilities`, and `input_signal_ids`. Old rows remain readable.
Global Change detail and User Change detail reuse the same localized advisory panel,
with stale, pending, failure, and unevaluated states. No recommendation executes an
action. Provider timeout, invalid JSON/types, unavailable model, rate limits, credit
errors, and storage failures leave deterministic APIs and analytics available.
Provider exception bodies/chains are not logged or persisted.

## Verification (2026-09-29)

- 95 focused/related tests passed: mocked Jev requests, pipeline/API reads, storage
  serialization, retries, deduplication, budgets, evidence versions, change policies,
  investigation unit/security tests, and deployment topology/Helm tests.
- Tests ran from temporary symlinked test directories with `--confcutdir` there,
  avoiding the root conftest's broad ClickHouse test-database cleanup. No live LLM
  requests or production database writes were made.
- Chromium verified EN/VI recommendations, submitted evidence disclosure, stale/pending/failed/unevaluated states, and 1440px/390px/844px layouts without document overflow or page errors. Smoke script: `/tmp/check_jev_ui.py`.
- Python compilation, Helm lint, and Helm template checks passed. Secret rendering
  was checked only with synthetic test values; an existing-Secret render was also
  checked. The migration was not applied to a live database.
- TypeScript/Vite production build passed into `/tmp/jev-frontend-build`; the served
  `frontend/dist` was not replaced. Vite reports its large-chunk warning and the
  temporary output-directory notice. Pytest reports a Starlette/httpx deprecation.

Focused tests are in `tests/test_semantic_adviser.py`; existing contract and policy
tests remain unchanged. No deployment, commit, push, or Kubernetes command was run.


## Standalone activation (2026-09-29)

The local dashboard and analytics worker now run through `./run_server.sh start`
on port 30102 with live Jev enabled in the existing root `.env`. Migration 015 and
all four new columns are present; rerunning the migration runner is a no-op.
The SQL comment was corrected to avoid the runner splitting its semicolon as SQL.
A regression test covers this path. All 96 isolated related tests passed, the
served frontend was rebuilt, and live API checks passed including missing-detail
404 handling. The first verified worker cycle assessed two episodes successfully
with zero failures, and the Changes API returned their stored recommendations.
This activates the local working tree, not a Helm release.
