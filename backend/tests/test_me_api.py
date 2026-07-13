"""API tests for ``DELETE /api/me`` + ``GET /api/me/export`` (SEC-05, §7.6 / §9).

Overrides :func:`~app.api.me.get_account_service` with an :class:`AccountService` built over
the in-memory fakes (:class:`InMemoryAccountRepository` + :class:`InMemorySessionStore`) and
``require_auth`` with a stand-in :class:`~app.schemas.auth.CurrentUser`, so no real
Postgres/Redis wiring runs. Asserts the contract end-to-end through the router: erasure revokes
every one of the user's live sessions and returns ``204``; erasure is idempotent; export returns
the caller's scoped document as a download; and guest / unauthenticated calls are rejected.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from app.api.me import get_account_service
from app.main import app
from app.schemas.account import AccountExport
from app.schemas.auth import CurrentUser, SessionRecord
from app.security.dependencies import require_auth
from app.services.account import AccountService, InMemoryAccountRepository
from app.services.session_store import InMemorySessionStore
from tests.fakes import fake_current_user


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def repo() -> InMemoryAccountRepository:
    return InMemoryAccountRepository()


@pytest.fixture
def sessions() -> InMemorySessionStore:
    return InMemorySessionStore()


@pytest.fixture
def wire(
    repo: InMemoryAccountRepository, sessions: InMemorySessionStore
) -> Iterator[Callable[[CurrentUser], None]]:
    """Wire the in-memory account service once and (re)point ``require_auth`` at a caller."""
    service = AccountService(repo, sessions)
    app.dependency_overrides[get_account_service] = lambda: service

    def _as(user: CurrentUser) -> None:
        app.dependency_overrides[require_auth] = lambda: user

    yield _as
    app.dependency_overrides.clear()


def _user(user_id: str, session_id: str = "s1") -> CurrentUser:
    return fake_current_user(session_id, role="user", user_id=user_id)


async def _seed_session(store: InMemorySessionStore, session_id: str, user_id: str) -> None:
    await store.create(
        SessionRecord(
            session_id=session_id, role="user", user_id=user_id, created_at=datetime.now(UTC)
        ),
        ttl_seconds=3600,
    )


async def test_delete_me_erases_and_revokes_all_sessions(
    client: httpx.AsyncClient,
    repo: InMemoryAccountRepository,
    sessions: InMemorySessionStore,
    wire: Callable[[CurrentUser], None],
) -> None:
    # Sessions live only in the (authoritative) session store — no Postgres row exists for
    # them (the login-shaped case: a device that logged in but never persisted a chat turn).
    await _seed_session(sessions, "s1", "u1")
    await _seed_session(sessions, "s2", "u1")
    wire(_user("u1"))

    response = await client.delete("/api/me")

    assert response.status_code == 204
    # Every device's session is revoked, not just the caller's — enumerated from the store's
    # per-user index, so a session with no Postgres row is still revoked.
    assert await sessions.get("s1") is None
    assert await sessions.get("s2") is None
    # The Postgres cascade delete was invoked.
    assert repo.deleted == ["u1"]


async def test_delete_me_is_idempotent_on_user_with_no_data(
    client: httpx.AsyncClient,
    repo: InMemoryAccountRepository,
    wire: Callable[[CurrentUser], None],
) -> None:
    wire(_user("fresh"))
    first = await client.delete("/api/me")
    second = await client.delete("/api/me")
    # No data, deleted twice — never a 500.
    assert first.status_code == 204
    assert second.status_code == 204
    assert repo.deleted == ["fresh", "fresh"]


async def test_delete_me_guest_forbidden(
    client: httpx.AsyncClient,
    repo: InMemoryAccountRepository,
    wire: Callable[[CurrentUser], None],
) -> None:
    wire(fake_current_user("guest-s", role="guest"))
    response = await client.delete("/api/me")
    assert response.status_code == 403
    # Nothing was deleted for a guest.
    assert repo.deleted == []


async def test_delete_me_requires_auth_401(client: httpx.AsyncClient) -> None:
    service = AccountService(InMemoryAccountRepository(), InMemorySessionStore())
    app.dependency_overrides[get_account_service] = lambda: service
    try:
        response = await client.delete("/api/me")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


async def test_export_returns_scoped_document_as_download(
    client: httpx.AsyncClient,
    repo: InMemoryAccountRepository,
    wire: Callable[[CurrentUser], None],
) -> None:
    repo.exports_by_user["u1"] = AccountExport(
        user={"id": "u1", "email": "u1@example.com"},
        goals=[{"title": "Staff engineer"}],
        kb_chunks=[{"content": "cv text"}],  # no embedding key — the model has no such field
    )
    wire(_user("u1"))

    response = await client.get("/api/me/export")

    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"id": "u1", "email": "u1@example.com"}
    assert body["goals"] == [{"title": "Staff engineer"}]
    # Raw embedding vectors are never part of the export shape.
    assert "embedding" not in body["kb_chunks"][0]
    # Served as a downloadable attachment (Art. 20 portability).
    assert response.headers["content-disposition"] == (
        'attachment; filename="career-coach-export.json"'
    )


async def test_export_guest_forbidden(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(fake_current_user("guest-s", role="guest"))
    response = await client.get("/api/me/export")
    assert response.status_code == 403


async def test_export_requires_auth_401(client: httpx.AsyncClient) -> None:
    service = AccountService(InMemoryAccountRepository(), InMemorySessionStore())
    app.dependency_overrides[get_account_service] = lambda: service
    try:
        response = await client.get("/api/me/export")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401
