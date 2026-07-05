---
name: check-alembic-migration-tasks
description: Checklist for reviewing backend/migrations Alembic tasks (env.py, ini, migration files) in this repo
metadata:
  type: project
---

Reviewing an Alembic migration/plumbing task (P2-02 and later P2-03/04/05 model migrations).

**Why:** these gate on DSN single-source, the pgvector boundary, and real upgrade/downgrade behavior — things a static read can miss. A live pgvector/pg16 docker stack is usually already up here, so re-run the verification instead of trusting the report.

**How to apply — concrete checks:**
- **DSN single source of truth:** `alembic.ini` must NOT set `sqlalchemy.url`; `migrations/env.py` injects it via `config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)` from `app.config`. No hardcoded/duplicated connection string.
- **target_metadata:** must be `Base.metadata` from `app.repositories.postgres` (the one shared declarative Base). For a model migration, confirm the models are actually imported in `env.py` (else `--autogenerate` sees nothing).
- **pgvector boundary:** the `vector` extension is bootstrapped by `backend/migrations/init/01_enable_pgvector.sql` (P0-07), NOT by Alembic. No `CREATE EXTENSION` in any migration. Verify with `alembic upgrade head --sql | grep -i "create extension"` (should be empty) and `SELECT extname FROM pg_extension WHERE extname='vector'`.
- **No lifespan auto-run:** `grep -rn "alembic\|upgrade\|run_migrations" app/` must be empty — migrations are an explicit Makefile/CLI/`docker compose run` step, kept out of the FastAPI lifespan.
- **Live cycle (docker stack usually up):** `cd backend; set -a && . ../.env && set +a; export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"; uv run --no-sync alembic upgrade head && alembic current && alembic downgrade base`. Container is `career-coach-agent-db-1`.
- **Lints/tests:** run from `backend/` with `uv run --no-sync`: `ruff check .`, `ruff format --check .`, `mypy app/ migrations/`, `pytest -q`. CI also type-checks `migrations/`; alembic is treated as `Any` (not in curated install) — that's the accepted posture, not a finding.
- **Known nit (don't over-gate):** `script.py.mako` imports `sqlalchemy as sa` + `alembic.op` unconditionally; a manual (non-autogenerate) empty revision leaves them unused (F401). Normal path is `--autogenerate` (imports used) — nit, not a blocker.
- **Model-migration checks that paid off (P2-05):** re-run the live cycle (`downgrade <prev>` then `upgrade head`, asserting the group's tables drop to 0 then return via `information_schema.tables`) and the autogenerate drift check (new revision's `upgrade()` must have 0 `op.*` calls — delete the file after). Verify FK on-delete rules directly in `pg_constraint` (`confdeltype`: `c`=CASCADE, `n`=SET NULL) rather than trusting the report. CHECK-constraint vocab in the ORM (often built via `repr()` of a module tuple) must match the migration's hand-written `IN (...)` literal exactly. Watch for btree-indexed long varchars (e.g. `source_url String(2048) index=True`) — btree entry cap ~2704 bytes; nit for ASCII, only bites on very long multibyte values.
