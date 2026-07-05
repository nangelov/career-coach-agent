# Task FIX-01-backend-test-deps — Backend test env, skip audit, and CI config check

- **Phase:** cross-cutting (post-P2 regression)   **Status:** ENG   **Tags:** (B)

## Scope

### Part A — original collection-error report (likely resolved, confirm)
`dev-board/failed-tests.md` originally captured a plain `pytest` run from `backend/tests/` (wrong/stale venv
active — the user's shell had the **repo-root** `.venv` active instead of `backend/.venv`) failing with 18
collection errors (`ModuleNotFoundError` for `sqlalchemy`, `openai`, `pytest_asyncio`) even though all three
are declared in `backend/pyproject.toml`. The user has since re-run with `uv run --no-sync pytest` from
`backend/`, which now collects and runs cleanly: **102 passed, 40 skipped in 6.36s** (see the updated
`dev-board/failed-tests.md`). Confirm whether this was purely a "wrong venv active" user-environment issue,
or whether there's a real repo-side gap (e.g. no documented/enforced way to run tests correctly — a stray
`pytest` in `$PATH` will silently pick the wrong env). If there's a repo-side gap, fix it (e.g. a documented
command, a Makefile target, or a `README`/`CONTRIBUTING` note) so this doesn't recur. Do not just note "user
error" and move on if there's nothing in the repo steering people to the right command.

### Part B — NEW: are the 40 skipped tests expected?
Same run: `test_conversation_store.py` (4 skipped), `test_identity_models.py` (6), `test_knowledge_models.py`
(9), `test_p2_exit_verification.py` (5), `test_structured_models.py` (10), `test_vector_search.py` (6) = 40.
Investigate **why** each of these is skipped (missing optional dependency? missing live Postgres/Redis?
missing env var? explicit `skipif` marker?) and determine whether that's the **intended** test design (e.g.
"integration tests skip without a live DB, unit tests use aiosqlite") or a coverage gap that's silently
hiding broken/untested code (esp. P2 persistence, pgvector, and embeddings paths). Report per-module findings
in `engineer.md`. If skips are hiding real gaps, fix them (e.g. wire up a real/aiosqlite fallback, add a
required test fixture/service) rather than just documenting them away — unless doing so is out of scope for
a single task, in which case flag the split explicitly.

### Part C — audit `.github/workflows/backend-ci.yml` (CONFIRMED BROKEN — see real run logs)
`./dev-board/pipelinee-failures/` contains the actual GitHub Actions log dump from a **real failing run** of
`backend-ci` (per-step `.txt` files under `pipelinee-failures/backend/`, plus the combined `0_backend.txt`).
This is not hypothetical — read `pipelinee-failures/backend/9_Test (pytest).txt` and
`pipelinee-failures/backend/5_Install dependencies.txt` directly. Findings already confirmed from these logs:
- CI's pytest step **fails outright** (`Interrupted: 8 errors during collection`, exit code 2) — this is worse
  than the local "40 skipped": in CI these modules don't even skip, they **error at collection** and abort
  the whole test run: `test_chat_api.py`, `test_chat_cancel.py`, `test_embeddings.py`,
  `test_identity_models.py`, `test_knowledge_models.py`, `test_p2_exit_verification.py`,
  `test_structured_models.py`, `test_vector_search.py`.
- Root cause is visible in the traceback: `app/repositories/models/knowledge.py:62: from pgvector.sqlalchemy
  import Vector` → `ModuleNotFoundError: No module named 'pgvector'`. The `Install dependencies` step log
  confirms the curated `uv pip install` list is: `fastapi pydantic pydantic-settings "celery[redis]" openai
  sqlalchemy asyncpg aiosqlite` — **`pgvector` (the Python client library) is missing from that list.** The
  explanatory comment in `backend-ci.yml` above the install step was written before pgvector-backed models
  existed (P2-04/P2-06 added the `pgvector.sqlalchemy.Vector` column type after) and was never updated, so the
  curated list drifted out of sync with what `app.repositories.models.knowledge` (imported transitively by
  almost everything via `app/repositories/__init__.py`) actually needs at import time.
- Fix: add `pgvector` to the curated install list (and update the stale explanatory comment to mention it,
  same pattern as the existing sqlalchemy/asyncpg/aiosqlite entries). Then verify: does this newly let those
  8 modules collect and run in CI, and do they then hit the *same* 40-skip pattern as local (Part B), i.e. are
  they skipping for a legitimate "no live Postgres in CI" reason once they can actually import? Confirm with
  reasoning, don't assume.
- While you're in `backend-ci.yml`, also resolve the other Part C questions: is there a live Postgres/Redis
  service (or equivalent) available to CI for tests that need one; does the lint/type-check/test command
  sequence still make sense; is the curated list otherwise complete for everything currently imported at
  collection time (not just pgvector).

## Acceptance criteria
- [ ] Root cause of the original collection errors is confirmed and, if it was more than user error, fixed
      (documented command / Makefile / README note).
- [ ] Each of the 40 skips is explained (why it skips) and classified as **expected-by-design** or
      **coverage gap**; coverage gaps are fixed or explicitly flagged as a follow-up task with rationale.
- [ ] `backend-ci.yml` is confirmed correct against the above, or fixed if it isn't (e.g. missing service
      container, curated install list out of sync with what tests actually need).
- [ ] Full backend test suite is run as the final step (`cd backend && uv run pytest` or the corrected
      documented command) and passes — any genuine failures are root-caused and fixed, not papered over.
- [ ] Findings for all three parts documented clearly in `engineer.md`.

## Design references
- dev-board/plan.md: P0-09 backend CI (ruff + mypy + pytest).
- `dev-board/code-review/P0-09-backend-ci/` — original CI task design intent (why the curated install exists).
- `backend/pyproject.toml` — declared dependency source of truth.
- `docker-compose.yml` — what services (Postgres/Redis) exist for local/integration testing.

## Constraints / non-goals
- Do not upgrade/downgrade unrelated dependency versions beyond what's needed here.
- Do not weaken or delete tests to make them pass, and do not just add `skip` markers to make failures
  disappear — if a test itself is wrong, fix it and say so explicitly.
- Per the agent-handoff skill: running the test suite and fixing root causes of failures is a **mandatory
  final step** of this task, same as every other task.
