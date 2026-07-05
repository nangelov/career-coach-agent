# Developer convenience targets for the Career Coach Agent v2 backend.
# Run from backend/. Migrations are an explicit, separate step from app startup
# (never auto-run in the FastAPI lifespan) — see migrations/README.
#
# `uv run` executes inside the project venv; alembic reads DATABASE_URL from
# app.config.Settings, so the app env vars (root .env) must be present.

.PHONY: migrate migrate-down migrate-base migrate-status revision

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
