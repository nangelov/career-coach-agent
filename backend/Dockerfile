# Backend image — FastAPI (uvicorn) and the Celery worker share this image.
# Production-style: install deps with uv into a venv, copy source, run uvicorn.
# The Celery worker reuses the same image and overrides the command in
# docker-compose.yml (see the `worker` service).
FROM python:3.11-slim

# uv: fast, reproducible Python dependency manager (pyproject-driven, P0-02).
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

WORKDIR /app

# uv tuning: compile bytecode for faster cold starts; copy (not symlink) so the
# installed venv survives across build layers.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Resolve and install runtime deps first (cached unless pyproject changes).
# --no-install-project: this is an application (package = false, P0-02), so we
# install only the dependency tree, not the project itself.
# --no-dev: exclude the dev dependency group (pytest/ruff/mypy) from the image.
COPY pyproject.toml ./
RUN uv sync --no-install-project --no-dev

# Application source.
COPY app ./app

# Alembic migration environment + config. Shipped so migrations can be applied
# against the deployed database as an explicit, separate step, e.g.
#   docker compose run --rm backend alembic upgrade head
# Migrations are intentionally NOT auto-run at app startup (they are schema
# management, distinct from the app's runtime connection pool — see app.main).
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000

# Default command: the FastAPI ASGI app. The worker service overrides this.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
