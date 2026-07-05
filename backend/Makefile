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

.PHONY: install lint format format-check typecheck test test-integration check \
        migrate migrate-down migrate-base migrate-status revision

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
		sqlalchemy asyncpg aiosqlite pgvector

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

# Run the full suite against the docker-compose Postgres (compose stack must be
# up and migrated: `docker compose up -d db && make migrate`). Builds the async
# DSN from the root .env so the live-DB integration suites actually execute
# instead of skipping. Leaves the DB as found (rolled-back / cleaned-up tests).
test-integration:
	set -a && . ../.env && set +a && \
	DATABASE_URL="postgresql+asyncpg://$$POSTGRES_USER:$$POSTGRES_PASSWORD@localhost:5432/$$POSTGRES_DB" \
	uv run --no-sync pytest

# The full local gate — everything CI runs, in one command.
check: lint format-check typecheck test

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

# Apply all pending migrations.
migrate:
	uv run alembic upgrade head

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
