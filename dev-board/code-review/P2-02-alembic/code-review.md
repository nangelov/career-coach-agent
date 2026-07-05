# Code review — P2-02-alembic · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/migrations/script.py.mako:11-12 | `import sqlalchemy as sa` / `from alembic import op` are imported unconditionally. A manual `alembic revision` (no `--autogenerate`) on an empty change would leave both unused → ruff F401, forcing a hand-trim (as was done for the baseline). | Optional: gate the two imports on `${imports}`/body content, or leave as-is since the normal P2-03/04/05 path is `--autogenerate` (imports used). Already documented by the engineer; no action required. |

## Notes
Independently re-ran every verification from `engineer.md`; all pass on my machine (DB container `career-coach-agent-db-1`, pgvector/pg16, was up):
- `ruff check .` → All checks passed; `ruff format --check .` → 48 files formatted.
- `mypy app/ migrations/` → Success, 34 files (env.py + baseline type-checked under strict).
- `pytest -q` → 83 passed.
- Live cycle: `alembic heads` → `0001 (head)`; `upgrade head` applies `0001`; `current` → `0001 (head)`; `downgrade base` reverts cleanly; `current` → empty. DB left as found.
- `alembic upgrade head --sql` (offline) emits only the `alembic_version` DDL + the `INSERT` — **no `CREATE EXTENSION`**, confirming Alembic never touches pgvector.
- `SELECT extname FROM pg_extension WHERE extname='vector'` → `vector` present (from the P0-07 init script, not Alembic).

Correctness / security spot-checks, all clean:
- **Single source of truth for the DSN.** `env.py` injects `settings.DATABASE_URL` via `config.set_main_option`; `alembic.ini` deliberately omits `sqlalchemy.url` — Alembic and the app cannot drift (acceptance #1). `%%`-escaping in `file_template` and `path_separator = os` / `prepend_sys_path = .` are correct and verified working.
- **Async template** (`asyncio.run` → `async_engine_from_config` + `NullPool` + `run_sync`) matches Alembic's canonical async pattern; offline mode retained (acceptance #1).
- **`target_metadata = Base.metadata`** from `app.repositories.postgres` — the same `Base` P2-01 defined and future models subclass (acceptance #2). Empty until P2-03; expected. (Future note, not this task: P2-03 must import its models into `env.py` for `--autogenerate` to see them — no gap now since there are no models.)
- **pgvector boundary respected** (acceptance #3): init SQL + its compose mount untouched, extension not re-created in any migration — verified via offline SQL and live `pg_extension`.
- **No lifespan auto-run** (acceptance #5): `grep` finds zero `alembic`/`upgrade`/`run_migrations` references in `app/`; migrations reachable only via Makefile / explicit `alembic` / `docker compose run`.
- Dockerfile ships `alembic.ini` + `migrations/` (copies the `init/` subdir too — harmless); CI adds `sqlalchemy asyncpg aiosqlite` to the curated install (needed for `app.main` import) and type-checks `migrations/`. Sensible, no secrets committed.

All six acceptance criteria are met and independently reproduced. Only a documented nit (C1); nothing to gate on.
