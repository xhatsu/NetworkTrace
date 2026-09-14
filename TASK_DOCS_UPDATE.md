# TASK: Update all project Markdown documentation

Read this workspace and execute every step in order. Do not deviate from it; do not add features it does not ask for.

## Goal

The 9 project Markdown files listed below have drifted from the actual codebase. Read the ACTUAL code and update every one of them so they accurately describe the current state of the repository. Derive every fact from ACTUAL code, not guesses.

## Files to update (exactly these 9, no others)

1. `AGENTS.md`
2. `README.md`
3. `STATE.md`
4. `bootstrap/README.md`
5. `deploy/helm/tracescope/README.md`
6. `deploy/k8s/README.md`
7. `docs/ANOMALIES.md`
8. `docs/BENCHMARK.md`
9. `docs/DESIGN.md`

## How to work

1. First read all 9 target files end-to-end.
2. Then verify each factual claim in them against the actual source before rewriting:
   - Backend endpoints/ports/behavior: `backend/main.py`, `backend/app/api/*`, `backend/app/services/*`, `backend/app/repositories/*`, `backend/app/models/*`
   - Persistence: ClickHouse (`backend/clickhouse_migrations/`), `backend/app/repositories/db_context.py`
   - Frontend: `frontend/src/` structure and pages
   - Deployment: `deploy/helm/tracescope/`, `deploy/k8s/`, `Dockerfile`, `bootstrap/`
   - Runtime/lifecycle: `run_server.sh`, `docker-entrypoint.sh`
   - Known port fact: the active hub is OTelTrace on `0.0.0.0:30102`; the former NetworkTracing hub on `:31115` is legacy and not used. Make all docs consistent with this.
3. Update stale facts: wrong ports, wrong paths, removed/renamed modules, outdated feature lists, stale state descriptions, wrong file references.
4. Keep each file's existing structure, tone, and heading layout — surgical updates, not rewrites. Do not reorganize a doc for its own sake. If a section is already accurate, leave it untouched.
5. `STATE.md` should reflect the CURRENT worktree state (the tree is dirty with a large in-flight ClickHouse migration refactor — describe what is actually in flight, from the code, not what a past session claimed).
6. Do NOT create new doc files except the one report required below.

## Constraints (hard)

- Do NOT commit. Do NOT run `git add`. Do NOT stage anything. Leave the working tree as you found it — it is dirty with pre-existing in-flight work that must be preserved exactly.
- Do NOT modify anything outside the 9 listed files (plus creating `DOCS_UPDATE_REPORT.md`).
- Do NOT touch `.venv/`, `frontend/node_modules/`, `.hermes/`, `.pytest_cache/`, `.git/`, or this `TASK_DOCS_UPDATE.md`.
- Repository-relative paths only in all doc content.
- POSIX sh if you run any shell commands.

## Verification gates (run and report REAL output)

1. `ls -la` each of the 9 files after your edits (prove they exist with fresh mtimes).
2. `grep -rn "31115" AGENTS.md README.md STATE.md docs/ deploy/ bootstrap/` — any remaining reference to the legacy port must be explicitly marked legacy, not presented as active.
3. For 3 spot-check facts of your choice that you corrected, cite evidence: file + line in actual source that proves the new value.
4. `git status --porcelain | head -60` — report it verbatim at the end.

## Deliverable

Write `DOCS_UPDATE_REPORT.md` at the repo root containing, per file: what was stale, what you changed, and the source evidence (file:line). End with the verification-gate outputs. Honest reporting: if you could not verify something, say so instead of inventing it.
