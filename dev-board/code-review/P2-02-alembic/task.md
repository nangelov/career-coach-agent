# Task P2-02-alembic — Alembic init + migration env
- **Phase:** P2   **Status:** ENG   **Tags:** (I)

## Scope
Wire up **Alembic** against the `Base`/engine foundation P2-01 just built (`app/repositories/postgres.py`),
so P2-03/04/05 can each ship a real migration. This task is infra-only: no new tables yet.

Build:
- `backend/alembic.ini` (or `backend/migrations/alembic.ini` — pick whichever keeps `backend/` as the
  natural working directory for `alembic upgrade head` in CI/dev; document the choice).
- `backend/migrations/env.py` configured for **async** SQLAlchemy (Alembic's async template —
  `run_migrations_online` using `asyncio.run` + `async_engine_from_config`/`create_async_engine`), reading
  `DATABASE_URL` from `app/config.py`'s `Settings` (not a hardcoded URL, not re-parsing `.env` directly —
  reuse the same settings object the app uses) so `alembic` and the app never drift on connection config.
- `target_metadata = Base.metadata` from `app.repositories.postgres` — the same `Base` all future ORM
  models will subclass, so `alembic revision --autogenerate` works once P2-03 adds models.
- Note there's an existing `backend/migrations/init/01_enable_pgvector.sql` (raw SQL run once via
  docker-compose's Postgres init-scripts mount, from P0-07) that enables the `pgvector` extension **before**
  Alembic ever runs. Keep that file and its docker-compose wiring as-is — Alembic migrations should assume
  the extension already exists (do not re-`CREATE EXTENSION` in an Alembic migration; that's already
  handled). Confirm this in `engineer.md` rather than duplicating the extension-creation logic.
- A first, genuinely empty migration (`alembic revision -m "baseline"` with a no-op `upgrade()`/`downgrade()`)
  or, if you prefer, defer the very first migration file to P2-03 and just prove `alembic upgrade head` /
  `alembic downgrade base` work against zero revisions — your call, document which.
- Wire `alembic upgrade head` into whatever startup/dev flow makes sense (e.g. a `Makefile`/script target,
  or a doc note in `backend/README.md` if one exists) — do **not** auto-run migrations inside the FastAPI
  lifespan (keep migrations an explicit, separate step from app startup, standard practice and consistent
  with P2-01's app-owned connection pool being distinct from schema management).
- Tests/verification: this is infra, not app code, so a full pytest unit test isn't the primary signal.
  Instead, verify functionally: spin up Postgres (via `docker-compose.yml`, `pgvector/pgvector:pg16`) and
  run `alembic upgrade head` then `alembic downgrade base` (or `-1`) and confirm both succeed cleanly against
  a real database. If a live Postgres isn't available in this sandboxed environment, document that clearly
  (same posture as prior verify-tasks) and instead prove the `env.py`/`alembic.ini` wiring is at least
  import-clean and config-valid (e.g. `alembic check`/`alembic heads` without a live DB where possible, or a
  SQLite-backed dry run if Alembic's async template tolerates it — document whichever you can actually run).
- `ruff`/`mypy` clean on any new/edited `.py` files (`env.py` counts; Alembic's generated template usually
  needs a couple of touch-ups to satisfy strict mypy — fix don't ignore, unless truly untypeable
  third-party internals, in which case a narrowly-scoped `# type: ignore[code]` with a comment is fine).

## Acceptance criteria
- [ ] `alembic.ini` + `migrations/env.py` (or wherever you place it) use **async** SQLAlchemy and read
      `DATABASE_URL` from the app's `Settings` — no hardcoded/duplicated connection string.
- [ ] `target_metadata` points at the same `Base` from `app/repositories/postgres.py` P2-01 defined.
- [ ] The pre-existing `pgvector` extension init script/docker-compose wiring is left untouched and
      explicitly confirmed compatible (not re-implemented in Alembic).
- [ ] `alembic upgrade head` / `alembic downgrade base` verified — live against real Postgres if available
      in this environment, otherwise clearly documented what could and couldn't be run here.
- [ ] Migrations are **not** auto-run from the FastAPI lifespan — an explicit, separate step.
- [ ] `ruff` + `mypy` clean on new/edited Python files.

## Design references
- dev-board/plan.md: Phase 2 ("Postgres + alembic migrations")
- dev-board/app-design-and-features.md: §4 Data Model & Ownership, §8 Target Project Structure
  (`backend/migrations/`)
- dev-board/code-review/P2-01-repositories/engineer.md — the `Base`/`PostgresConnectionProvider` this
  Alembic env must target; also documents `DATABASE_URL` location in `app/config.py`
- backend/migrations/init/01_enable_pgvector.sql — existing P0-07 raw-SQL extension bootstrap; do not
  duplicate this in an Alembic migration

## Constraints / non-goals
- No table models yet (`users`, `conversations`, etc. — those are P2-03/04/05). This task proves the
  Alembic **plumbing** only; an empty/baseline migration is fine, or no migration file at all if you
  document why.
- Do not touch `docker-compose.yml`'s existing Postgres init-script mount for `01_enable_pgvector.sql`.
- Do not auto-run migrations at FastAPI startup — keep it a separate, explicit command.
