"""API test for ``POST /api/auth/guest`` (P3-01).

Overrides :func:`~app.api.auth.get_guest_auth_service` with a service built over the
process-local ``InMemorySessionStore`` + the real session-JWT codec, so the endpoint runs
its full Router → Service path with **no Redis / no Postgres**. Asserts: no auth is required
to call it, it returns 201 with a bearer token + session id, and the returned token is a
valid guest session JWT whose ``sid`` matches the response.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from app.api.auth import get_guest_auth_service
from app.main import app
from app.security.tokens import SessionTokenCodec
from app.services.auth import GuestAuthService
from app.services.session_store import InMemorySessionStore

_SECRET = "auth-api-test-secret"


@pytest.fixture
def store() -> InMemorySessionStore:
    return InMemorySessionStore()


@pytest.fixture
def client_and_store(store: InMemorySessionStore) -> tuple[httpx.AsyncClient, InMemorySessionStore]:
    codec = SessionTokenCodec(secret=_SECRET, expire_minutes=60)
    service = GuestAuthService(
        store, codec, session_ttl_seconds=3600, consent_policy_version="2026-07-13"
    )
    app.dependency_overrides[get_guest_auth_service] = lambda: service
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), store


async def test_guest_endpoint_creates_session(
    client_and_store: tuple[httpx.AsyncClient, InMemorySessionStore],
) -> None:
    client, store = client_and_store
    try:
        # No Authorization header — starting a guest session must not require auth, but the
        # consent gate (§6.22) does require the body to carry consent.
        response = await client.post("/api/auth/guest", json={"consent": True})
    finally:
        app.dependency_overrides.pop(get_guest_auth_service, None)
        await client.aclose()

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "guest"
    assert body["expires_in"] == 3600
    assert body["access_token"]
    assert body["session_id"]

    # The session record was actually persisted (guest is Redis-only; here the fake store),
    # stamped with the accepted consent policy version.
    stored = await store.get(body["session_id"])
    assert stored is not None
    assert stored.role == "guest"
    assert stored.consent_policy_version == "2026-07-13"

    # The bearer token is a valid guest session JWT tied to the same session.
    claims = SessionTokenCodec(secret=_SECRET).decode(body["access_token"])
    assert claims.role == "guest"
    assert claims.sid == body["session_id"]


async def test_guest_endpoint_rejects_missing_consent(
    client_and_store: tuple[httpx.AsyncClient, InMemorySessionStore],
) -> None:
    client, store = client_and_store
    try:
        # No consent (and no body at all) → 400, no session minted (§6.22 fail closed).
        no_body = await client.post("/api/auth/guest")
        explicit_false = await client.post("/api/auth/guest", json={"consent": False})
    finally:
        app.dependency_overrides.pop(get_guest_auth_service, None)
        await client.aclose()
    assert no_body.status_code == 400
    assert explicit_false.status_code == 400
    assert store._records == {}  # type: ignore[attr-defined]


async def test_guest_endpoint_rejects_get(
    client_and_store: tuple[httpx.AsyncClient, InMemorySessionStore],
) -> None:
    client, _ = client_and_store
    try:
        response = await client.get("/api/auth/guest")
    finally:
        app.dependency_overrides.pop(get_guest_auth_service, None)
        await client.aclose()
    assert response.status_code == 405
