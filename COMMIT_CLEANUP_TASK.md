# TASK: Commit the worktree and remove unused files — first-ever commit authorization

The operator has authorized a commit for the first time in this project's history. The worktree carries days of verified work: doc updates, the full code-review fix set (22 findings), SQL aggregation phase 1 (verbatim contract preserved), phases 2–5 (shadow states, decoupled worker, deterministic anomaly IDs), deploy-prep + deploy-fix (0.2.2 images, secrets, TTL migration 004), and their reports.

## Part A — Secrets must NOT enter git history (hard rule)

`deploy/helm/tracescope/values.yaml` currently contains two real secrets (`secrets.internalApiToken`, `secrets.apiKey`, 64 chars each). Before committing:
1. Create `deploy/helm/tracescope/values-secrets.yaml` containing ONLY:
   ```yaml
   secrets:
     internalApiToken: "<real token>"
     apiKey: "<real key>"
   ```
2. Add `values-secrets.yaml` to `.gitignore` (repo root .gitignore, create/append).
3. In `values.yaml` set both back to `""` with a comment: `# Real values live in gitignored values-secrets.yaml (helm upgrade -f values-secrets.yaml)`.
4. Verify render still works WITH the secrets file: `helm template tracescope deploy/helm/tracescope --namespace tracescope -f deploy/helm/tracescope/values-secrets.yaml` → exit 0. (Render without it is EXPECTED to fail on the token guard — that's by design.)
5. Update the rollout runbook line in `DEPLOY_FIX_REPORT.md` §5 to include `-f deploy/helm/tracescope/values-secrets.yaml`.

## Part B — Remove unused files (evidence-based, conservative)

1. **Database/DB-adjacent files**: find every `*.db`, `*.sqlite*`, `*.sqlite-wal`, `*.shm`, `*.duckdb`, backup dumps, and `data/` leftovers in the repo (NOT in .venv/node_modules). For each: check references (grep code + scripts + docs) and mtime. Delete only ones provably unused by current code paths. Known context: SQLite was fully purged 2026-09-11 and ClickHouse is the sole store — any `data/*.db` remnants are dead. Report each deletion with the evidence of non-use.
2. **Junk**: `__pycache__/`, `.pytest_cache/` (if not already ignored — add to .gitignore rather than commit), stray `/tmp`-style artifacts inside the repo, empty dirs.
3. **Do NOT delete**: `frontend/dist` (image build may use it), `bootstrap/bundle.tar.gz` (served by the bootstrap server), the 2M dataset (lives in NetworkTracing, out of scope), any `*_REPORT.md`/`*_PROGRESS.md` (work record), `CODE_REVIEW_FINDINGS.md`, migrations, tests.
4. **Ambiguous files** (e.g. old task briefs `*_TASK.md`, `TASK_DOCS_UPDATE.md`): do NOT delete — list them in the report with your recommendation.

## Part C — Commit

1. `git add -A` then verify with `git status` what's staged; ensure `values-secrets.yaml` is NOT staged (gitignore working).
2. One commit (or a small number of logical commits if cleaner — your call, max 3):
   - Suggested single message:
   ```
   feat: 0.2.2 release — CH-native SQL aggregation, shadow states, decoupled worker, deploy hardening

   - Fix all 22 code-review findings (row-ID uniqueness, helm token guard, auth middleware, dedup ordering, gzip bomb guard, traversal, TTL)
   - Move aggregation into ClickHouse SQL (nearest-rank-exact quantiles, parity-tested); bounded slices + composite cursor
   - Shadow AggregatingMergeTree states + TDigest validation; cutover flag OFF
   - Decoupled worker stages with independent checkpoints, cadences, budgets; deterministic anomaly IDs
   - Byte-capped coalescing writer; per-stage memory telemetry; cardinality instrumentation
   - Deploy prep/fix: 0.2.2 images, helm token+apiKey, CH 4Gi, migration 004 live TTLs, CORS, 9 env knobs in chart
   - Secrets moved to gitignored values-secrets.yaml; docs and reports updated
   ```
3. NO push (no remote confirmed). Report `git log --stat -1` summary (files, insertions/deletions).
4. After commit: `git status` should show only gitignored/untracked leftovers (values-secrets.yaml, maybe pytest cache).

## Part D — Verification (report verbatim)

- `git log --oneline -3`
- `git show --stat HEAD | tail -5`
- **Secret leak scan**: `git grep` the two real secret values across ALL history reachable from HEAD (`git grep <value> $(git rev-list --all)` style, or search the committed tree) → must be 0 hits. Also confirm values-secrets.yaml not tracked: `git check-ignore -v deploy/helm/tracescope/values-secrets.yaml`.
- `helm template ... -f values-secrets.yaml` exit 0.
- `.venv/bin/python -m pytest tests/ -q` final line (123 expected).

## Deliverable

Write `COMMIT_CLEANUP_REPORT.md` at repo root: deletions table (file → evidence of non-use), files kept-but-flagged, commit hash + stat, verification outputs (secret scan MUST show 0 hits — print the scan commands, never the values), and the corrected rollout command. Never print any secret value.
