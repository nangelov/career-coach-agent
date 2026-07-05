"""Postgres repository layer — the single shared async engine/pool + ORM base (§4).

This is the **connection/session foundation** every future Postgres model and
repository sits on. Per design §4: *"the ``repositories/postgres.py`` layer maintains
a single shared async connection pool (SQLAlchemy ``AsyncEngine``) — max 5 connections
— shared across all requests and agents. Do not open per-request connections; acquire
from the pool via the repository layer only."*

Three things live here, all in the **repository** layer so services never touch a
datastore driver directly:

* :class:`Base` — the SQLAlchemy 2.x declarative base that the upcoming ORM models
  (P2-02 users/sessions, P2-03 knowledge/memory, P2-04 dashboard) subclass. Alembic
  (P2-02) targets this ``Base.metadata`` for autogeneration.
* :class:`PostgresConnectionProvider` — owns the one shared
  :class:`~sqlalchemy.ext.asyncio.AsyncEngine` (**max 5 connections**, design §4) and
  its :func:`~sqlalchemy.ext.asyncio.async_sessionmaker`. Built once at the composition
  root (the app lifespan), it hands out :class:`~sqlalchemy.ext.asyncio.AsyncSession`
  objects that all draw from that *one* pool — no ``create_async_engine`` per request.
  Mirrors P1-05's :class:`~app.repositories.redis.RedisConnectionProvider` shape and
  lifecycle (build once → hand out handles → close on shutdown).
* :func:`get_db_session` — the FastAPI dependency that yields an ``AsyncSession`` per
  request from the shared engine's pool and closes it when the request ends.

No table models are defined here beyond :class:`Base` itself — real tables land in
P2-02..04. The engine is created but does not connect until first use;
:meth:`PostgresConnectionProvider.verify_connectivity` (a ``SELECT 1``) is what proves
the pool works at startup.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.app_state import AppStateKeys
from app.config import Settings, settings


class Base(DeclarativeBase):
    """Declarative base for all v2 ORM models (design §4/§8).

    Plain **SQLAlchemy 2.x** :class:`~sqlalchemy.orm.DeclarativeBase` (not SQLModel):
    the design doc allows either ("SQLAlchemy/SQLModel"), and SQLAlchemy is the
    dependency already present. It gives the full mapped-column typing, first-class
    ``pgvector`` column support, and Alembic autogenerate (P2-02) that the upcoming
    knowledge/memory/dashboard tables need. Every P2-02..04 model subclasses this so
    they share one ``metadata`` (the single migration target).
    """


class PostgresConnectionProvider:
    """Owns the single shared SQLAlchemy async engine / connection pool (design §4).

    Build once at the composition root (the app lifespan) and share the same provider
    everywhere that needs Postgres. Sessions handed out by :meth:`session` /
    :meth:`get_db_session` all draw from this **one** engine's pool (max 5 connections),
    which is what enforces the "single shared pool, no per-request connections" rule —
    acquiring a session is cheap; it does not open a new pool.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        # expire_on_commit=False: attributes stay usable after commit without an extra
        # round-trip — the standard async pattern (a lazy refresh would need a live
        # connection the request may already have returned to the pool).
        # autoflush=False: pending writes are NOT auto-flushed before a query runs, so
        # downstream repositories (P2-02..04) must flush explicitly (or commit) when a
        # read must see their own not-yet-flushed writes. Chosen for explicit, predictable
        # transaction control in async code (implicit flushes can trigger surprising I/O
        # mid-query on a pooled connection).
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @classmethod
    def from_settings(cls, config: Settings = settings) -> PostgresConnectionProvider:
        """Create the shared engine from ``DATABASE_URL`` (lazy — no I/O until first use).

        The pool is capped at ``POSTGRES_MAX_CONNECTIONS`` (default 5, §4) via
        ``pool_size`` with ``max_overflow=0`` so the total number of connections can
        never exceed the cap. ``pool_pre_ping`` transparently discards a connection that
        the server dropped (e.g. an idle timeout) before handing it to a request.
        """
        engine = create_async_engine(
            config.DATABASE_URL,
            pool_size=config.POSTGRES_MAX_CONNECTIONS,
            max_overflow=0,
            pool_pre_ping=True,
            echo=config.DEBUG,
        )
        return cls(engine)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield an :class:`AsyncSession` bound to the shared pool, closed on exit.

        The session is closed (its connection returned to the pool) when the context
        exits — success or error. Callers own transaction boundaries (``commit`` /
        ``rollback``); the session rolls back any open transaction on close.
        """
        async with self._session_factory() as session:
            yield session

    async def verify_connectivity(self) -> None:
        """Prove the pool works by acquiring a connection and running ``SELECT 1``.

        Called at startup (fail-fast, §4): if Postgres is unreachable this raises and
        the app does not start with a broken data layer.
        """
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def aclose(self) -> None:
        """Dispose the engine and its pool (closes all pooled connections)."""
        await self._engine.dispose()


def get_db_session_provider(
    app_state_provider: PostgresConnectionProvider | None,
) -> PostgresConnectionProvider:
    """Return the app-scoped provider or raise if the lifespan never built it.

    Separated from :func:`get_db_session` so the "was the lifespan run?" guard is
    unit-testable without a ``Request``.
    """
    if app_state_provider is None:
        raise RuntimeError(
            "Postgres provider is not initialised — the application lifespan "
            "(app.main.lifespan) must run before requests acquire a DB session."
        )
    return app_state_provider


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield an ``AsyncSession`` per request from the shared pool.

    Reads the one :class:`PostgresConnectionProvider` the lifespan stashed on
    ``app.state`` (never a new engine) and yields a session scoped to the request,
    closed when the request finishes. Repositories depend on this session; services and
    routers never touch the engine/driver directly (§4 layering).

    This dependency **never commits**: callers own transaction boundaries and must
    ``session.commit()`` explicitly to persist writes. Any transaction still open when
    the request ends is rolled back as the session closes (a safe no-write default).

    The parameter is annotated as the **bare** :class:`~fastapi.Request` — FastAPI
    auto-injects the raw request only for the bare class; a subscripted alias like
    ``Request[Any]`` would be misread as a body/query field and raise ``FastAPIError``
    at route registration.
    """
    provider = get_db_session_provider(getattr(request.app.state, AppStateKeys.PG_PROVIDER, None))
    async with provider.session() as session:
        yield session
