"""Composition root — assembles the shared, app-scoped :class:`ChatService` (§4/§8).

This is the single place the concrete Redis / Postgres / LLM wiring is put together. It
lives here, deliberately **out of both** the API layer (``api/chat.py`` must stay a thin
router: request/response + SSE only, no repository imports) **and** ``app.main`` (which
owns the ASGI app + lifespan). Keeping composition in one module means P3 (auth needs the
same Redis pool for sessions/rate-limits) and P4 (agents need the router) extend *one*
wiring path rather than each growing its own.

The shared ``redis.asyncio`` connection pool (§4) is owned by a
:class:`~app.repositories.redis.RedisConnectionProvider` stashed on ``app.state`` so the
lifespan can close it on shutdown. The **one** client from that pool is shared by the
router's circuit-breaker, the Redis-backed session memory, and the Redis-backed cancel
registry — no per-request/per-feature ``Redis()`` clients. The Postgres pool is built
eagerly by the lifespan (``app.main``); this reads it from ``app.state`` to build the
durable conversation store.

Wiring is invoked lazily on first request (via ``api.chat.get_chat_service``) rather than
at boot, so a deployment without Redis still serves ``/health`` and starts up; the pool is
opened on the first chat turn.
"""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI

from app.app_state import AppStateKeys
from app.config import settings
from app.repositories.conversation_store import PostgresConversationStore
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.redis import (
    CancelRedis,
    RedisCancelRegistry,
    RedisConnectionProvider,
    RedisSessionMemory,
    SessionRedis,
)
from app.services.chat import ChatService
from app.tools.registry import build_default_registry


def build_chat_service(app: FastAPI) -> ChatService:
    """Construct the default :class:`ChatService` from application settings.

    Builds (and stashes on ``app.state``) the shared Redis pool provider, then wires the
    LLM router, tool registry, session memory, cancel registry, and durable conversation
    store over it. Called once per process (the result is cached by
    :func:`app.api.chat.get_chat_service`).
    """
    from app.llm.router import LLMRouter, RedisLike

    provider = RedisConnectionProvider.from_settings(settings)
    setattr(app.state, AppStateKeys.REDIS_PROVIDER, provider)
    redis_client = provider.client()

    # The one shared client implements the router's ``RedisLike`` seam, the session
    # memory's ``SessionRedis`` seam, and the cancel registry's ``CancelRedis`` seam.
    # redis-py's own method signatures are too loose (``Awaitable[Any] | Any`` returns)
    # to structurally satisfy those strict Protocols under mypy, so cast at this single
    # composition-root boundary.
    llm_router = LLMRouter.from_settings(settings, redis_client=cast("RedisLike", redis_client))
    registry = build_default_registry(settings)
    memory = RedisSessionMemory.from_settings(cast(SessionRedis, redis_client), settings)
    cancel = RedisCancelRegistry.from_settings(cast(CancelRedis, redis_client), settings)

    # Durable conversation store for logged-in users (§4): built over the single shared
    # Postgres pool the lifespan (app.main) created on ``app.state`` — same "acquire from
    # the repository-layer provider, never a per-request engine" rule as Redis. Absent
    # (None) only if the lifespan never ran (e.g. a test that bypasses it), in which case
    # the chat service simply skips durable persistence (guest-equivalent).
    pg_provider: PostgresConnectionProvider | None = getattr(
        app.state, AppStateKeys.PG_PROVIDER, None
    )
    conversations = (
        PostgresConversationStore.from_settings(pg_provider, settings)
        if pg_provider is not None
        else None
    )
    return ChatService(llm_router, registry, memory, cancel, conversations=conversations)
