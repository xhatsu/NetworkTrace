# TASK: Fix all findings from the code review

You are fixing every finding reported in `CODE_REVIEW_FINDINGS.md` (repo root — a full code review of this repository, 21 findings: 2 critical, 8 high, 8 medium, 3 low, plus a test-gaps list). Work through ALL of them to completion.

## Context about this worktree

- The worktree is intentionally dirty: it carries an in-flight ClickHouse migration refactor and staged deletions of `backend/migrations/*.sql` (superseded by `backend/clickhouse_migrations/`). This state is correct — do NOT restore deleted files, do NOT clean anything, do NOT try to "fix" the dirty state.
- The 9 project `.md` files were just updated. Do not edit them unless one of your fixes makes a documented fact wrong; if you must, note it in the report.

## Workflow — for each finding, in order (critical → high → medium → low)

1. **Verify**: read the cited code (`file:line` in the findings file). Confirm the finding is real.
2. **Fix**: if real, implement the minimal, correct fix. The findings file includes suggested fixes — follow them unless code inspection shows a better approach. Preserve existing style/structure.
3. **Skip**: if the finding is a false positive or misreads the code, skip it and record the evidence in the report. Do not "fix" non-bugs.
4. **Test**: add or extend a focused test covering the fix where practical. Also address the related items from the Test-gaps list (multi-row ID uniqueness, failure injection between dedup marker and trace insert, auth coverage on mutating routes, bounded gzip decompression, ASGI path-traversal tests, service-baseline dimensional grain).

## Fix-specific guidance

- **ID uniqueness (critical #1)**: schema change — do not rewrite `001_initial.sql` history; add a new migration file under `backend/clickhouse_migrations/` and update the code paths (writer, incremental cursors, lookups) consistently. Check whether the live DB on `127.0.0.1:8123` has real data and whether migration tooling applies new files automatically.
- **Helm internalApiToken (critical #2)**: implement the report's recommendation (require explicit token, reject placeholder at render time, keep `/internal/*` off the public Ingress).
- **ClickHouse adapter (high #1)**: replace silently-weakened SQLite semantics with explicit ClickHouse-native operations (aggregating/versioned merges) at the call sites — keep the dialect translation confined to `db_context.py` where possible.
- **Auth gaps (high #5)**: prefer router-wide dependency / central mutation policy over per-route sprinkling.
- Do not introduce new dependencies unless absolutely necessary; the venv already has what the app uses.

## Constraints (hard)

- NO `git commit`, NO `git add`, NO `git stash`, NO branch switching. Edit files in place only.
- Do not modify anything under `.venv/`, `frontend/node_modules/`, `.git/`, `.hermes/`.
- Do not weaken, delete, or skip existing tests to make things pass. Fix code, not tests.
- If a fix turns out to be too risky/invasive to do safely, stop on that finding, mark it `deferred` with the reason, and move on. Honest reporting over completeness.

## Testing

- Python for all test runs: `.venv/bin/python -m pytest tests/ -q` (repo venv has clickhouse-connect).
- FIRST run the full suite to get a baseline; record output. If there are pre-existing failures at baseline, record them — do not conflate with your changes.
- After fixes, run the full suite again; iterate until green (or until remaining failures are proven pre-existing/unrelated — show evidence).
- Also run `python3 deploy/k8s/validate_manifests.py deploy/k8s` if you touch manifests.

## Deliverable

Write `FIX_REPORT.md` at repo root containing:
1. Per-finding status table: `# | severity | title | status (fixed / skipped-false-positive / deferred) | files changed`.
2. For each fixed finding: 1-3 sentences on the approach taken.
3. For each skipped/deferred finding: the evidence or reason.
4. Test baseline vs final: verbatim pytest summary lines.
5. Any files changed outside the expected scope, with justification.
