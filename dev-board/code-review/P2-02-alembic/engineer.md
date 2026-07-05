# Engineer report — P2-02-alembic · Revision 1

## Summary
Wired **Alembic** (async SQLAlchemy) to the P2-01 `Base`/engine foundation so P2-03/04/05 can each ship a
real migration. Infra-only — no application tables. New `backend/alembic.ini` + `backend/migrations/env.py`
use the **async template** and read `DATABASE_URL` from the app's `Settings` (single source of truth, never a
hardcoded string), with `target_metadata = Base.metadata` from `app.repositories.postgres`. A genuine no-op
**baseline** migration (`0001`) establishes the revision chain / `alembic_version` table without creating any
tables. Verified end-to-end against the **live Postgres container**: `alembic upgrade head` → `alembic
downgrade base` both succeed; the pre-existing `pgvector` extension is confirmed present and is **not**
touched by Alembic.

## Files changed
- `backend/alembic.ini` — **new.** Placed at `backend/` so `backend/` is the natural cwd for `alembic ...`
  (also where `app` imports from; `prepend_sys_path = .`). `script_location = %(here)s/migrations`. No
  `sqlalchemy.url` — env.py injects it from settings. `file_template` prepends a UTC date for on-disk
  ordering. Keeps the standard logging config.
- `backend/migrations/env.py` — **new.** Async env (`asyncio.run` + `async_engine_from_config` +
  `NullPool`). Imports `settings` and `Base`; `config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)`;
  `target_metadata = Base.metadata`. Keeps offline mode too.
- `backend/migrations/script.py.mako` — **new.** Migration template, modernized for the repo's ruff `UP`
  rules (`str | Sequence[str] | None`, `collections.abc.Sequence`) so future generated files lint cleanly.
- `backend/migrations/versions/20260705_0001_baseline.py` — **new.** No-op baseline (`revision="0001"`,
  `down_revision=None`, empty `upgrade`/`downgrade`). Hand-trimmed of the template's unused `op`/`sa` imports
  so an empty migration is ruff-clean; documents that pgvector is bootstrapped elsewhere.
- `backend/migrations/README` — **new.** Documents layout, the settings-driven URL, the pgvector boundary,
  and the common commands (incl. the compose form).
- `backend/Makefile` — **new.** `migrate` / `migrate-down` / `migrate-base` / `migrate-status` / `revision`
  targets (`uv run alembic ...`) — the explicit dev flow.
- `backend/Dockerfile` — ship `alembic.ini` + `migrations/` into the image so migrations are runnable in the
  deployed container (`docker compose run --rm backend alembic upgrade head`) as an explicit step.
- `.github/workflows/backend-ci.yml` — mypy step now `mypy app/ migrations/` so `env.py` is type-checked in
  CI (ruff already covered it via `ruff check .`). alembic isn't in the curated install → treated as `Any`
  via `ignore_missing_imports` (same posture as langgraph/docling).
- `backend/migrations/.gitkeep` — **removed** (the dir now has real content).

## Key decisions
- **`alembic.ini` at `backend/`, not `backend/migrations/`.** Keeps `backend/` as the single working dir for
  every dev/CI command (that's also where `app/` is importable), matching where tests/ruff/mypy already run
  (design §8 target structure lists `backend/migrations/`).
- **URL from `app.config.Settings`, injected in env.py — no `sqlalchemy.url` in the ini.** env.py does
  `config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)` so Alembic and the app can never drift on
  connection config (task requirement / §4). Consequence: alembic commands need the app's env vars present
  (root `.env` locally, compose/Space Secrets in containers) — documented in the README.
- **`target_metadata = Base.metadata`** from `app.repositories.postgres` (the one base all P2-03/04/05 models
  subclass), so `--autogenerate` works the moment models land.
- **pgvector left entirely to P0-07's init script.** No `CREATE EXTENSION` in any migration. Verified the
  `vector` extension is already present in the live db before/independently of Alembic (see How to verify).
- **A real no-op baseline (`0001`) rather than zero revisions.** Gives a concrete head to build P2-03 onto and
  exercises the full `alembic_version` bookkeeping in verification; the empty bodies add nothing to migrate.
- **No auto-run at startup.** Migrations are only reachable via the Makefile / explicit `alembic` command /
  `docker compose run`. The FastAPI lifespan (P2-01) is untouched — schema management stays distinct from the
  app's runtime pool (task constraint / §4).

## How to verify
From `backend/` with the app env vars set (host DSN pointing at the running db container):
```bash
set -a && . ../.env && set +a
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"

alembic heads            # 0001 (head)
alembic upgrade head     # Running upgrade  -> 0001, baseline ...
alembic current          # 0001 (head)
alembic downgrade base   # Running downgrade 0001 -> , baseline ...
alembic current          # (empty)
```
Lints/types (from `backend/`):
```bash
ruff check .            # All checks passed!
ruff format --check .   # 48 files already formatted
mypy app/ migrations/   # Success: no issues found in 34 source files
pytest -q               # 83 passed
```

**Live-DB verification (actually run here):** a docker-compose stack was already up
(`career-coach-agent-db-1`, pgvector/pgvector:pg16, 5432 published). Results:
- `alembic upgrade head` → applied `0001`; `alembic current` → `0001 (head)`; `SELECT version_num FROM
  alembic_version` → `0001`.
- `SELECT extname FROM pg_extension WHERE extname='vector'` → `vector` present (from the P0-07 init script,
  **not** created by Alembic).
- `alembic downgrade base` → reverted cleanly; `alembic current` → empty. DB left as found.
- `alembic upgrade head --sql` (offline mode) emits only the `alembic_version` DDL + `INSERT` — no
  `CREATE EXTENSION`, confirming Alembic doesn't touch pgvector.

Note: `alembic` is a `pyproject.toml` dependency but wasn't in the partial local `.venv`; installed it
ad-hoc (`uv pip install alembic`) to run the above. It's already resolved for the Docker image via
`uv sync` (main dep, not dev).

## Self-check
- [x] `alembic.ini` + `migrations/env.py` use **async** SQLAlchemy and read `DATABASE_URL` from the app's
  `Settings` — no hardcoded/duplicated connection string.
- [x] `target_metadata` points at the same `Base` from `app/repositories/postgres.py` (P2-01).
- [x] pgvector init script + docker-compose wiring **left untouched**; extension confirmed pre-existing and
  not re-created in any migration.
- [x] `alembic upgrade head` / `alembic downgrade base` verified **live against real Postgres** (output above).
- [x] Migrations **not** auto-run from the FastAPI lifespan — explicit Makefile/`alembic`/compose step only.
- [x] `ruff` + `ruff format` + `mypy --strict` clean on new/edited Python files; 83 tests still pass.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (migration env sits beside the
  repository layer, targets its `Base`; no service/router touched).

## Notes for reviewers
- The `script.py.mako` default imports `sqlalchemy as sa` / `alembic.op`; a **manual** empty `alembic revision`
  (no `--autogenerate`) would leave those unused → ruff F401. Normal path is `--autogenerate` (imports used)
  or trim like I did for the baseline. Documented as a known minor, not worth a noqa in the template.
- CI curated install intentionally still excludes `alembic` (mypy treats it as `Any`); no CI change was made
  to *run* alembic — live-DB verification isn't part of the free-tier CI (same posture as P2-01).
