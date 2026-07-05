"""Unit tests for the Postgres repository foundation (P2-01).

These are **pure plumbing** tests: they exercise the shared-engine / session
lifecycle and the pool configuration without requiring a live Postgres in CI.

Two engines are used:

* An in-memory **SQLite via aiosqlite** engine (``sqlite+aiosqlite:///:memory:``) for
  the behavioural tests — ``verify_connectivity`` (``SELECT 1``), session yield/close,
  and the ``get_db_session`` dependency. SQLite exercises the exact SQLAlchemy async
  session/engine machinery the app uses, with no network or driver install.
* A non-connecting **postgresql+asyncpg** engine for the pool-config assertions: the
  engine object and its pool are built without opening a connection, so we can assert
  the "max 5 connections" cap (``pool_size`` / ``max_overflow``) from design §4 is
  actually applied to the real production dialect.

Why not a real Postgres: the design's pool cap is dialect-agnostic engine config, and
the session lifecycle is identical across dialects — SQLite proves the plumbing without
adding a Postgres service to the free-tier CI. A real-Postgres integration test lands
naturally once P2-02..04 add tables/migrations.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.repositories.postgres import (
    Base,
    PostgresConnectionProvider,
    get_db_session,
    get_db_session_provider,
)

SQLITE_URL = "sqlite+aiosqlite:///:memory:"
PG_URL = "postgresql+asyncpg://user:pw@localhost:5432/career_coach"


def _sqlite_provider() -> PostgresConnectionProvider:
    """A provider over an in-memory SQLite async engine (real session machinery)."""
    return PostgresConnectionProvider(create_async_engine(SQLITE_URL))


# --------------------------------------------------------------------------- #
# Base
# --------------------------------------------------------------------------- #
def test_base_is_declarative_base_with_shared_metadata() -> None:
    """``Base`` exposes the single ``metadata`` all models/migrations target."""
    from sqlalchemy.orm import DeclarativeBase

    # Importing the models registers their tables on the shared ``Base.metadata`` —
    # this is the one metadata Alembic autogenerates from (P2-03 landed the first group).
    import app.repositories.models  # noqa: F401

    assert issubclass(Base, DeclarativeBase)
    assert Base.metadata is not None
    # The P2-03 identity/docs group is now registered on the shared metadata.
    assert {"users", "sessions", "messages", "message_feedback"} <= set(Base.metadata.tables)


# --------------------------------------------------------------------------- #
# verify_connectivity — SELECT 1
# --------------------------------------------------------------------------- #
async def test_verify_connectivity_runs_select_1() -> None:
    provider = _sqlite_provider()
    try:
        await provider.verify_connectivity()  # must not raise
    finally:
        await provider.aclose()


async def test_verify_connectivity_raises_on_bad_url() -> None:
    """An unreachable DB surfaces as an error at connectivity check (fail-fast, §4)."""
    provider = PostgresConnectionProvider(
        create_async_engine("postgresql+asyncpg://user:pw@127.0.0.1:1/nope")
    )
    try:
        with pytest.raises(Exception):
            await provider.verify_connectivity()
    finally:
        await provider.aclose()


# --------------------------------------------------------------------------- #
# session lifecycle — yields a live session, closed on exit, from the one engine
# --------------------------------------------------------------------------- #
async def test_session_yields_working_session_bound_to_shared_engine() -> None:
    provider = _sqlite_provider()
    try:
        async with provider.session() as session:
            assert isinstance(session, AsyncSession)
            # Bound to the provider's one engine (not a fresh engine per session).
            assert session.bind is provider.engine
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
        # After the context exits the session is closed (no open transaction).
        assert not session.in_transaction()
    finally:
        await provider.aclose()


async def test_multiple_sessions_share_one_engine() -> None:
    provider = _sqlite_provider()
    try:
        async with provider.session() as s1, provider.session() as s2:
            assert s1 is not s2
            assert s1.bind is provider.engine
            assert s2.bind is provider.engine
    finally:
        await provider.aclose()


# --------------------------------------------------------------------------- #
# pool configuration — max 5 connections (§4) on the real Postgres dialect
# --------------------------------------------------------------------------- #
def test_from_settings_applies_pool_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """``from_settings`` caps the pool at POSTGRES_MAX_CONNECTIONS with no overflow."""
    monkeypatch.setattr(settings, "DATABASE_URL", PG_URL)
    monkeypatch.setattr(settings, "POSTGRES_MAX_CONNECTIONS", 5)
    provider = PostgresConnectionProvider.from_settings(settings)
    pool = provider.engine.pool
    # pool_size == cap and max_overflow == 0 → total connections never exceed the cap.
    assert pool.size() == 5  # type: ignore[attr-defined]
    assert provider.engine.pool._max_overflow == 0  # type: ignore[attr-defined]


def test_from_settings_respects_custom_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DATABASE_URL", PG_URL)
    monkeypatch.setattr(settings, "POSTGRES_MAX_CONNECTIONS", 3)
    provider = PostgresConnectionProvider.from_settings(settings)
    assert provider.engine.pool.size() == 3  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# get_db_session dependency
# --------------------------------------------------------------------------- #
async def test_get_db_session_yields_from_app_provider() -> None:
    """The dependency draws a session from the provider stashed on ``app.state``."""
    provider = _sqlite_provider()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pg_provider=provider)))
    try:
        agen = get_db_session(request)  # type: ignore[arg-type]
        session = await agen.__anext__()
        assert isinstance(session, AsyncSession)
        assert session.bind is provider.engine
        # Exhaust the generator so the session's context manager closes it.
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()
        assert not session.in_transaction()
    finally:
        await provider.aclose()


async def test_get_db_session_wired_via_fastapi_depends() -> None:
    """Register ``get_db_session`` through FastAPI ``Depends`` and hit a real route.

    This exercises the actual dependency-injection path (route registration analyses the
    parameter annotation; a real request drives the yield/close). It is the regression
    guard for a subscripted-``Request`` annotation, which registers fine as bare
    ``Request`` but raises ``FastAPIError`` at route-add time as ``Request[Any]``.
    """
    test_app = FastAPI()

    @test_app.get("/db-check")
    async def db_check(session: AsyncSession = Depends(get_db_session)) -> dict[str, int]:
        # Prove the injected object is a live session drawn from the shared pool.
        result = await session.execute(text("SELECT 1"))
        return {"value": result.scalar_one()}

    provider = _sqlite_provider()
    test_app.state.pg_provider = provider
    try:
        transport = ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/db-check")
        assert response.status_code == 200
        assert response.json() == {"value": 1}
    finally:
        await provider.aclose()


async def test_get_db_session_depends_raises_when_uninitialised() -> None:
    """Through DI, a missing provider surfaces the explicit RuntimeError (not silent)."""
    test_app = FastAPI()

    @test_app.get("/db-check")
    async def db_check(session: AsyncSession = Depends(get_db_session)) -> dict[str, str]:
        return {"ok": "yes"}  # pragma: no cover - dependency raises before this runs

    # No provider stashed on app.state → the guard must fire.
    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(RuntimeError, match="not initialised"):
            await client.get("/db-check")


def test_get_db_session_provider_raises_when_uninitialised() -> None:
    """A guard makes the "lifespan never ran" failure explicit, not an AttributeError."""
    with pytest.raises(RuntimeError, match="not initialised"):
        get_db_session_provider(None)


def test_get_db_session_provider_returns_provider() -> None:
    # The accessor is a pure pass-through guard; any non-None provider is returned as-is
    # (no engine created here, so no async cleanup needed).
    sentinel: Any = object()
    assert get_db_session_provider(sentinel) is sentinel
