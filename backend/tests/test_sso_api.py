"""API tests for the SSO endpoints (P3-02) — login / callback / logout, no network.

Overrides the SSO service and the session authenticator with instances wired over
process-local stores + a scripted :class:`~tests.fakes.FakeOIDCClient`, so the full Router →
Service path runs with **no** Redis / Postgres / live provider. The SSO service and the
authenticator deliberately share one session store so logout revocation is observable
end-to-end. Asserts: login 302s to the consent screen; the callback completes and 302s to
the frontend with the token in the URL fragment; logout requires a bearer token and revokes
the session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import ASGITransport

from app.api.auth import get_sso_auth_service
from app.main import app
from app.security.dependencies import get_session_authenticator
from app.security.tokens import SessionTokenCodec
from app.services.auth import SessionAuthenticator, SsoAuthService
from app.services.oauth_state_store import InMemoryOAuthStateStore
from app.services.session_store import InMemorySessionStore
from app.services.user_store import InMemoryUserStore
from tests.fakes import FakeOIDCClient

_SECRET = "sso-api-test-secret"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    store = InMemorySessionStore()
    codec = SessionTokenCodec(secret=_SECRET, expire_minutes=60)
    sso = SsoAuthService(
        FakeOIDCClient(),
        InMemoryOAuthStateStore(),
        InMemoryUserStore(),
        store,
        codec,
        redirect_base_url="https://app.example",
        state_ttl_seconds=600,
        session_ttl_seconds=3600,
        providers=frozenset({"google", "linkedin"}),
    )
    authenticator = SessionAuthenticator(codec, store)
    app.dependency_overrides[get_sso_auth_service] = lambda: sso
    app.dependency_overrides[get_session_authenticator] = lambda: authenticator
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        try:
            yield http
        finally:
            app.dependency_overrides.pop(get_sso_auth_service, None)
            app.dependency_overrides.pop(get_session_authenticator, None)


def _token_from_redirect(location: str) -> dict[str, str]:
    """Parse the ``#access_token=...`` fragment the callback redirects to."""
    fragment = urlsplit(location).fragment
    return {k: v[0] for k, v in parse_qs(fragment).items()}


async def test_login_redirects_to_consent(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/login/google")

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://provider.example/consent")


async def test_login_unknown_provider_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/login/myspace")
    assert response.status_code == 404


async def test_callback_completes_and_redirects_with_token(client: httpx.AsyncClient) -> None:
    # Start the flow so the PKCE transaction (state-1) is stored, then hit the callback.
    await client.get("/api/auth/login/google")
    response = await client.get(
        "/api/auth/callback/google", params={"code": "auth-code", "state": "state-1"}
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://localhost:3000/auth/callback#")
    token = _token_from_redirect(location)
    assert token["token_type"] == "bearer"
    assert token["role"] == "user"
    assert token["session_id"]
    # The delivered token is a valid user session JWT.
    claims = SessionTokenCodec(secret=_SECRET).decode(token["access_token"])
    assert claims.role == "user"
    assert claims.sid == token["session_id"]


async def test_callback_invalid_state_400(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/auth/callback/google", params={"code": "auth-code", "state": "never-issued"}
    )
    assert response.status_code == 400


async def test_callback_missing_params_422(client: httpx.AsyncClient) -> None:
    # code + state are required query params.
    response = await client.get("/api/auth/callback/google")
    assert response.status_code == 422


async def test_logout_requires_bearer_token(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/auth/logout")
    assert response.status_code == 401


async def test_logout_revokes_session(client: httpx.AsyncClient) -> None:
    # Full flow: login → callback → obtain the bearer token.
    await client.get("/api/auth/login/google")
    callback = await client.get(
        "/api/auth/callback/google", params={"code": "auth-code", "state": "state-1"}
    )
    token = _token_from_redirect(callback.headers["location"])["access_token"]
    auth_header = {"Authorization": f"Bearer {token}"}

    # Logout succeeds (204)...
    first = await client.post("/api/auth/logout", headers=auth_header)
    assert first.status_code == 204

    # ...and the token no longer resolves (session record deleted → 401).
    second = await client.post("/api/auth/logout", headers=auth_header)
    assert second.status_code == 401
