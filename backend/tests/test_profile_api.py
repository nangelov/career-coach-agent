"""API tests for ``GET/PUT /api/profile`` (P5-05, §4/§8 — structured profile read/edit).

Overrides :func:`~app.api.profile.get_profile_store` with an
:class:`~app.services.profile_store.InMemoryProfileStore` and ``require_auth`` with a stand-in
:class:`~app.schemas.auth.CurrentUser`, so no real Postgres/Redis wiring runs. Asserts the
read/edit contract end-to-end through the router: no-profile → empty ``200``; round-trip of a
stored profile; upsert creates then replaces; cross-user isolation (a user never reads/writes
another user's row); guest behavior (read empty, write ``403``); malformed body → ``422``; and
missing auth → ``401``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from app.api.profile import get_profile_store
from app.ingestion.profile import ProfileSchema
from app.main import app
from app.schemas.auth import CurrentUser
from app.security.dependencies import require_auth
from app.services.profile_store import InMemoryProfileStore
from tests.fakes import fake_current_user


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def store() -> InMemoryProfileStore:
    return InMemoryProfileStore()


@pytest.fixture
def wire(store: InMemoryProfileStore) -> Iterator[Callable[[CurrentUser], None]]:
    """Wire the in-memory store once and (re)point ``require_auth`` at a given caller.

    Returned helper lets a single test switch the authenticated caller between requests (to
    exercise cross-user isolation) while sharing one store. Overrides are cleared by the
    fixture teardown.
    """
    app.dependency_overrides[get_profile_store] = lambda: store

    def _as(user: CurrentUser) -> None:
        app.dependency_overrides[require_auth] = lambda: user

    yield _as
    app.dependency_overrides.clear()


def _user(user_id: str, session_id: str = "s1") -> CurrentUser:
    return fake_current_user(session_id, role="user", user_id=user_id)


async def test_get_profile_returns_empty_when_none(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    response = await client.get("/api/profile")
    assert response.status_code == 200
    # A fresh account with no CV uploaded reads as an empty (but renderable) profile.
    assert response.json() == ProfileSchema().model_dump()


async def test_get_profile_returns_stored_profile(
    client: httpx.AsyncClient, store: InMemoryProfileStore, wire: Callable[[CurrentUser], None]
) -> None:
    await store.upsert("u1", ProfileSchema(skills=["Python"], goals=["Staff engineer"]))
    wire(_user("u1"))
    response = await client.get("/api/profile")
    assert response.status_code == 200
    body = response.json()
    assert body["skills"] == ["Python"]
    assert body["goals"] == ["Staff engineer"]


async def test_put_profile_creates_then_get_returns_it(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    payload = ProfileSchema(
        skills=["SQL"],
        experience=[{"title": "Data Engineer", "company": "Acme"}],
    ).model_dump()
    put = await client.put("/api/profile", json=payload)
    assert put.status_code == 200
    assert put.json()["skills"] == ["SQL"]

    got = await client.get("/api/profile")
    assert got.status_code == 200
    body = got.json()
    assert body["skills"] == ["SQL"]
    assert body["experience"][0]["title"] == "Data Engineer"


async def test_put_profile_updates_existing(
    client: httpx.AsyncClient, store: InMemoryProfileStore, wire: Callable[[CurrentUser], None]
) -> None:
    await store.upsert("u1", ProfileSchema(skills=["old"]))
    wire(_user("u1"))
    put = await client.put("/api/profile", json=ProfileSchema(skills=["new"]).model_dump())
    assert put.status_code == 200
    # The edit replaces the prior profile in place (one row per user).
    assert (await store.get("u1")).skills == ["new"]  # type: ignore[union-attr]


async def test_cross_user_isolation(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    # User A writes a profile; user B must neither read it nor overwrite it.
    wire(_user("A", session_id="sa"))
    await client.put("/api/profile", json=ProfileSchema(skills=["A-secret"]).model_dump())

    wire(_user("B", session_id="sb"))
    b_get = await client.get("/api/profile")
    assert b_get.status_code == 200
    assert b_get.json() == ProfileSchema().model_dump()  # B sees its own (empty) profile
    await client.put("/api/profile", json=ProfileSchema(skills=["B-own"]).model_dump())

    # A's profile is untouched by B's write.
    wire(_user("A", session_id="sa"))
    a_get = await client.get("/api/profile")
    assert a_get.json()["skills"] == ["A-secret"]


async def test_guest_get_returns_empty_profile(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(fake_current_user("guest-s", role="guest"))
    response = await client.get("/api/profile")
    assert response.status_code == 200
    assert response.json() == ProfileSchema().model_dump()


async def test_guest_put_is_forbidden(
    client: httpx.AsyncClient, store: InMemoryProfileStore, wire: Callable[[CurrentUser], None]
) -> None:
    wire(fake_current_user("guest-s", role="guest"))
    response = await client.put("/api/profile", json=ProfileSchema(skills=["x"]).model_dump())
    assert response.status_code == 403
    # Nothing was persisted for the guest session id either.
    assert await store.get("guest-s") is None


async def test_put_rejects_malformed_body_422(
    client: httpx.AsyncClient, wire: Callable[[CurrentUser], None]
) -> None:
    wire(_user("u1"))
    # ``skills`` must be a list[str]; a bare string is not a valid list → 422.
    response = await client.put("/api/profile", json={"skills": "python"})
    assert response.status_code == 422


async def test_get_profile_requires_auth_401(client: httpx.AsyncClient) -> None:
    # No require_auth override → the real dependency rejects the missing bearer token.
    store = InMemoryProfileStore()
    app.dependency_overrides[get_profile_store] = lambda: store
    try:
        response = await client.get("/api/profile")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401
