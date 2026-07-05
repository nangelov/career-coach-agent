# Engineer report — FIX-01-backend-test-deps · Revision 1

## Summary
Three-part regression fix around the backend test environment and CI.

- **Part A (original collection errors):** confirmed as a wrong-venv user-environment issue, **not** a
  repo-side gap in the general case — the repo already steers people to the correct command
  (`backend/Makefile` targets + `uv run --no-sync`, whose header comment explicitly warns that a bare
  `pytest` picks the wrong venv). **However**, the `Makefile install` target carried the *same* curated-list
  drift as CI (missing `pgvector`), so `make install && make test` would reproduce the CI failure for a fresh
  contributor — fixed.
- **Part B (40 skips):** all 40 skips are the **same** live-Postgres integration gate
  (`"Postgres not reachable at DATABASE_URL — integration test skipped"`). **Expected-by-design**, not a
  coverage gap. Proven not-hiding-broken-code by running them against the live docker-compose Postgres
  (`make test-integration` → **142 passed**).
- **Part C (CI broken):** confirmed and fixed. CI's curated `uv pip install` list was missing the `pgvector`
  Python client lib, which `app/repositories/models/knowledge.py:62` imports at module load and which is
  pulled in transitively by nearly everything via `app/repositories/__init__.py`. Added `pgvector` to the
  curated list (CI + Makefile) and updated the stale explanatory comment. Verified the fix end-to-end in a
  clean fresh venv mirroring CI.

## Files changed
- `.github/workflows/backend-ci.yml` — added `pgvector` to the curated `uv pip install` list; expanded the
  "Install dependencies" comment to explain why (P2-04/P2-06 `pgvector.sqlalchemy.Vector` column type,
  imported transitively at collection → must be present or the whole suite errors at collection). It is a
  pure-Python client lib (no torch/CUDA), so the free-tier/light-install posture is preserved.
- `backend/Makefile` — added `pgvector` to the `install` target's curated list so `make install` (and thus
  `make test` / `make check`) stays in sync with CI and with what the models import. (DRY: same list, two
  places — both were drifting.)
- `backend/tests/conftest.py` — restored the blank line after `from __future__ import annotations` that a
  stray uncommitted working-tree edit had removed. That edit breaks ruff import-sorting (`I001`) and would
  fail CI's `ruff check` step; the committed version was already correct, so this restores it. Not a test
  weakening — pure import formatting.

## Key decisions
- **Add `pgvector`, do not restructure imports.** The alternative (lazy/guarded import of `Vector`) would
  hide a genuinely-required runtime dependency and diverge test-time from prod-time import behavior. The
  design (P0-09) chose a *curated* light install precisely so light-but-required libs are listed explicitly;
  `pgvector` is exactly that class (like `sqlalchemy`/`asyncpg`/`aiosqlite` already there). Ref: task.md Part
  C, `dev-board/code-review/P0-09-backend-ci/`.
- **No Postgres/Redis service container added to CI.** The 40 integration tests are intentionally
  `skip-not-fail` when no live DB is reachable (locked P0-09 posture: free-tier CI, no service containers;
  integration coverage runs via `make test-integration` against docker-compose). Adding a `services:`
  Postgres (with the `pgvector` extension) + running migrations in CI is a real coverage improvement but a
  meaningful scope expansion beyond this fix — **flagged as a follow-up** below rather than bundled here.
- **Redis needs nothing extra.** The Redis-backed suites (`test_session_memory`, `test_chat_persistence`,
  `test_llm_router`) already pass in CI via in-process fakes; `redis` arrives transitively through
  `celery[redis]`. Verified they collect and pass in the clean fresh-venv sim.

## Part B — per-module skip audit (all expected-by-design)
Every skip reason is identical: `Postgres not reachable at DATABASE_URL — integration test skipped`, emitted
from a live-connection probe fixture (skip, never error). Counts confirmed via `pytest -rs`:

| module | skipped | why it skips | classification |
|--------|---------|--------------|----------------|
| `test_conversation_store.py` | 4 | needs live Postgres + migration 0002 (identity schema) | expected-by-design |
| `test_identity_models.py` | 6 | needs live Postgres + migration 0002 | expected-by-design |
| `test_knowledge_models.py` | 9 | needs live Postgres + knowledge schema (JSONB/pgvector cols not in SQLite) | expected-by-design |
| `test_p2_exit_verification.py` | 5 | P2 exit checks against live Postgres + migrated schema | expected-by-design |
| `test_structured_models.py` | 10 | needs live Postgres (Postgres-specific column types) | expected-by-design |
| `test_vector_search.py` | 6 | needs live Postgres + `0003` pgvector schema | expected-by-design |

**Evidence they hide no broken code:** `make test-integration` against the live docker-compose Postgres runs
all 40 and passes (**142 passed in 11.90s**). So the skips are legitimate environment gating, not silent
coverage rot. Unit paths for the same layers (aiosqlite/fakes) already run unconditionally
(`test_postgres_repository`, `test_chat_persistence`, `test_embeddings`, etc.).

## Part C — CI verification result
Once `pgvector` is installed, all 8 previously-erroring modules **collect** (no more
`ModuleNotFoundError: No module named 'pgvector'`). Of those 8: the 3 unit-style modules
(`test_chat_api`, `test_chat_cancel`, `test_embeddings`) run and **pass**; the 5 integration modules
(`test_identity_models`, `test_knowledge_models`, `test_p2_exit_verification`, `test_structured_models`,
`test_vector_search`) **skip** for the *same legitimate "no live Postgres in CI" reason as local* — confirmed
by reproduction (below), not assumed. `pgvector` is the **only** missing collection-time package: with it
added, the entire suite (142 items) collects with zero errors.

### Follow-up flagged (not done here, by design)
Integration tests never execute in CI (they skip). If we want that coverage in CI, a follow-up task should add
a Postgres `services:` container built on a `pgvector`-enabled image, run `alembic upgrade head`, and export
`DATABASE_URL` for the pytest step (mirroring `make test-integration`). Deliberately out of scope for this
minimal-fix task per the P0-09 free-tier posture.

## How to verify
- Local gate (mirrors CI): `cd backend && make check` → ruff + format + mypy + pytest all green.
- Integration coverage: `docker compose up -d db && cd backend && make migrate && make test-integration`.

## Tests (final step — mandatory)
- **Local unit gate** `cd backend && make check`: `ruff check` → *All checks passed!*; `ruff format --check`
  → *72 files already formatted*; `mypy app/ migrations/` → *Success: no issues found in 49 source files*;
  `pytest` → **102 passed, 40 skipped**.
- **Live-DB integration** `make test-integration` (docker-compose Postgres up + migrated): **142 passed**.
- **CI-bug reproduction (fresh venv, curated list WITHOUT pgvector):** `8 errors during collection`,
  `ModuleNotFoundError: No module named 'pgvector'`, `Interrupted`, exit 2 — byte-for-byte the reported
  failure.
- **CI-fix proof (fresh venv, FIXED curated list WITH pgvector, no live DB — exactly like CI):** all four CI
  steps pass — `ruff check` *All checks passed!*, `ruff format --check` *72 files already formatted*, `mypy`
  *Success: no issues found in 49 source files*, `pytest` **102 passed, 40 skipped**. This is the same
  pass/skip pattern as local, confirming Part C's expectation.
- **One test-fix applied (not a weakening):** `tests/conftest.py` import spacing restored to fix a pre-existing
  stray-edit `ruff I001` lint failure that would have failed CI's lint step; behavior of the fixture is
  unchanged.

## Self-check
- [x] Meets acceptance criteria (all three parts addressed: root cause confirmed/fixed; 40 skips explained +
      classified; `backend-ci.yml` fixed; full suite green as final step; findings documented here).
- [x] No secrets committed; Router→Service→Agent/Repo layering untouched (only CI config, Makefile, and a test
      import-spacing restore).
- [x] Tests/lints pass (pasted above): `make check` fully green; CI fix proven in a clean fresh venv.
