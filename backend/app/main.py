"""FastAPI application factory, middleware, lifespan, and health check.

This module owns the ASGI entry point.  Real DB/Redis connection pools are wired
in P2; the lifespan here only structures the startup/shutdown sequence with logging
stubs.  Auth, agents, tools, and the full router set arrive in later phases (P3+).

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

from .api.chat import router as chat_router
from .config import settings

logger = logging.getLogger(__name__)

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

    Startup initialises shared resources (DB pool, Redis) and shutdown closes
    them cleanly.  Real pools land in P2 — for now these are structured logging
    stubs so the wiring/order is correct and observable.
    """
    # --- startup -----------------------------------------------------------
    logger.info("Starting %s v%s (debug=%s)", app.title, APP_VERSION, settings.DEBUG)
    # P2: initialise the async Postgres (asyncpg/SQLAlchemy) connection pool here.
    logger.info("Postgres connection pool init — stubbed (implemented in P2)")
    # P2: create the Redis client and PING to verify connectivity here.
    logger.info("Redis connection/ping — stubbed (implemented in P2)")

    yield

    # --- shutdown ----------------------------------------------------------
    # Close the lazily-built chat service (and its LLM router / clients) if the
    # first request ever constructed one. P2 will move this to shared-pool teardown.
    chat_service = getattr(app.state, "chat_service", None)
    if chat_service is not None:
        try:
            await chat_service.aclose()
        except Exception:  # noqa: BLE001 - best-effort cleanup must not mask shutdown
            logger.warning("chat service close failed", exc_info=True)
    # P2: dispose the Postgres pool here.
    logger.info("Postgres connection pool close — stubbed (implemented in P2)")
    # Close the shared redis.asyncio pool (§4) if a request ever built the chat
    # service (which owns the RedisConnectionProvider). P2 makes this the canonical
    # shared-pool teardown for all Redis consumers.
    redis_provider = getattr(app.state, "redis_provider", None)
    if redis_provider is not None:
        try:
            await redis_provider.aclose()
        except Exception:  # noqa: BLE001 - best-effort cleanup must not mask shutdown
            logger.warning("redis pool close failed", exc_info=True)
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

    # Feature routers (auth, profile, pdp, … arrive in later phases).
    app.include_router(chat_router)

    return app


#: Module-level ASGI target: ``uvicorn app.main:app`` / ``uvicorn backend.app.main:app``.
app = create_app()
