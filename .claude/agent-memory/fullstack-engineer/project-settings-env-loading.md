---
name: settings-env-loading
description: app.config.Settings loads .env from CWD (backend/), not repo root; root .env lacks DATABASE_URL — live-DB Makefile targets must source it explicitly
metadata:
  type: project
---

`backend/app/config.py` `Settings` has `model_config = SettingsConfigDict(env_file=".env")`, which resolves
**relative to the process CWD**. Running any alembic/pytest command from `backend/` finds **no** `.env` there
(the credentials file is at the **repo root**), so the required-with-no-default fields (`DATABASE_URL`,
`HF_API_TOKEN`, `JWT_SECRET_KEY`) raise `ValidationError` unless supplied another way. The root `.env` also
does **not** define `DATABASE_URL` — docker-compose builds it from `POSTGRES_USER/PASSWORD/DB`.

**Why:** this made a standalone `make migrate` fail (it never loaded the root .env), so the live-DB workflow
was broken until P2-09.

**How to apply:** any live-DB Makefile/CLI recipe must source the root `.env` and construct the localhost
async DSN itself — see the `LIVE_DB_ENV` var + `migrate-integration` / `test-integration` / the all-in-one
`test-integration-full` target in `backend/Makefile`. Tests get dummy fallbacks via `tests/conftest.py`
(`os.environ.setdefault`), which is why `make test` runs without a DB but the integration suites still skip
(wrong DB/creds → probe fails). See [[project-live-docker-stack]], [[project-local-venv-partial]].
