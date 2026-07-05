# Task P2-01-repositories — `repositories/postgres.py` foundation (+ confirm `repositories/redis.py`)
- **Phase:** P2   **Status:** ENG   **Tags:** (B)

## Scope
Build the **Postgres side of the repository layer**, design §4/§8: *"services never touch drivers directly"*.
`repositories/redis.py` already exists (built in P1-05: `RedisConnectionProvider`, `RedisSessionMemory`,
`RedisCancelRegistry`) — review it briefly to confirm it still fits this task's intent, but the primary
deliverable here is `repositories/postgres.py`. No table-specific migrations exist yet (that's the next
three tasks, P2-02..P2-04); this task builds the **connection/session foundation** all of them will sit on.

Build `backend/app/repositories/postgres.py`:
- A **single shared async connection pool** (design §4: *"the `repositories/postgres.py` layer maintains a
  single shared async connection pool (SQLAlchemy `AsyncEngine`) — max 5 connections — shared across all
  requests and agents. Do not open per-request connections; acquire from the pool via the repository layer
  only."*). Use SQLAlchemy 2.x async (`create_async_engine`, `async_sessionmaker`) reading `DATABASE_URL`
  from `app/config.py` (already present).
- A `Base`/declarative-base setup (SQLAlchemy `DeclarativeBase` or SQLModel — pick one consistently; the
  design doc says "SQLAlchemy/SQLModel", so either is acceptable, but document the choice since every future
  migration/model in P2-02..04 will follow it) that upcoming ORM models (P2-02/03/04) will subclass.
- A composition-root-friendly accessor (e.g. `PostgresConnectionProvider` mirroring P1-05's
  `RedisConnectionProvider` shape/lifecycle: build once, hand out sessions, close on shutdown) — a FastAPI
  dependency (`get_db_session`) that yields an `AsyncSession` per request from the shared engine's pool (not
  a new engine per request).
- Wire it into `app/main.py`'s lifespan: create the provider at startup (verify connectivity — e.g. a
  `SELECT 1` — replacing the P0 "stubbed" log lines), close/dispose the engine at shutdown.
- Do **not** define any table models yet beyond what's needed to prove the plumbing (e.g. a trivial smoke
  model/table is not needed — a lifespan-time `SELECT 1` is enough proof; real tables land in P2-02/03/04).
- Tests: unit tests using a fake/lightweight approach — SQLAlchemy's async engine can point at an in-memory
  SQLite via `aiosqlite` for a *pure plumbing* test (session yields/closes correctly, pool config applied) if
  that's simpler than requiring a real Postgres in CI; or, if a real Postgres is available via the
  environment/CI (check `.github/workflows/backend-ci.yml` and `docker-compose.yml` first), test against
  that. Document whichever approach you take and why. No new heavy dependency without checking `pyproject.toml`
  first (sqlalchemy/asyncpg/alembic/pgvector are already present).

## Acceptance criteria
- [ ] `app/repositories/postgres.py` exposes a single shared `AsyncEngine`-backed pool (max 5 connections,
      §4) and a `Base` for ORM models — no per-request engine/connection creation anywhere.
- [ ] A FastAPI dependency yields an `AsyncSession` per request from the shared pool.
- [ ] `app/main.py` lifespan creates the provider at startup (verifies connectivity) and disposes it cleanly
      at shutdown — the P0 "stubbed" Postgres log lines are replaced with real wiring.
- [ ] `repositories/redis.py` reviewed and confirmed still consistent with this task's repository-layer intent
      (no rework expected, but call out anything worth fixing).
- [ ] Unit tests pass (documented approach — in-memory SQLite plumbing test or a real Postgres in CI).
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/plan.md: Phase 2 ("Repository layer: `postgres.py`... `redis.py` — services never touch drivers
  directly")
- dev-board/app-design-and-features.md: §4 Data Model & Ownership ("Connection pooling: the
  `repositories/postgres.py` layer maintains a single shared async connection pool... max 5 connections...
  Do not open per-request connections"), §8 Target Project Structure (`repositories/postgres.py`)
- dev-board/code-review/P1-05-session-memory/engineer.md — the `RedisConnectionProvider` shape/lifecycle
  precedent this task's Postgres provider should mirror
- backend/app/config.py — `DATABASE_URL` (already defined)

## Constraints / non-goals
- No table models beyond what's strictly needed to prove connectivity (no `users`/`profiles`/etc. yet —
  those are P2-02/03/04).
- No Alembic setup here (that's the very next task, P2-02) — this task is the SQLAlchemy engine/session
  layer only; Alembic will target the `Base` this task defines.
- Don't touch `repositories/redis.py`'s public interface unless something is genuinely broken — this task
  is additive (Postgres side).
