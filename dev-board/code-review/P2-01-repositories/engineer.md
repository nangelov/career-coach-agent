# Engineer report — P2-01-repositories · Revision 2

## Summary
Built the **Postgres side of the repository layer** — the connection/session foundation all P2-02..04
tables/migrations will sit on (design §4/§8: *"services never touch drivers directly"*). New
`app/repositories/postgres.py` provides:
- a **single shared SQLAlchemy async engine/pool** (`AsyncEngine`, max 5 connections, §4) owned by a
  `PostgresConnectionProvider` mirroring P1-05's `RedisConnectionProvider` shape/lifecycle;
- a SQLAlchemy 2.x `DeclarativeBase` (`Base`) that upcoming ORM models subclass;
- a FastAPI dependency `get_db_session` yielding an `AsyncSession` per request from the shared pool.

`app/main.py`'s lifespan now **really** creates the provider at startup, verifies connectivity with a
`SELECT 1` (replacing the P0 "stubbed" Postgres log lines), and disposes the engine cleanly at shutdown.
`repositories/redis.py` was reviewed and needs no rework (see below).

## Files changed
- `app/repositories/postgres.py` — **new.** `Base` (DeclarativeBase), `PostgresConnectionProvider`
  (owns the one `AsyncEngine` + `async_sessionmaker`; `from_settings`, `session()` context manager,
  `verify_connectivity()`, `aclose()`), `get_db_session` FastAPI dependency + `get_db_session_provider`
  guard.
- `app/config.py` — new `POSTGRES_MAX_CONNECTIONS` setting (default 5, §4; applied as `pool_size` with
  `max_overflow=0`). Mirrors `REDIS_MAX_CONNECTIONS`.
- `app/repositories/__init__.py` — export `Base`, `PostgresConnectionProvider`, `get_db_session`,
  `get_db_session_provider`.
- `app/main.py` — lifespan startup builds the provider, stashes it on `app.state.pg_provider`, and runs
  `verify_connectivity()` (fail-fast); shutdown disposes it best-effort. Replaced both "stubbed (P2)"
  Postgres log lines.
- `.github/workflows/backend-ci.yml` — widened the curated install with `sqlalchemy asyncpg aiosqlite`
  (all light, no torch): `app.main` now imports the Postgres repo, so every test needs SQLAlchemy
  importable; `asyncpg` is the prod dialect the pool-config test builds a non-connecting engine against;
  `aiosqlite` is the in-memory driver the plumbing tests use instead of a live Postgres.
- `tests/test_postgres_repository.py` — **new.** 10 unit tests (approach documented below).

## Key decisions
- **Plain SQLAlchemy 2.x `DeclarativeBase`, not SQLModel.** The design doc allows either
  ("SQLAlchemy/SQLModel"); SQLAlchemy is the dependency already present (`pyproject.toml`), gives full
  mapped-column typing, first-class `pgvector` column support, and Alembic autogenerate (P2-02). Every
  P2-02..04 model subclasses this one `Base` so they share a single `metadata` (the migration target).
- **Provider mirrors `RedisConnectionProvider` (P1-05 precedent).** Build once at the composition root →
  hand out sessions → close on shutdown. `from_settings(settings)` reads `DATABASE_URL`; the engine is
  lazy (no I/O until first use), so importing the module / building the provider never connects.
- **Pool cap enforced structurally (§4 "max 5 connections").** `pool_size = POSTGRES_MAX_CONNECTIONS`
  with `max_overflow=0` ⇒ the total number of connections can never exceed the cap. `pool_pre_ping=True`
  discards a server-dropped idle connection before handing it out. `echo=DEBUG` for dev visibility.
- **Startup fail-fast connectivity check.** Lifespan runs `SELECT 1` via a pooled connection; if Postgres
  is unreachable the app does not start with a broken data layer (§4 posture). Unit tests never run the
  lifespan (httpx `ASGITransport` doesn't), so this never fires in CI.
- **`get_db_session` lives in `postgres.py`** (the task's named deliverable). It reads the provider from
  `app.state` (never a new engine per request) and yields a request-scoped `AsyncSession` closed on
  request end. Split out `get_db_session_provider` so the "lifespan never ran" guard is unit-testable
  without a `Request`. Annotated as the **bare** `Request` (rev 2 fix — see C1): FastAPI auto-injects the
  raw request only for the bare class; a subscripted `Request[Any]` is misread as a body/query field and
  raises `FastAPIError` at route registration.
- **Session hygiene:** `expire_on_commit=False` (standard async pattern — attributes stay usable after
  commit without a round-trip on a connection already returned to the pool) and `autoflush=False`.

## `repositories/redis.py` review (acceptance item)
Reviewed — **no rework needed**, consistent with this task's repository-layer intent: `RedisConnectionProvider`
owns the single shared `redis.asyncio` pool (max 10, §4), `from_settings`/`client()`/`aclose()` lifecycle,
and the two adapters (`RedisSessionMemory`, `RedisCancelRegistry`) implement service-layer ABCs. The
Postgres provider was deliberately shaped to match it. One *non-blocking* asymmetry worth noting (not fixed
here — out of this task's additive scope): Redis is still built **lazily on first request** in
`build_chat_service`, whereas Postgres is now built **eagerly in the lifespan**. A future task could move
the Redis provider to the same eager lifespan wiring for symmetry; left as-is to avoid touching Redis's
public surface (task constraint).

## How to verify
From `backend/` (local `.venv` — installed `sqlalchemy aiosqlite greenlet` from the uv cache alongside the
already-present `asyncpg`):
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app/
.venv/bin/python -m pytest -q
```
Results:
- `ruff check .` → `All checks passed!`
- `ruff format --check .` → `46 files already formatted`
- `mypy app/` → `Success: no issues found in 32 source files`
- `pytest -q` → `83 passed` (71 prior + 12 new; rev 2 added 2 FastAPI-DI tests)

**Test approach (documented per task):** *pure plumbing*, no live Postgres in CI.
- Behavioural tests (`verify_connectivity` `SELECT 1`, session yield/close, `get_db_session` dependency)
  use an **in-memory SQLite via aiosqlite** engine — it exercises the exact SQLAlchemy async
  session/engine machinery the app uses, with no network/driver-connect.
- Pool-config tests (`max 5` cap, custom cap) build a **non-connecting `postgresql+asyncpg`** engine and
  assert `pool.size()` / `max_overflow` on the real production dialect (engine/pool are constructed
  without opening a connection).
- Rationale: the design's cap is dialect-agnostic engine config and the session lifecycle is identical
  across dialects, so SQLite proves the plumbing without adding a Postgres service to the free-tier CI. A
  real-Postgres integration test lands naturally once P2-02..04 add tables/migrations.

Manual live check: `docker compose up` (db = `pgvector/pgvector:pg16`) then start the backend — the
lifespan logs `Postgres connection pool ready (max 5, SELECT 1 ok)` instead of the old stub line.

## Self-check
- [x] `app/repositories/postgres.py` exposes a single shared `AsyncEngine`-backed pool (max 5, §4) and a
  `Base` for ORM models — no per-request engine/connection creation (`from_settings` builds one engine;
  the dependency reads it from `app.state`).
- [x] FastAPI dependency (`get_db_session`) yields an `AsyncSession` per request from the shared pool.
- [x] `app/main.py` lifespan creates the provider at startup, verifies connectivity (`SELECT 1`), and
  disposes it at shutdown — P0 "stubbed" Postgres lines replaced.
- [x] `repositories/redis.py` reviewed and confirmed consistent (one non-blocking symmetry note above).
- [x] Unit tests pass (10 new; approach documented — SQLite plumbing + non-connecting asyncpg pool-config).
- [x] `ruff` + `mypy --strict` clean (output pasted).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (DB access confined to
  `repositories/`; interface `Base`/provider before any table models).

## Notes for reviewers
- **No table models / no Alembic here** — strictly the engine/session foundation (task non-goals). `Base`
  currently maps zero tables (asserted in a test); real tables + Alembic are P2-02..04.
- **CI curated install widened** (`sqlalchemy asyncpg aiosqlite`) because `app.main` now imports the
  Postgres repo — a missing lib would fail *every* test at collection (`from app.main import app`), not
  just one. All three are light (no torch/CUDA), keeping the free-tier CI posture.

## Response to review (revision 2)

Addresses code-review revision 1 (`code-review.md`, verdict `CHANGES_REQUESTED`). Architecture review was
`APPROVED`; no architecture changes were needed. All four findings addressed; no public interface changed.

- **C1 (major, gating) — `Request[Any]` breaks `Depends(get_db_session)`.** Changed the parameter
  annotation in `app/repositories/postgres.py` from `request: Request[Any]` to the **bare**
  `request: Request`, and removed the now-unused `from typing import Any` import. FastAPI only auto-injects
  the raw request for the bare `Request` class; the subscripted alias was treated as a body/query field and
  would raise `FastAPIError: Invalid args for response field!` at route registration. Verified still
  `mypy app/` clean (32 files, `Success: no issues found`) — no type-arg tension, no `# type: ignore`
  needed. Left `main.py:54`'s `Request[Any]` untouched (Starlette middleware `dispatch` signature, not
  FastAPI-analyzed), per the finding.
- **C2 (minor) — DI path not exercised by tests.** Added two tests to
  `tests/test_postgres_repository.py` that register `get_db_session` via `Depends(...)` on a throwaway
  `FastAPI` app and drive it through the real ASGI request path (`httpx.AsyncClient` + `ASGITransport`):
  - `test_get_db_session_wired_via_fastapi_depends` — route registration analyses the annotation (this is
    what C1 would have tripped), then a real `GET` request injects a live session that runs `SELECT 1`
    against the SQLite provider on `app.state`, asserting the response body. This is the standing regression
    guard for the subscripted-`Request` class of breakage.
  - `test_get_db_session_depends_raises_when_uninitialised` — through DI with no provider on `app.state`,
    the explicit `RuntimeError("not initialised")` guard fires (surfaced by `ASGITransport`'s default
    `raise_app_exceptions`).
  The pre-existing direct-call `SimpleNamespace` test is kept (fast unit coverage of the yield/close and
  session binding), now complemented by the real DI coverage.
- **C3 (nit) — `autoflush=False` unexplained.** Added a rationale comment next to the `async_sessionmaker`
  config (postgres.py) explaining that pending writes are not auto-flushed before a query, so downstream
  P2-02..04 repositories must flush/commit explicitly if a read must see their own not-yet-flushed writes —
  chosen for explicit, predictable async transaction control (implicit flushes can trigger surprising I/O
  mid-query on a pooled connection).
- **C4 (nit) — commit contract undocumented.** Extended `get_db_session`'s docstring to state the dependency
  **never commits**: callers own transaction boundaries and must `session.commit()` explicitly; any open
  transaction is rolled back as the session closes (safe no-write default). Also documented the bare-`Request`
  requirement inline so a future author does not reintroduce the subscripted form.

### Rev 2 verification (from `backend/`)
- `ruff check .` → `All checks passed!`
- `ruff format --check .` → `46 files already formatted`
- `mypy app/` → `Success: no issues found in 32 source files`
- `pytest -q` → `83 passed`
