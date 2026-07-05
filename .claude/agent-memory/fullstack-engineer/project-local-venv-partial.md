---
name: local-venv-partial
description: backend/.venv on this host now has the DB + tooling deps (sqlalchemy/asyncpg/ruff/mypy/pytest) — run checks on the host; the docker backend image is STALE and not source-mounted
metadata:
  type: project
---

As of P2-07 (2026-07-05) the local `backend/.venv` **does** contain the deps needed for
backend verification: `sqlalchemy` (2.0.x), `asyncpg`, `ruff`, `mypy`, `pytest`,
`pytest_asyncio`, plus fastapi/redis/pydantic. It may still lack the heavy ML stack
(torch/sentence-transformers) per [[uv-ci-heavy-deps]], but for chat/repo/DB tasks the host
venv is sufficient — prefer it over the container.

**The docker `career-coach-agent-backend-1` image is STALE and source is NOT mounted**: it
was built from an early commit (e.g. `app/services/` had only `__init__.py`) and has no
`python`/`ruff`/`mypy`/`pytest` on PATH (tools live under `/app/.venv/bin`). Do **not** try
to run current-tree tests inside it — your new files won't be there.

**How to apply:** run verification on the host venv:
`cd backend && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ && .venv/bin/python -m pytest -q`.
For live-Postgres integration tests, the db container publishes 5432, so build a host DSN and
run against it:
`set -a && . ./.env && set +a && export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"`
(migration 0002 is already applied there). CI only type-checks `app/ migrations/` (not
`tests/`), but keep tests mypy-clean anyway — reviewers run mypy on them.
