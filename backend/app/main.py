"""FastAPI application factory, middleware, lifespan, and health check.

This module owns the ASGI entry point.  The lifespan builds the shared Postgres pool
eagerly (fail-fast) and closes all shared resources (Postgres pool, Redis pool, chat
service) on shutdown; the concrete service composition lives in ``app.bootstrap``.
Auth, agents, and the full router set arrive in later phases (P3+).

Run with either invocation (the relative import below makes both work):

    uvicorn app.main:app            # from the backend/ directory
    uvicorn backend.app.main:app    # from the repo root
"""

from __future__ import annotations

import importlib.metadata
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .api.auth import router as auth_router
from .api.chat import router as chat_router
from .api.dashboard import router as dashboard_router
from .api.feedback import router as feedback_router
from .api.jobs import router as jobs_router
from .api.me import router as me_router
from .api.pdp import router as pdp_router
from .api.profile import router as profile_router
from .api.roles import router as roles_router
from .app_state import AppStateKeys
from .config import settings
from .repositories.postgres import PostgresConnectionProvider

logger = logging.getLogger(__name__)


async def _best_effort_aclose(obj: Any, label: str) -> None:
    """Close a shared resource on shutdown, logging (never raising) on failure.

    Shutdown cleanup must never mask the shutdown itself, so a close failure is swallowed
    with a warning rather than propagated. A ``None`` object (the resource was never built)
    is a no-op.
    """
    if obj is None:
        return
    try:
        await obj.aclose()
    except Exception:  # noqa: BLE001 - best-effort cleanup must not mask shutdown
        logger.warning("%s close failed", label, exc_info=True)


#: Header used to correlate a single request across logs and responses.
REQUEST_ID_HEADER = "X-Request-ID"

try:
    #: Application version — single-sourced from the installed package metadata
    #: (pyproject.toml ``version``), with a fallback for non-installed runs.
    APP_VERSION = importlib.metadata.version("career-coach-agent")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev/non-installed runs
    APP_VERSION = "2.0.0"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request id to every request/response.

    Reuses an incoming ``X-Request-ID`` header when present (e.g. set by an
    upstream proxy) so a single id can be traced end-to-end; otherwise mints a
    fresh UUID.  The id is exposed on ``request.state.request_id`` for downstream
    handlers/loggers and echoed back on the response header.
    """

    async def dispatch(self, request: Request[Any], call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup then shutdown.

    Startup initialises shared resources and shutdown closes them cleanly.  The single
    shared Postgres async engine/pool (§4) is built and connectivity-checked here; the
    shared Redis pool is built lazily by the composition root (``app.bootstrap``) on the
    first chat request and closed below.
    """
    # --- startup -----------------------------------------------------------
    logger.info("Starting %s v%s (debug=%s)", app.title, APP_VERSION, settings.DEBUG)
    # Build the one shared Postgres async engine/pool (§4) and verify connectivity
    # (SELECT 1) — fail fast if the data layer is unreachable rather than serving with
    # a broken DB. All requests/agents acquire sessions from this provider.
    pg_provider = PostgresConnectionProvider.from_settings(settings)
    setattr(app.state, AppStateKeys.PG_PROVIDER, pg_provider)
    await pg_provider.verify_connectivity()
    logger.info(
        "Postgres connection pool ready (max %d, SELECT 1 ok)",
        settings.POSTGRES_MAX_CONNECTIONS,
    )
    # Redis: the shared redis.asyncio pool is built lazily by app.bootstrap on the
    # first chat request and closed on shutdown below.
    logger.info("Redis connection pool — built lazily on first request (app.bootstrap)")

    yield

    # --- shutdown ----------------------------------------------------------
    # Close every shared resource best-effort (order: service → Postgres → Redis). Each is
    # absent (None) if it was never built (e.g. no chat request ever ran); the helper skips
    # those and never lets a close failure mask the shutdown.
    await _best_effort_aclose(getattr(app.state, AppStateKeys.CHAT_SERVICE, None), "chat service")
    await _best_effort_aclose(getattr(app.state, AppStateKeys.PG_PROVIDER, None), "postgres pool")
    await _best_effort_aclose(getattr(app.state, AppStateKeys.REDIS_PROVIDER, None), "redis pool")
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Factory pattern keeps construction explicit and testable (tests can build an
    isolated app instance), while the module-level ``app`` below is the ASGI
    target used by uvicorn.
    """
    app = FastAPI(
        title="Career Coach Agent",
        version=APP_VERSION,
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    # CORS — origins sourced from settings (never hard-coded), so the allowed
    # Next.js frontend origins are environment-configurable.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Compress larger responses (SSE streams are excluded by content type).
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    # Request-id correlation for logs/responses.
    app.add_middleware(RequestIDMiddleware)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Liveness/readiness probe — cheap, no external dependencies."""
        return {"status": "ok", "version": APP_VERSION}

    # Feature routers (pdp, dashboard, … arrive in later phases).
    app.include_router(chat_router)
    app.include_router(auth_router)
    app.include_router(feedback_router)
    app.include_router(profile_router)
    app.include_router(jobs_router)
    app.include_router(me_router)
    app.include_router(roles_router)
    app.include_router(pdp_router)
    app.include_router(dashboard_router)

    return app


#: Module-level ASGI target: ``uvicorn app.main:app`` / ``uvicorn backend.app.main:app``.
app = create_app()
