# TASK: Full code review of this repository (review-only, no edits)

You are performing a comprehensive code review of the OtelTrace repository. READ-ONLY task.

## Scope

Review ALL first-party code in the current worktree (which is dirty — it carries an in-flight ClickHouse migration refactor plus documentation updates; that is intentional, do not treat uncommitted state as an accident, but DO report real bugs in it):

- `backend/` — FastAPI application: `main.py`, `app/api/*`, `app/services/*`, `app/repositories/*`, `app/models/*`, `clickhouse_migrations/`, `agent_stats_main.py`, `benchmark.py`, and the test suite in `tests/`
- `frontend/src/` — React/Vite app (skip `node_modules`)
- `deploy/helm/tracescope/` and `deploy/k8s/` — manifests/values + `validate_manifests.py`
- `bootstrap/`, `run_server.sh`, `docker-entrypoint.sh`, `Dockerfile`
- EXCLUDE entirely: `.venv/`, `frontend/node_modules/`, `.git/`, `.hermes/`, `.pytest_cache/`, all `*.md` files, `CODE_REVIEW_REPORT.md`, `TASK_DOCS_UPDATE.md`

## What to look for (prioritized)

1. **Correctness bugs** — logic errors, wrong async usage (blocking calls in async handlers), incorrect exception handling, off-by-one, None-handling.
2. **Concurrency/races** — shared state in the FastAPI app, background task safety, ClickHouse client reuse, cache invalidation.
3. **Security** — the API binds `0.0.0.0:30102` with optional `X-API-Key` (`OTEL_API_KEY`): injection risks (especially ClickHouse query construction — string interpolation vs parameterized), auth bypass paths, SSRF, unvalidated input on ingest endpoints, secrets handling.
4. **Data integrity** — ClickHouse migration correctness, idempotency, rollup/aggregation math (percentiles, baselines, anomaly scoring), repository/DB transaction boundaries.
5. **API contract consistency** — response models vs actual returns, status codes, breaking mismatches between frontend calls (`frontend/src`) and backend routes.
6. **Deployment risks** — manifest/values inconsistencies, health/readiness probe correctness, resource limits, ingress config.
7. **Test gaps** — critical paths with no coverage (state which, briefly).
8. **Performance** — N+1 query patterns, unbounded queries, missing pagination on large trace tables.

## Rules (hard)

- Do NOT modify, create, or delete ANY file. Do NOT run `git add`/`git commit`. Read-only review; your entire output goes into your final response.
- Derive every finding from actual code you read. Include `file:line` for every finding.
- If unsure whether something is a bug, investigate the surrounding code before reporting; if still unsure, label it `needs-verification` instead of guessing.
- Do not pad the report with praise or summaries of what the code does — findings only, plus a short scope/coverage note.

## Output format (final response)

Markdown report:
1. **Coverage** — what you actually read (dirs/file counts), what you skipped and why.
2. **Findings** — each as: `[SEVERITY] title — file:line` followed by 2-5 sentences: what's wrong, evidence, suggested fix. Severity: `critical` / `high` / `medium` / `low`. Order by severity.
3. **Test gaps** — bullet list.
4. **Verdict** — one paragraph overall assessment.
