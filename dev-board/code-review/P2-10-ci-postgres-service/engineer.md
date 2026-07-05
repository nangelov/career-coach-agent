# Engineer report — P2-10-ci-postgres-service · Revision 1

## Summary
Wired a Postgres(+pgvector) service container into the `backend` job of
`.github/workflows/backend-ci.yml` so the ~40 live-DB-gated integration tests
(`test_conversation_store`, `test_identity_models`, `test_knowledge_models`,
`test_p2_exit_verification`, `test_structured_models`, `test_vector_search`)
**execute and pass in CI** instead of skipping. The change is additive: a
`services:` block, a job-level `env:` with the required Settings placeholders +
the localhost `DATABASE_URL`, an "enable pgvector extension" step (mirroring the
docker-compose init script, which CI can't mount), and an `alembic upgrade head`
migration step before pytest. The curated-install boundary is preserved — no
`uv sync` / heavy ML stack added; only light `alembic` was appended to the
curated pip list so migrations can run via `--no-sync`.

## Files changed
- `.github/workflows/backend-ci.yml` —
  - job-level `env:` with non-secret placeholders `HF_API_TOKEN` / `JWT_SECRET_KEY`
    (required by `app.config.Settings`, which both alembic's `env.py` and pytest
    instantiate) and `DATABASE_URL` pointing at `localhost:5432` (the service is
    port-mapped onto the runner host; the compose `db` hostname is not valid here).
  - `services.postgres` using `pgvector/pgvector:pg16` (same image as
    docker-compose `db`), with `pg_isready` health check via `options:` so the job
    waits for readiness — no manual sleeps.
  - `alembic` added to the curated `uv pip install` list (light: pure-Python,
    SQLAlchemy/Mako only) so the migration step runs in the curated venv via
    `--no-sync` without triggering a full project sync.
  - `Enable pgvector extension` step: feeds the exact
    `migrations/init/01_enable_pgvector.sql` to the service's own `psql` via
    `docker exec -i "${{ job.services.postgres.id }}"` (no host-psql assumption).
  - `Run migrations (alembic upgrade head)` step before the pytest step.
  - Explanatory comments for each new piece, matching the file's existing
    documentation standard.
- `backend/Makefile` — added `alembic` to the `install` target's curated pip list
  to keep `make install` producing the same venv as CI (the file already documents
  that `install` "prepare[s] the curated venv CI uses").

## Key decisions
- **Extension enable via `docker exec` + the checked-out init script, not a
  migration change.** The P0-07 design deliberately keeps `CREATE EXTENSION vector`
  in `migrations/init/01_enable_pgvector.sql` (run by the container entrypoint),
  and migration `0001` explicitly documents that it does *not* create the extension.
  GitHub Actions service containers start before checkout, so the init dir can't be
  mounted; I reuse the *same* SQL file against the service's own psql instead of
  duplicating the DDL or moving it into a migration (DRY + preserves the locked
  design boundary). Ref: `docker-compose.yml` `db` service, `migrations/env.py`.
- **`localhost`, not `db`.** Per the task and GitHub Actions service-container
  networking, the DB is reachable on the runner host via the port map, so
  `DATABASE_URL` uses `localhost:5432`. Mirrors the `LIVE_DB_ENV` localhost-DSN
  convention established in `backend/Makefile` (P2-09) — same shape, CI-appropriate host.
- **Job-level `env:` for the three required Settings fields.** DRY: one definition
  the extension/migration/pytest steps all inherit. `HF_API_TOKEN`/`JWT_SECRET_KEY`
  are non-secret throwaways (unused by these tests, but `Settings()` raises without
  them); the DB dies with the runner.
- **`alembic` added to the curated install (both CI and Makefile), not a full sync.**
  Keeps the free-tier / no-heavy-ML curated boundary intact while letting
  `uv run --no-sync alembic upgrade head` work. Kept the two install lists in sync.
- **Health check via `options:`** so the job blocks until Postgres accepts
  connections — reasonable startup wait, no `sleep`/retry hacks (task constraint).

## How to verify
CI (once pushed): the `backend` job's pytest step reports **142 passed, 0 skipped**
(was 102 passed, 40 skipped), and the "Enable pgvector extension" + "Run migrations"
steps appear before "Test (pytest)".

Local equivalents:
- `cd backend && make check` → lint + format-check + mypy --strict + `make test`
  (no live DB: 102 passed, 40 skipped — unchanged baseline behavior).
- `cd backend && make test-integration-full` → brings up the compose Postgres,
  migrates, runs the whole suite (142 passed), tears down.

## Tests (final step — mandatory)
Because a real GitHub Actions run can't be triggered from here, I reproduced the CI
job's environment as faithfully as possible and ran the exact CI command sequence.

**1. Fresh service container, no init mount** (proves the CI extension step works
where the compose init-script mount is unavailable):
```
docker run -d --name ci-validate-pg -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=career_coach_test \
  -p 5433:5432 pgvector/pgvector:pg16
# vector extension BEFORE: (empty)
docker exec -i ci-validate-pg psql -U postgres -d career_coach_test \
  < migrations/init/01_enable_pgvector.sql        # -> CREATE EXTENSION
# vector extension AFTER:  vector
```

**2. Exact curated venv** (isolated in scratchpad so the local `.venv` was
untouched) built from the CI install list incl. the newly-added `alembic`:
`uv sync --only-group dev` + `uv pip install fastapi pydantic pydantic-settings
"celery[redis]" openai sqlalchemy asyncpg aiosqlite pgvector alembic`. Confirmed
`alembic 1.18.5` and `pytest` importable/runnable in that venv.

**3. CI command sequence** against the fresh container (`DATABASE_URL=...@localhost:5433/...`,
`HF_API_TOKEN`/`JWT_SECRET_KEY` placeholders):
```
uv run --no-sync alembic upgrade head     # 0001 -> 0002 -> 0003 -> 0004, ok
uv run --no-sync pytest                    # 142 passed in 5.02s  (0 skipped)
```
And the 6 previously-skipping modules in isolation: **40 passed** (was 40 skipped).

**4. Standard local gate** on the project venv:
```
make check   # ruff check + ruff format --check + mypy --strict + pytest
             # -> 102 passed, 40 skipped  (unchanged no-live-DB baseline)
```

**5. Workflow YAML** validated with `yaml.safe_load` → valid.

Cleaned up the throwaway container afterward.

### Before / after (affected modules)
| module | before (CI) | after (CI, reproduced) |
|--------|-------------|------------------------|
| test_conversation_store | skip (4) | 4 passed |
| test_identity_models | skip (6) | 6 passed |
| test_knowledge_models | skip (9) | 9 passed |
| test_p2_exit_verification | skip (5) | 5 passed |
| test_structured_models | skip (10) | 10 passed |
| test_vector_search | skip (6) | 6 passed |
| **suite total** | **102 passed, 40 skipped** | **142 passed, 0 skipped** |

No failures to root-cause — all previously-skipped tests passed on first execution
against the CI-equivalent Postgres.

## Self-check
- [x] Meets acceptance criteria: service container wired in; migrations run before
      tests; `DATABASE_URL` exported at `localhost`; the 40 tests execute and pass;
      lint/format/mypy steps unaffected; before/after counts documented.
- [x] No secrets committed (CI env values are non-secret throwaways; real secrets
      stay in env / Space Secrets). Layering unaffected (CI/infra-only change).
- [x] Tests/lints pass — see Tests section (`make check` green; CI-equivalent run
      142 passed, 0 skipped).
- [x] Curated-install boundary preserved (no `uv sync` / heavy ML stack; only light
      `alembic` added, kept in sync between CI and Makefile).
