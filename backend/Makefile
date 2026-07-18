# Developer convenience targets for the Career Coach Agent v2 backend.
# Run from backend/. Migrations are an explicit, separate step from app startup
# (never auto-run in the FastAPI lifespan) — see migrations/README.
#
# `uv run` executes inside the *project* venv (backend/.venv) and IGNORES a
# mismatched VIRTUAL_ENV in your shell — so `make test` is safe even if the
# repo-root .venv is active. Running a bare `pytest` from your shell can silently
# pick the wrong venv (missing sqlalchemy/openai/pytest_asyncio → collection
# errors); always go through these targets or `uv run`.
#
# One-time setup:  make install
# Full local gate (mirrors .github/workflows/backend-ci.yml):  make check
# alembic reads DATABASE_URL from app.config.Settings, so the app env vars
# (root .env) must be present for the migrate-* targets.

.PHONY: install lint format format-check typecheck test test-integration \
        test-integration-full check \
        migrate migrate-integration migrate-down migrate-base migrate-status revision

# ---------------------------------------------------------------------------
# Shared helpers for the live-DB (docker-compose Postgres) workflow.
#
# The compose file + the credentials .env both live at the repo root, one level
# up from backend/. `docker compose -f ../docker-compose.yml` therefore uses the
# repo root as its project directory, so it reads the root `.env` for variable
# interpolation exactly like running compose from the repo root does.
COMPOSE = docker compose -f ../docker-compose.yml

# The default compose file no longer publishes the `db` host port (port lockdown,
# design §7.2). The live-DB targets below run pytest/alembic *on the host* against
# localhost:5432, so they must bring the DB up with the opt-in dev-ports override
# that re-publishes it. DRY: reuse this for every recipe that needs the host port.
COMPOSE_PORTS = docker compose -f ../docker-compose.yml -f ../docker-compose.dev-ports.yml

# Shell prefix that loads the root `.env` and exports a *localhost* async DSN so
# every live-DB recipe (migrate + pytest) talks to the docker-compose Postgres
# published on :5432 (requires the DB to be up via COMPOSE_PORTS — see above).
# app.config.Settings loads its `.env` relative to the CWD (backend/), which has
# no .env — so the required fields (DATABASE_URL, HF_API_TOKEN, JWT_SECRET_KEY)
# must come from the exported root .env here.
# DRY: one definition, reused by migrate-integration and test-integration.
LIVE_DB_ENV = set -a && . ../.env && set +a && \
	export DATABASE_URL="postgresql+asyncpg://$$POSTGRES_USER:$$POSTGRES_PASSWORD@localhost:5432/$$POSTGRES_DB" &&

# ---------------------------------------------------------------------------
# Lint / type-check / test — same commands and curated install as backend CI.
# The curated install deliberately skips the heavy ML stack (torch via
# sentence-transformers, docling) that lint/type-check/these tests never
# exercise; see the CI workflow comments. `--no-sync` then runs the tools in
# this prepared venv without uv re-dragging the full dependency tree.
# ---------------------------------------------------------------------------

# One-time (or after dependency changes): prepare the curated venv CI uses.
install:
	uv sync --only-group dev
	uv pip install fastapi pydantic pydantic-settings "celery[redis]" openai \
		sqlalchemy asyncpg aiosqlite pgvector alembic joserfc authlib langgraph \
		python-multipart reportlab

lint:
	uv run --no-sync ruff check .

format:
	uv run --no-sync ruff format .

format-check:
	uv run --no-sync ruff format --check .

typecheck:
	uv run --no-sync mypy app/ migrations/

# Unit tests + live-DB integration tests. Without a reachable Postgres at
# DATABASE_URL the integration suites skip cleanly (same as CI) — run
# `make test-integration` to exercise them against the docker-compose Postgres.
test:
	uv run --no-sync pytest

# Run the full suite against the docker-compose Postgres. The compose stack must
# be up (with the DB host port published) and migrated first
# (`$(COMPOSE_PORTS) up -d --wait db && make migrate-integration`), or just use
# the all-in-one `test-integration-full` below. Builds the async DSN
# from the root .env so the live-DB integration suites actually execute instead
# of skipping. Leaves the DB as found (rolled-back / cleaned-up tests).
test-integration:
	$(LIVE_DB_ENV) uv run --no-sync pytest

# All-in-one, self-contained live-DB verification (P2 exit criteria). Brings up
# the Postgres(+pgvector) container *with its host port published* (dev-ports
# override — the default compose file keeps it internal-only per §7.2), applies
# migrations, runs the WHOLE suite so the live-DB integration tests execute (not
# skip), then tears the container back down. Reproducible from a clean checkout:
#   cd backend && make test-integration-full
# `up --wait db` blocks until the healthcheck passes; `down` removes the compose
# containers (named volumes, incl. postgres_data, are preserved). If pytest
# fails, make stops before `down` so the DB stays up for debugging — re-run, or
# tear down manually with `$(COMPOSE) down`.
test-integration-full:
	$(COMPOSE_PORTS) up -d --wait db
	$(MAKE) migrate-integration
	$(MAKE) test-integration
	$(COMPOSE) down

# The full local gate — everything CI runs, in one command.
check: lint format-check typecheck test

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

# Apply all pending migrations. Requires DATABASE_URL (+ the other required
# Settings fields) in the environment — e.g. exported in your shell, or a
# backend/.env. For the docker-compose Postgres, prefer `make migrate-integration`
# (or the all-in-one `make test-integration-full`), which loads the root .env for
# you.
migrate:
	uv run alembic upgrade head

# Apply all pending migrations against the docker-compose Postgres, loading the
# root .env and building the localhost DSN just like `test-integration`.
migrate-integration:
	$(LIVE_DB_ENV) uv run alembic upgrade head

# Revert the most recent migration.
migrate-down:
	uv run alembic downgrade -1

# Revert every migration (down to an empty schema).
migrate-base:
	uv run alembic downgrade base

# Show the currently-applied revision.
migrate-status:
	uv run alembic current

# Autogenerate a new migration from the ORM models: make revision m="add users".
revision:
	uv run alembic revision --autogenerate -m "$(m)"
