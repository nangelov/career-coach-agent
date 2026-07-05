# Code review — P2-01-repositories · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major | backend/app/repositories/postgres.py:154 | (rev 1) `get_db_session(request: Request[Any])` — subscripted `Request` is a `_GenericAlias`, so `Depends(get_db_session)` raised `FastAPIError` at route registration. | **Resolved.** Parameter is now bare `request: Request`; the unused `from typing import Any` import was dropped from the module. A real route wiring `Depends(get_db_session)` now registers and serves (see C2 test). |
| C2 | minor | backend/tests/test_postgres_repository.py:158,186 | (rev 1) DI path was never exercised — the only coverage called `get_db_session` directly with a `SimpleNamespace`, so C1 slipped past green tests. | **Resolved.** Added `test_get_db_session_wired_via_fastapi_depends` (registers `Depends(get_db_session)` on a throwaway `FastAPI` app, drives a real `GET` over `ASGITransport`, asserts `SELECT 1` result) — this is the standing regression guard for the subscripted-`Request` breakage — plus `test_get_db_session_depends_raises_when_uninitialised` (guard fires through DI). The fast direct-call test is retained as unit coverage. |
| C3 | nit | backend/app/repositories/postgres.py:76-80 | (rev 1) `autoflush=False` set silently. | **Resolved.** Rationale comment added: pending writes are not auto-flushed before a query, so P2-02..04 repos must flush/commit explicitly to see their own not-yet-flushed writes; chosen for explicit, predictable async transaction control. |
| C4 | nit | backend/app/repositories/postgres.py:162-164 | (rev 1) `get_db_session` commit contract undocumented. | **Resolved.** Docstring now states the dependency never commits — callers own transaction boundaries and must `commit()` explicitly; any open transaction is rolled back as the session closes. The bare-`Request` requirement is also documented inline to prevent regression. |

## Notes
- All four rev-1 findings are genuinely fixed in the code (not just claimed): verified bare `Request` at postgres.py:154, no residual `typing.Any` import in the module, the two new FastAPI-DI tests, the `autoflush` comment, and the extended `get_db_session` docstring.
- Re-ran the full suite locally in `backend/` (`.venv`): `ruff check .` → All checks passed; `ruff format --check .` → 46 files already formatted; `mypy app/` → Success, no issues in 32 source files; `pytest -q` → **83 passed**. Engineer's rev-2 results reproduce exactly.
- The rev-1 C1 fix required no `# type: ignore` — mypy strict is clean with the bare annotation, as predicted. `main.py`'s `Request[Any]` (Starlette middleware `dispatch` signature, not FastAPI-analyzed) was correctly left untouched.
- Everything else from rev 1 still holds: single shared `AsyncEngine`, `pool_size` + `max_overflow=0` structurally enforcing §4 "max 5", `pool_pre_ping`, lazy engine, `DeclarativeBase` `Base` with zero tables, no Alembic/table models (task non-goals), no secrets, `echo` gated on `DEBUG`. `repositories/redis.py` reviewed — consistent, no rework; the noted lazy-vs-eager provider-build asymmetry remains a fine-to-defer minor.
- No new issues introduced by the revision.
