# Code review — P2-05-migration-structured · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/repositories/models/jobs.py:84 | `source_url` is `String(2048)` and btree-`index=True`. A btree index entry is capped at ~2704 bytes; a very long (multibyte) URL near the 2048-char limit could exceed that and raise on insert of the index tuple. ASCII URLs (≤2048 bytes) are safe, so this is an edge case only. | Optional: drop the index (it's reference/display metadata, not the dedup key) or switch to a hash index / expression index on a truncated value if long-URL lookups are ever needed. Non-blocking. |
| C2 | nit | backend/app/repositories/models/dashboard.py:288 | `progress_entries.source` is a deliberate superset of the task's minimum (task only required `source` on `tasks`). Well-reasoned (a progress note can be AI-authored) and documented, but flagging so the architect can rule on scope. | None required — documented judgment call. |

## Notes
- **Verified live** against the running `career-coach-agent-db-1` Postgres container (not just trusting the report):
  - `alembic downgrade 0003` drops all 6 tables (information_schema count → 0); `upgrade head` restores them (count → 6). Clean both directions.
  - `alembic revision --autogenerate` produces an **empty** `upgrade()` (0 `op.*` calls) → no model/migration drift. Drift file deleted.
  - FK on-delete rules confirmed in `pg_constraint`: `pdps.user_id`, `goals.user_id`, `milestones.goal_id`, `tasks.goal_id`, `progress_entries.user_id` = **CASCADE**; `tasks.milestone_id`, `progress_entries.goal_id`, `progress_entries.task_id` = **SET NULL**. Matches the documented posture exactly.
  - `ruff check` + `ruff format --check` clean; `mypy app/ migrations/` clean (42 files); `pytest tests/test_structured_models.py` → **10 passed**.
- **Acceptance criteria** all met: 6 ORM models + migration `0004` chained after `0003`; `tasks.source` (`user`|`ai`) present and CHECK-enforced; cascade goal→milestones→tasks and user→goals documented + tested; `progress_entries` has no `updated_at`/update path (append-only); live upgrade/downgrade clean; lints clean.
- **Correctness spot-checks passed:** ORM `cascade="all, delete-orphan"` on `Goal.milestones`/`Goal.tasks` is consistent with the DB-level CASCADE; `Milestone.tasks` intentionally has no ORM cascade, matching the DB SET NULL (verified by `test_deleting_milestone_detaches_tasks`, which asserts the task survives with `milestone_id=None`). CHECK-constraint literals built via `repr()` of internal (non-user) tuples exactly match the migration's hand-written `IN (...)` clauses — no drift, no injection surface. `raw`/`content` JSONB `server_default="{}"` round-trips correctly (tested).
- **Security:** schema-only change, no agent/tool write paths, no untrusted input reaching constraints or SQL. No secrets. Consistent with the P2-03/04 posture.
- The `source_url` index nit (C1) is the only thing worth a follow-up and is non-blocking; both findings are nits, so this approves.
