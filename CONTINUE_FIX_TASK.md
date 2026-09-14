# TASK: Complete the in-progress fix job (continuation from another agent)

A previous agent was executing `FIX_TASK.md` in this repo (fix every finding in `CODE_REVIEW_FINDINGS.md`) but was cut off by a usage limit partway through. Its work is ALREADY IN THIS WORKTREE — uncommitted, intentionally. Your job is to pick up exactly where it stopped and finish.

## Continuation rules

1. Do NOT revert, clean, or "tidy" any existing uncommitted change. Do NOT run `git checkout`/`git restore`/`git stash`. The dirty state is the accumulated fix work.
2. First, assess what is already done: read `FIX_TASK.md`, `CODE_REVIEW_FINDINGS.md`, then inspect the current code for each of the 21 findings (use the file:line refs in the findings file as starting points — lines have shifted, so locate by symbol/pattern). Known-completed work observed so far: new migration `backend/clickhouse_migrations/002_integrity_and_retention.sql` (row-ID/retention), incremental bounded gzip decompression in `backend/app/services/otlp_parser.py`, placeholder-token rejection in `deploy/helm/tracescope/templates/secret.yaml`, ingest-writer dedup failure-injection tests, agent-stats TTL test, ReplacingMergeTree/FINAL rework of upsert paths.
3. Classify every finding: `already-fixed` / `partially-fixed (finish it)` / `not-started (implement)` / `false-positive (skip, document)`. Verify by reading code — do not trust this list blindly.
4. Complete all partially-fixed and not-started findings following the workflow, fix guidance, and constraints in `FIX_TASK.md` (verify → minimal fix → focused test; NO git commit/add/stash; do not weaken tests; defer with documented reason only if genuinely too risky).
5. Pay special attention to the highest-severity items most likely incomplete:
   - Critical #2: does `ingress.yaml` still route `/internal/*` publicly? (a probe found no change there yet) — implement render-time placeholder rejection + internal-route isolation.
   - High #5: auth on OTLP/APM ingest aliases, agent-stats DELETEs, reference_compat policy writes, user-review mutations — check whether a central/router-wide dependency was added; if not, add it.
   - High #1/#2/#3 (adapter upsert semantics, dedup marker-before-data transactionality, storage-owner URL in manifests) — verify each end-to-end.
6. Keep the in-flight ClickHouse migration direction (clickhouse_migrations/ is the source of truth; backend/migrations/*.sql deletions are intentional).

## Testing

- Python: `.venv/bin/python -m pytest tests/ -q` — run full suite; iterate until green or failures are proven pre-existing/unrelated (show evidence in report).
- If you touch manifests: `python3 deploy/k8s/validate_manifests.py deploy/k8s`.

## Deliverable

Write `FIX_REPORT.md` at repo root (it does not exist yet):
1. Per-finding status table: `# | severity | title | status (fixed / already-fixed / skipped-false-positive / deferred) | files changed`.
2. 1-3 sentences per fixed finding on approach; evidence/reason per skipped/deferred one.
3. Verbatim baseline-vs-final pytest summary lines (run the baseline yourself now — the previous agent's baseline is not available; note this in the report).
4. Any files changed outside expected scope, with justification.
5. A short "Continuation notes" section: what the previous agent had done, what you completed.
