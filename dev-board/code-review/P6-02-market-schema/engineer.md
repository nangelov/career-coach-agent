# Engineer report — P6-02-market-schema · Revision 1

## Summary
Rescoped the P2-05 `jobs` table into the P6 market-intelligence group and added the durable
`role_profiles` artifact (design §5.6). Renamed `jobs` → `job_postings`, renamed the ORM
class `Job` → `JobPosting` (moved into a new colocated `market.py` alongside `RoleProfile`),
dropped per-posting `match_score`, and added `target_role` + `expires_at` (both NOT NULL,
indexed). New Alembic migration `0007` applies, downgrades, and re-applies cleanly with no
model↔migration drift. Schema-only — no ingestion/mining, no `/api/jobs` endpoints.

## Files changed
- `backend/app/repositories/models/market.py` (new) — `RoleProfile` (global, non-personal,
  `canonical_role` unique) + `JobPosting` (renamed `Job`, no `match_score`, adds
  `target_role`/`expires_at`); docstrings cite §5.6/§7.6 posture.
- `backend/app/repositories/models/jobs.py` (deleted) — content moved to `market.py`.
- `backend/app/repositories/models/__init__.py` — re-export `JobPosting` + `RoleProfile`
  instead of `Job`; updated `__all__` and the table-group comment.
- `backend/migrations/versions/20260713_0007_market_intelligence.py` (new) — rename table +
  its constraint/index/pk, drop `match_score`, add the two evidence columns (transient
  server_default to backfill any cached rows, then dropped so the schema matches the ORM),
  create `role_profiles`; full reverse in `downgrade()`.
- `backend/tests/test_market_models.py` (new) — 7 integration checks for the new group.
- `backend/tests/test_structured_models.py` — removed the two `Job` tests (now in
  `test_market_models.py`), switched the schema-probe to `Pdp`, updated the module docstring.

## Key decisions
- **Colocated `market.py` (not renamed `jobs.py`).** Task offered either; chose the new file
  so `RoleProfile` + `JobPosting` sit together as the market-intel group, mirroring how
  `knowledge.py`/`dashboard.py` group their tables. `Job` had no callers outside the model
  `__init__` and one test, so the rename fan-out was contained.
- **`match_score` dropped, not repurposed** — §5.6 P6: "match scoring" now means
  `user profile △ role_profile` (the skills gap), computed on demand, never stored on a
  posting. No `/api/jobs` surface (schema-only).
- **`target_role`/`expires_at` NOT NULL via transient server_default.** `jobs` is a TTL cache
  that may hold rows; adding NOT NULL columns backfills them with a temporary default, then
  the default is dropped so the final DDL equals `create_all` from the model (verified by
  `alembic check` reporting no drift).
- **`role_profiles` has no `user_id` / no FK / no cascade** — global, non-personal aggregate
  (§5.6); a GDPR user-delete (§7.6) never touches it. `canonical_role` is UNIQUE (one profile
  per role, reused across users).
- **PII-stripping is documented, not enforced here** — that lives in P6-04 ingestion; the
  schema (raw JSONB + no recruiter columns) supports it (§7.6).

## How to verify
```
cd backend
docker compose -f ../docker-compose.yml -f ../docker-compose.dev-ports.yml up -d db
make migrate-integration        # upgrade head (applies 0007)
make test-integration           # or: pytest tests/test_market_models.py tests/test_structured_models.py
```
Migration cycle proven manually: `alembic upgrade head` → `downgrade -1` (jobs restored,
match_score re-added, role_profiles/job_postings gone) → `upgrade head` again, then
`alembic check` → "No new upgrade operations detected."

## Tests (final step — mandatory)
- `pytest tests/test_market_models.py tests/test_structured_models.py -q` → **15 passed**
  (against the live docker-compose Postgres).
- Full suite: `pytest -q` → **541 passed, 1 skipped, 12 failed**.
  - The 12 failures are **all in `tests/test_tools.py`**
    (`TypeError: InternetSearchTool.__init__() got an unexpected keyword argument 'base_url'`)
    and are **not caused by this task**. `git status` shows the shared working tree currently
    holds uncommitted in-flight edits from the parallel **P6-03** (tavily pool) task
    (`app/tools/internet_search.py`, `tests/test_tools.py`, `app/tools/tavily_pool.py`).
    Those files are outside P6-02's scope (schema/models only) — fixing them belongs to P6-03,
    not here. Every test in my scope (models, repositories, migrations) is green.
- `ruff check` + `mypy` on all touched files → clean.

## Self-check
- [x] Meets acceptance criteria (rename + reshape + `role_profiles` + unique `canonical_role`
      + updated imports + migration up/down + tests + no `/api/jobs`).
- [x] No secrets committed; Router→Service→Repo layering respected (this is the Repo/model layer).
- [x] Tests/lints pass for this task's scope (paste above); pre-existing unrelated failures flagged.

## Response to review (revisions only)
- N/A (revision 1).
