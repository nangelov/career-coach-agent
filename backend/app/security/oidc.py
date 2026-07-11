"""OIDC client seam + Authlib implementation (§7.1 — SSO login via Google/LinkedIn).

The v2 auth model makes FastAPI the OIDC *relying party*: it runs the authorization-code +
PKCE flow against the provider, then mints its **own** session JWT (Next.js is a pure
Bearer-token client). This module owns the raw OAuth/OIDC mechanics behind that flow and
keeps them behind a narrow port so the service layer (and tests) never depend on Authlib or
the network directly:

* :class:`OIDCClient` — the port: build a provider authorization request (with a fresh PKCE
  verifier + state + nonce), and exchange an authorization ``code`` for the caller's
  verified identity.
* :class:`AuthlibOIDCClient` — the real implementation over Authlib's
  :class:`~authlib.integrations.httpx_client.AsyncOAuth2Client`, discovering each provider's
  endpoints from its ``.well-known/openid-configuration`` document.

Security posture (§7.1): **PKCE (S256)** so a leaked client id alone cannot complete a
flow; **minimal scopes** (``openid email profile``); the client secret comes only from
settings (env / HF Space Secret). Identity is resolved via the provider's ``userinfo``
endpoint using the just-issued access token over TLS — authoritative provider-verified
claims — which keeps the implementation free of JWKS handling while PKCE + ``state`` guard
against code interception and CSRF.

Testability: :class:`AuthlibOIDCClient` accepts an injectable httpx ``transport`` so the
discovery / token / userinfo calls can be driven by an ``httpx.MockTransport`` with **no**
live network and no real Google/LinkedIn credentials.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from authlib.common.security import generate_token
from authlib.integrations.httpx_client import AsyncOAuth2Client

from app.config import Settings, settings


class OIDCError(Exception):
    """Raised when an OIDC step fails (unknown provider, discovery/token/userinfo error).

    The auth service maps this to a ``400``/``502`` at the API edge; callers never see
    Authlib/httpx error types.
    """


@dataclass(frozen=True)
class AuthorizationRequest:
    """The output of starting a login: where to send the user + what to remember.

    ``url`` is the provider consent URL to redirect the browser to. ``state``,
    ``code_verifier`` and ``nonce`` are the per-attempt values the caller persists (keyed by
    ``state``) so :meth:`OIDCClient.exchange_code` can complete the flow on the callback.
    """

    url: str
    state: str
    code_verifier: str
    nonce: str


@dataclass(frozen=True)
class OIDCUserInfo:
    """The verified identity returned by a successful code exchange.

    Only the minimal-scope claims are surfaced (§7.1): the provider-issued ``sub`` (stable
    per provider), ``email``, and an optional display ``name``.
    """

    provider: str
    sub: str
    email: str
    display_name: str | None


class OIDCClient:
    """Port: start an OIDC login and exchange the returned code for a verified identity."""

    async def create_authorization_request(
        self, *, provider: str, redirect_uri: str
    ) -> AuthorizationRequest:  # pragma: no cover - abstract seam
        raise NotImplementedError

    async def exchange_code(
        self,
        *,
        provider: str,
        redirect_uri: str,
        code: str,
        code_verifier: str,
    ) -> OIDCUserInfo:  # pragma: no cover - abstract seam
        raise NotImplementedError


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved per-provider config (credentials + discovery URL + scopes)."""

    client_id: str
    client_secret: str
    metadata_url: str
    scopes: str


class AuthlibOIDCClient(OIDCClient):
    """Authlib-backed :class:`OIDCClient` — PKCE authorization-code flow (§7.1).

    Endpoints are discovered per provider from the OIDC metadata document and cached for the
    process lifetime (they are stable provider constants). Each call constructs a fresh
    :class:`~authlib.integrations.httpx_client.AsyncOAuth2Client` (cheap; carries no
    cross-request state), which is what generates the PKCE ``code_challenge`` from the
    verifier we pass and performs the signed token exchange.
    """

    def __init__(
        self,
        providers: dict[str, ProviderConfig],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._providers = providers
        # Injected only in tests (an httpx.MockTransport) so discovery/token/userinfo run
        # with no live network; None in production means httpx's default transport.
        self._transport = transport
        self._timeout = timeout
        self._metadata_cache: dict[str, dict[str, str]] = {}

    @classmethod
    def from_settings(cls, config: Settings = settings) -> AuthlibOIDCClient:
        """Build the client from application config (credentials + discovery URLs)."""
        providers = {
            "google": ProviderConfig(
                client_id=config.GOOGLE_CLIENT_ID,
                client_secret=config.GOOGLE_CLIENT_SECRET,
                metadata_url=config.OAUTH_METADATA_URLS["google"],
                scopes=config.OAUTH_SCOPES,
            ),
            "linkedin": ProviderConfig(
                client_id=config.LINKEDIN_CLIENT_ID,
                client_secret=config.LINKEDIN_CLIENT_SECRET,
                metadata_url=config.OAUTH_METADATA_URLS["linkedin"],
                scopes=config.OAUTH_SCOPES,
            ),
        }
        return cls(providers)

    def _provider_config(self, provider: str) -> ProviderConfig:
        config = self._providers.get(provider)
        if config is None:
            raise OIDCError(f"Unknown OIDC provider: {provider!r}")
        return config

    async def _metadata(self, provider: str) -> dict[str, str]:
        """Return (and cache) the provider's discovery document."""
        cached = self._metadata_cache.get(provider)
        if cached is not None:
            return cached
        config = self._provider_config(provider)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as http:
                response = await http.get(config.metadata_url)
                response.raise_for_status()
                metadata: dict[str, str] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError(f"OIDC discovery failed for {provider!r}: {exc}") from exc
        self._metadata_cache[provider] = metadata
        return metadata

    def _client(self, config: ProviderConfig, redirect_uri: str) -> AsyncOAuth2Client:
        return AsyncOAuth2Client(
            client_id=config.client_id,
            client_secret=config.client_secret,
            scope=config.scopes,
            redirect_uri=redirect_uri,
            code_challenge_method="S256",
            transport=self._transport,
            timeout=self._timeout,
        )

    async def create_authorization_request(
        self, *, provider: str, redirect_uri: str
    ) -> AuthorizationRequest:
        """Build the provider consent URL with a fresh PKCE verifier, state and nonce."""
        config = self._provider_config(provider)
        metadata = await self._metadata(provider)
        code_verifier = generate_token(64)
        nonce = generate_token(32)
        async with self._client(config, redirect_uri) as oauth:
            url, state = oauth.create_authorization_url(
                metadata["authorization_endpoint"],
                code_verifier=code_verifier,
                nonce=nonce,
            )
        return AuthorizationRequest(url=url, state=state, code_verifier=code_verifier, nonce=nonce)

    async def exchange_code(
        self,
        *,
        provider: str,
        redirect_uri: str,
        code: str,
        code_verifier: str,
    ) -> OIDCUserInfo:
        """Exchange ``code`` (with the PKCE verifier) and return the verified identity."""
        config = self._provider_config(provider)
        metadata = await self._metadata(provider)
        try:
            async with self._client(config, redirect_uri) as oauth:
                await oauth.fetch_token(
                    metadata["token_endpoint"],
                    grant_type="authorization_code",
                    code=code,
                    redirect_uri=redirect_uri,
                    code_verifier=code_verifier,
                )
                userinfo_response = await oauth.get(metadata["userinfo_endpoint"])
                userinfo_response.raise_for_status()
                claims: dict[str, str] = userinfo_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError(f"OIDC code exchange failed for {provider!r}: {exc}") from exc

        sub = claims.get("sub")
        email = claims.get("email")
        if not sub or not email:
            # Without a stable subject and an email we cannot key or contact the account —
            # the minimal scope guarantees both, so their absence is a provider/config fault.
            raise OIDCError(f"OIDC userinfo for {provider!r} missing required 'sub'/'email' claims")
        return OIDCUserInfo(
            provider=provider,
            sub=sub,
            email=email,
            display_name=claims.get("name"),
        )
