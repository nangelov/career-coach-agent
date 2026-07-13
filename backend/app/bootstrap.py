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
from redis.asyncio import Redis

from app.app_state import AppStateKeys
from app.config import settings
from app.repositories.account import PostgresAccountRepository
from app.repositories.conversation_store import PostgresConversationStore
from app.repositories.feedback_store import PostgresFeedbackReader
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.profile_store import PostgresProfileStore
from app.repositories.redis import (
    CancelRedis,
    LimiterRedis,
    RedisCancelRegistry,
    RedisConnectionProvider,
    RedisOAuthStateStore,
    RedisRateLimiter,
    RedisRoleProfileCache,
    RedisSessionMemory,
    RedisSessionStore,
    RedisUpgradeTicketStore,
    SessionRedis,
    StoreRedis,
)
from app.repositories.user_store import PostgresUserStore
from app.security.oidc import AuthlibOIDCClient
from app.security.tokens import SessionTokenCodec
from app.services.account import AccountService
from app.services.auth import GuestAuthService, SessionAuthenticator, SsoAuthService
from app.services.chat import ChatService
from app.services.feedback import FeedbackReader
from app.services.guest_upgrade import GuestUpgradeService
from app.services.jobs import JobStatusService
from app.services.profile_ingest import ProfileIngestService
from app.services.profile_store import ProfileStore
from app.services.rate_limiting import RateLimitService
from app.services.roles import RolesService
from app.services.skills_gap import SkillsGapService
from app.services.user_store import UserStore


def _shared_redis_client(app: FastAPI) -> Redis:
    """Return the single shared Redis client, building the pool provider on first use.

    The :class:`~app.repositories.redis.RedisConnectionProvider` is stashed on ``app.state``
    and **reused** across every composition entry point (chat, auth, …) so the whole process
    shares one bounded pool (§4) — the second builder to run must not create a second pool.
    The lifespan (``app.main``) closes whatever provider is present on shutdown.
    """
    provider: RedisConnectionProvider | None = getattr(app.state, AppStateKeys.REDIS_PROVIDER, None)
    if provider is None:
        provider = RedisConnectionProvider.from_settings(settings)
        setattr(app.state, AppStateKeys.REDIS_PROVIDER, provider)
    return provider.client()


def _require_pg_provider(app: FastAPI, feature: str) -> PostgresConnectionProvider:
    """Return the shared Postgres provider or fail loudly if the lifespan never built it.

    Features that *require* Postgres (SSO user upsert, admin authz, feedback read) cannot
    degrade to Redis-only, so a missing provider is a wiring bug for that endpoint — raise
    rather than silently disable it. The lifespan (``app.main``) builds this eagerly at
    startup, so in a correctly-wired process it is always present.
    """
    provider: PostgresConnectionProvider | None = getattr(app.state, AppStateKeys.PG_PROVIDER, None)
    if provider is None:
        raise RuntimeError(
            f"Postgres provider is not initialised — the application lifespan must run "
            f"before {feature} can be served."
        )
    return provider


def build_user_store(app: FastAPI) -> UserStore:
    """Construct the Postgres-backed :class:`UserStore` (SSO upsert + admin authz, §7.1/§7).

    The one ``users``-table adapter, shared by the SSO login flow (upsert on callback) and
    the ``require_admin`` dependency (``is_admin`` lookup). Requires the shared Postgres pool
    the lifespan built. Called once per process (cached on ``app.state`` by
    ``app.security.dependencies.get_user_store``).
    """
    provider = _require_pg_provider(app, "user store")
    return PostgresUserStore.from_provider(provider)


def build_feedback_reader(app: FastAPI) -> FeedbackReader:
    """Construct the Postgres-backed :class:`FeedbackReader` (admin feedback read, P3-05).

    Backs the admin-only ``GET /api/feedback`` endpoint that replaces v1's
    ``GET /get-feedback?key=<HF_TOKEN>``. Requires the shared Postgres pool. Called once per
    process (cached on ``app.state`` by ``app.api.feedback.get_feedback_reader``).
    """
    provider = _require_pg_provider(app, "feedback read")
    return PostgresFeedbackReader.from_provider(provider)


def build_profile_store(app: FastAPI) -> ProfileStore:
    """Construct the Postgres-backed :class:`ProfileStore` (get/upsert ``profiles``, P5-05).

    Backs ``GET/PUT /api/profile`` — read/edit the structured profile without re-uploading a
    CV (§4/§8). A profile is anchored to a ``users`` row (FK), so this cannot degrade to
    Redis-only: a missing Postgres provider is a wiring bug for these endpoints and
    ``_require_pg_provider`` fails loudly. Called once per process (cached on ``app.state`` by
    ``app.api.profile.get_profile_store``).
    """
    provider = _require_pg_provider(app, "profile store")
    return PostgresProfileStore.from_provider(provider)


def build_account_service(app: FastAPI) -> AccountService:
    """Construct the :class:`AccountService` (GDPR erase/export, SEC-05 / §7.6).

    Wires the Postgres-backed :class:`~app.repositories.account.PostgresAccountRepository` (the
    cascade delete + scoped export over the shared Postgres pool) and the Redis-backed
    :class:`~app.repositories.redis.RedisSessionStore` (revoking the user's live sessions across
    all devices) over the *same* shared Redis pool as the rest of the app. Erasure spans both
    stores, so both are required — a missing Postgres provider is a wiring bug (``_require_pg_
    provider`` fails loudly). Called once per process (cached by
    ``app.api.me.get_account_service``).
    """
    provider = _require_pg_provider(app, "account erasure/export")
    redis_client = _shared_redis_client(app)
    sessions = RedisSessionStore.from_settings(cast(StoreRedis, redis_client), settings)
    repo = PostgresAccountRepository.from_provider(provider)
    return AccountService(repo, sessions)


def build_chat_service(app: FastAPI) -> ChatService:
    """Construct the default :class:`ChatService` from application settings.

    Builds (and stashes on ``app.state``) the shared Redis pool provider, then wires the
    multi-agent graph runner (:class:`~app.agents.graph.GraphTurnStreamer`) — the LLM router
    driving both the planner and the responder, the in-process embedder and shared Postgres
    pool backing the RAG worker — plus the session memory, cancel registry, and durable
    conversation store. Called once per process (cached by
    :func:`app.api.chat.get_chat_service`).
    """
    from app.agents.graph import GraphTurnStreamer
    from app.llm.embeddings import SentenceTransformerEmbeddingClient
    from app.llm.router import LLMRouter, RedisLike
    from app.tools.internet_search import InternetSearchTool

    redis_client = _shared_redis_client(app)

    # The one shared client implements the router's ``RedisLike`` seam, the session
    # memory's ``SessionRedis`` seam, and the cancel registry's ``CancelRedis`` seam.
    # redis-py's own method signatures are too loose (``Awaitable[Any] | Any`` returns)
    # to structurally satisfy those strict Protocols under mypy, so cast at this single
    # composition-root boundary.
    llm_router = LLMRouter.from_settings(settings, redis_client=cast("RedisLike", redis_client))
    memory = RedisSessionMemory.from_settings(cast(SessionRedis, redis_client), settings)
    cancel = RedisCancelRegistry.from_settings(cast(CancelRedis, redis_client), settings)

    # Web Searcher provider (§5.7 / §6.19): the Tavily 3-key pool needs the *same* shared
    # Redis client for its promote-to-primary + per-key circuit-breaker + result cache, so
    # build the settings-configured search tool here (redis-wired) and inject it into the
    # graph rather than letting the web-search node lazily build a redis-less one per call.
    search_tool = InternetSearchTool.from_settings(
        settings, redis_client=cast("RedisLike", redis_client)
    )

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

    # The compiled-once multi-agent graph (design §3): the single failover ``LLMRouter`` drives
    # both the planner (``router=``) and the responder (``responder_router=``); the in-process
    # sentence-transformers embedder (§6 item 3, lazy-loaded on first use) and the shared
    # Postgres pool back the RAG worker's pgvector retrieval; the redis-wired Tavily search tool
    # (built above) backs the web-search worker.
    runner = GraphTurnStreamer(
        responder_router=llm_router,
        router=llm_router,
        embedder=SentenceTransformerEmbeddingClient(),
        db=pg_provider,
        search_tool=search_tool,
    )
    return ChatService(runner, memory, cancel, conversations=conversations)


def build_guest_auth_service(app: FastAPI) -> GuestAuthService:
    """Construct the :class:`GuestAuthService` from application settings (§7.1 / §9).

    Wires the Redis-backed session store (over the *same* shared pool the chat service uses)
    and the backend session-JWT codec. Guests are Redis-only, so no Postgres wiring is
    needed here. Called once per process (cached by ``app.api.auth.get_guest_auth_service``).
    """
    redis_client = _shared_redis_client(app)
    store = RedisSessionStore.from_settings(cast(StoreRedis, redis_client), settings)
    tokens = SessionTokenCodec.from_settings(settings)
    return GuestAuthService.from_settings(store, tokens, settings)


def build_sso_auth_service(app: FastAPI) -> SsoAuthService:
    """Construct the :class:`SsoAuthService` (OIDC login) from application settings (§7.1).

    Wires the Authlib OIDC client, the Redis-backed OAuth-state store and session store
    (over the *same* shared pool as the rest of the app), the Postgres-backed user store
    (over the shared Postgres pool the lifespan built), and the session-JWT codec. Unlike a
    guest, a logged-in user is persisted to Postgres, so this requires the Postgres provider
    to exist — the lifespan builds it eagerly at startup. Called once per process (cached by
    ``app.api.auth.get_sso_auth_service``).
    """
    redis_client = _shared_redis_client(app)
    states = RedisOAuthStateStore.from_settings(cast(StoreRedis, redis_client), settings)
    sessions = RedisSessionStore.from_settings(cast(StoreRedis, redis_client), settings)
    tokens = SessionTokenCodec.from_settings(settings)
    oidc = AuthlibOIDCClient.from_settings(settings)

    # Logged-in users must be persisted (the users/sessions FKs require the row): a missing
    # Postgres provider is a wiring bug for this endpoint (unlike guests, SSO cannot degrade
    # to Redis-only) — ``build_user_store`` fails loudly. The same ``users`` adapter backs
    # admin authz, so both go through one builder.
    users = build_user_store(app)
    upgrades = build_guest_upgrade_service(app)
    return SsoAuthService.from_settings(
        oidc, states, users, sessions, tokens, settings, upgrades=upgrades
    )


def build_guest_upgrade_service(app: FastAPI) -> GuestUpgradeService:
    """Construct the :class:`GuestUpgradeService` (guest→account carry-over) from settings.

    Wires the Redis-backed upgrade-ticket store, session store and session memory (over the
    *same* shared pool as the rest of the app) plus — when the lifespan has built the shared
    Postgres pool — the durable conversation store, so an upgraded guest's prior transcript
    is backfilled into Postgres. The conversation store is optional: without a Postgres
    provider the session still carries over (Redis working memory only), the backfill is just
    skipped. Used both by the ``POST /api/auth/upgrade`` endpoint and by the SSO service's
    callback. Called once per process (cached by ``app.api.auth.get_guest_upgrade_service``).
    """
    redis_client = _shared_redis_client(app)
    tickets = RedisUpgradeTicketStore.from_settings(cast(StoreRedis, redis_client), settings)
    sessions = RedisSessionStore.from_settings(cast(StoreRedis, redis_client), settings)
    memory = RedisSessionMemory.from_settings(cast(SessionRedis, redis_client), settings)

    pg_provider: PostgresConnectionProvider | None = getattr(
        app.state, AppStateKeys.PG_PROVIDER, None
    )
    conversations = (
        PostgresConversationStore.from_settings(pg_provider, settings)
        if pg_provider is not None
        else None
    )
    return GuestUpgradeService.from_settings(tickets, sessions, memory, conversations, settings)


def build_rate_limit_service(app: FastAPI) -> RateLimitService:
    """Construct the :class:`RateLimitService` (guest/user rate limits) from settings (§6.8/§7).

    Wires the Redis-backed fixed-window limiter (over the *same* shared pool as the rest of
    the app) with the guest caps (10 messages + 1 upload per session) and the generous
    per-user window limits sourced from ``app/config.py``. Redis-only — no Postgres wiring is
    needed. Called once per process (cached by ``app.api.chat.get_rate_limit_service``).
    """
    redis_client = _shared_redis_client(app)
    limiter = RedisRateLimiter.from_settings(cast(LimiterRedis, redis_client), settings)
    return RateLimitService.from_settings(limiter, settings)


def build_profile_ingest_service(app: FastAPI) -> ProfileIngestService:
    """Construct the :class:`ProfileIngestService` (CV upload → Celery parse job, §5.1/§5.3).

    Wires the service's narrow enqueue port to the real Celery producer
    (:func:`app.tasks.profile_ingest.enqueue_cv_ingest`) — imported lazily so importing this
    composition root does not pull Celery/ingestion in at API import time, matching
    :func:`build_chat_service`'s deferred-import posture. No Redis/Postgres pool is needed at
    the API layer: the endpoint only validates and enqueues; the worker owns the DB/embedding
    wiring for the parse itself. Called once per process (cached by
    ``app.api.profile.get_profile_ingest_service``); ``app`` is unused but kept for a uniform
    builder signature.
    """
    from app.tasks.profile_ingest import enqueue_cv_ingest

    return ProfileIngestService.from_settings(enqueue_cv_ingest)


def build_job_status_service(app: FastAPI) -> JobStatusService:
    """Construct the :class:`JobStatusService` (poll any async job's progress, §5.3/§8).

    Wires the service's narrow :data:`~app.services.jobs.AsyncResultFactory` port to Celery's
    :class:`~celery.result.AsyncResult` over the shared ``celery_app`` (its result backend is
    Redis). Both are imported lazily so importing this composition root does not pull Celery in
    at API import time (matching :func:`build_profile_ingest_service`). No Redis/Postgres pool
    from ``app.state`` is needed: Celery owns the result-backend connection. Called once per
    process (cached by ``app.api.jobs.get_job_status_service``); ``app`` is unused but kept for a
    uniform builder signature.
    """
    from celery.result import AsyncResult

    from app.services.jobs import AsyncResultLike
    from app.tasks.celery_app import celery_app

    def result_factory(task_id: str) -> AsyncResultLike:
        return AsyncResult(task_id, app=celery_app)

    return JobStatusService(result_factory)


def build_roles_service(app: FastAPI) -> RolesService:
    """Construct the :class:`RolesService` (role requirements + skills gap, P6-07, §5.6/§8).

    Wires the cache-first market read: the Redis-backed
    :class:`~app.repositories.redis.RedisRoleProfileCache` (over the shared pool), the shared
    taxonomy canonicalizer (:func:`app.agents.market_agent.resolve_canonical_role`, closed over the
    shared Postgres pool + in-process embedder), the Celery mine enqueuer
    (:func:`app.tasks.market.enqueue_mine_role`), and the reused P6-05
    :class:`~app.services.skills_gap.SkillsGapService` (profile store + role-profile repo). The
    market corpus is anchored in Postgres, so this requires the shared pool
    (``_require_pg_provider`` fails loudly). Heavy imports (embedder, market agent, Celery) are
    deferred to keep API import light. Called once per process (cached by
    ``app.api.roles.get_roles_service``).
    """
    from app.agents.market_agent import resolve_canonical_role
    from app.llm.embeddings import SentenceTransformerEmbeddingClient
    from app.tasks.market import enqueue_mine_role

    provider = _require_pg_provider(app, "role requirements")
    redis_client = _shared_redis_client(app)
    cache = RedisRoleProfileCache.from_settings(cast(StoreRedis, redis_client), settings)

    # The in-process sentence-transformers embedder is lazy-loaded on first use (same posture as
    # the chat/RAG path); the canonicalizer reads the shared taxonomy corpus over the same pool.
    embedder = SentenceTransformerEmbeddingClient()

    async def resolver(role: str) -> str:
        return await resolve_canonical_role(provider, embedder, role)

    skills_gap = SkillsGapService(build_profile_store(app), provider)
    return RolesService(
        cache=cache,
        resolve_canonical=resolver,
        enqueue_mine=enqueue_mine_role,
        skills_gap=skills_gap,
        db=provider,
        stale_after_seconds=settings.ROLE_PROFILE_STALE_AFTER_SECONDS,
        cache_ttl_seconds=settings.ROLE_REQUIREMENTS_CACHE_TTL_SECONDS,
    )


def build_session_authenticator(app: FastAPI) -> SessionAuthenticator:
    """Construct the :class:`SessionAuthenticator` (verify/logout) from settings (§7.1).

    The reusable auth primitive behind ``require_auth`` and ``POST /api/auth/logout``: the
    session-JWT codec plus the Redis-backed session store (over the shared pool). Works for
    both guest and logged-in sessions — any request bearing a valid, non-revoked token
    resolves to a :class:`~app.schemas.auth.CurrentUser`. Called once per process (cached by
    ``app.api.auth.get_session_authenticator``).
    """
    redis_client = _shared_redis_client(app)
    sessions = RedisSessionStore.from_settings(cast(StoreRedis, redis_client), settings)
    tokens = SessionTokenCodec.from_settings(settings)
    return SessionAuthenticator.from_deps(tokens, sessions)
