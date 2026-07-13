# Code review — P6-02-market-schema · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | migrations/versions/20260713_0007_market_intelligence.py:141 | Downgrade re-adds `match_score` as the last column of `jobs` rather than its original mid-table position. Purely cosmetic (column order is not semantically significant); the round-trip is otherwise faithful. | None required — noting only. |

## Notes
Verified live against `career-coach-agent-db-1` (pgvector/pg16):
- `alembic upgrade head` → `downgrade -1` → `upgrade head` cycles cleanly. After downgrade, `jobs` is restored **with** `match_score` and `role_profiles`/`job_postings` are gone; re-upgrade succeeds.
- `alembic check` → "No new upgrade operations detected" — no model↔migration drift.
- Post-upgrade schema on `job_postings`: pkey `job_postings_pkey`, unique `uq_job_postings_source_external_id`, and indexes `ix_job_postings_source_url` / `ix_job_postings_target_role` / `ix_job_postings_expires_at` all present; transient `server_default` on `target_role`/`expires_at` correctly dropped (matches ORM = no default).
- Rename targets are correct: P2-05 created those exact names (`uq_jobs_source_external_id`, `ix_jobs_source_url`, default `jobs_pkey`), so the constraint/index/pk renames resolve.
- `pytest tests/test_market_models.py tests/test_structured_models.py -q` → **15 passed**. `ruff check` + `mypy` on touched files clean.

Acceptance criteria met:
- Migration up/down verified live (criterion 1). ✓
- `RoleProfile` (new) + `JobPosting` (renamed `Job`) colocated in `repositories/models/market.py`, `CreatedAtMixin`, explicit `__tablename__`, docstrings citing §5.6/§7.6 and the PII-stripped-at-ingest posture (criterion 2). ✓
- No dangling `Job` references — grep of `app/`,`tests/`,`migrations/` shows only unrelated prose ("Job title", graph comments); `__init__.py` re-exports `JobPosting`/`RoleProfile` with `__all__` updated (criterion 3). ✓
- `role_profiles.canonical_role` UNIQUE, verified by `test_role_profile_canonical_role_unique` and `pg_constraint` (criterion 4). ✓
- Migration/shape tests present and green (criterion 5). ✓
- Schema-only — no `/api/jobs` endpoint added; `match_score` dropped, not repurposed (criterion 6). ✓

Correctness/security: both tables are global with no `user_id`/no FK/no cascade (asserted in tests + docstrings), so a GDPR user-delete (§7.6) never touches them — correct for non-personal aggregate. No untrusted-input, secret, or injection surface in a schema-only change. Note the 12 `test_tools.py` failures the engineer flagged are from the parallel P6-03 tavily work in the shared worktree, outside this task's scope — confirmed not caused by P6-02.
