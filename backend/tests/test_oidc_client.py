"""Unit tests for the Authlib OIDC client (P3-02) — no live network, no real credentials.

Drives :class:`~app.security.oidc.AuthlibOIDCClient` against an ``httpx.MockTransport`` that
stands in for the provider's discovery / token / userinfo endpoints. Asserts the PKCE +
minimal-scope authorization URL is built correctly and that a code exchange resolves the
userinfo claims — the security-critical wiring — without hitting Google/LinkedIn.
"""

from __future__ import annotations

import httpx
import pytest

from app.security.oidc import AuthlibOIDCClient, OIDCError, ProviderConfig

_ISSUER = "https://issuer.example"
_METADATA_URL = f"{_ISSUER}/.well-known/openid-configuration"
_REDIRECT_URI = "http://localhost:8000/api/auth/callback/google"


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("openid-configuration"):
        return httpx.Response(
            200,
            json={
                "issuer": _ISSUER,
                "authorization_endpoint": f"{_ISSUER}/authorize",
                "token_endpoint": f"{_ISSUER}/token",
                "userinfo_endpoint": f"{_ISSUER}/userinfo",
            },
        )
    if path == "/token":
        return httpx.Response(
            200,
            json={
                "access_token": "access-token-123",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "openid email profile",
            },
        )
    if path == "/userinfo":
        return httpx.Response(
            200,
            json={"sub": "sub-xyz", "email": "user@example.com", "name": "Test User"},
        )
    return httpx.Response(404)  # pragma: no cover - unexpected route


def _client() -> AuthlibOIDCClient:
    providers = {
        "google": ProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            metadata_url=_METADATA_URL,
            scopes="openid email profile",
        )
    }
    return AuthlibOIDCClient(providers, transport=httpx.MockTransport(_handler))


async def test_authorization_request_has_pkce_and_minimal_scopes() -> None:
    request = await _client().create_authorization_request(
        provider="google", redirect_uri=_REDIRECT_URI
    )

    assert request.url.startswith(f"{_ISSUER}/authorize?")
    # PKCE S256 challenge is present, so a leaked client id alone cannot complete a flow.
    assert "code_challenge=" in request.url
    assert "code_challenge_method=S256" in request.url
    # Minimal scopes only (§7.1); state + verifier are returned for the caller to persist.
    assert "scope=openid+email+profile" in request.url
    assert f"state={request.state}" in request.url
    assert request.code_verifier
    assert request.nonce


async def test_exchange_code_resolves_userinfo() -> None:
    userinfo = await _client().exchange_code(
        provider="google",
        redirect_uri=_REDIRECT_URI,
        code="auth-code",
        code_verifier="verifier-abc",
    )

    assert userinfo.provider == "google"
    assert userinfo.sub == "sub-xyz"
    assert userinfo.email == "user@example.com"
    assert userinfo.display_name == "Test User"


async def test_unknown_provider_raises() -> None:
    with pytest.raises(OIDCError):
        await _client().create_authorization_request(provider="unknown", redirect_uri=_REDIRECT_URI)


async def test_userinfo_missing_required_claims_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": _ISSUER,
                    "authorization_endpoint": f"{_ISSUER}/authorize",
                    "token_endpoint": f"{_ISSUER}/token",
                    "userinfo_endpoint": f"{_ISSUER}/userinfo",
                },
            )
        if request.url.path == "/token":
            return httpx.Response(
                200, json={"access_token": "at", "token_type": "Bearer", "expires_in": 3600}
            )
        # userinfo without sub/email — a provider/config fault we must reject.
        return httpx.Response(200, json={"name": "No Subject"})

    providers = {
        "google": ProviderConfig(
            client_id="client-id",
            client_secret="client-secret",
            metadata_url=_METADATA_URL,
            scopes="openid email profile",
        )
    }
    client = AuthlibOIDCClient(providers, transport=httpx.MockTransport(handler))

    with pytest.raises(OIDCError):
        await client.exchange_code(
            provider="google",
            redirect_uri=_REDIRECT_URI,
            code="auth-code",
            code_verifier="verifier-abc",
        )
