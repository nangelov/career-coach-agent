"""Auth API — guest session (P3-01) + SSO OIDC login/callback/logout (P3-02, §7.1/§9).

This router is deliberately **thin** (Router → Service → Repository): it owns HTTP concerns
(status codes, redirects, error mapping) and delegates all logic to the auth services
(:class:`~app.services.auth.GuestAuthService`, :class:`~app.services.auth.SsoAuthService`,
:class:`~app.services.auth.SessionAuthenticator`). It imports no repository/driver types —
only service classes, schemas, and dependencies (which delegate to the composition root) —
so every endpoint is unit-testable via a dependency override with no Redis/Postgres.

SSO flow (§7.1): ``GET /login/{provider}`` → 302 to the provider consent screen (PKCE,
minimal scopes); the provider redirects the browser back to ``GET /callback/{provider}``,
which completes the exchange, mints the backend session JWT, and 302-redirects to the
frontend with the token in the URL **fragment** (never a query param / server log). ``POST
/logout`` ends the session (deletes its record → the still-unexpired JWT stops resolving).
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.responses import RedirectResponse

from app.app_state import AppStateKeys
from app.bootstrap import (
    build_guest_auth_service,
    build_guest_upgrade_service,
    build_sso_auth_service,
)
from app.config import settings
from app.schemas.auth import (
    CurrentUser,
    GuestSessionRequest,
    GuestSessionResponse,
    UpgradeTicketResponse,
)
from app.security.dependencies import get_session_authenticator, require_auth
from app.security.oidc import OIDCError
from app.services.auth import (
    ConsentRequired,
    GuestAuthService,
    InvalidOAuthState,
    ProviderNotConfigured,
    SessionAuthenticator,
    SsoAuthService,
    UnknownProvider,
)
from app.services.guest_upgrade import GuestUpgradeService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_guest_auth_service(request: Request) -> GuestAuthService:
    """FastAPI dependency: the app-scoped :class:`GuestAuthService`, built once and cached.

    Delegates construction to the composition root
    (:func:`app.bootstrap.build_guest_auth_service`) and caches the singleton on
    ``app.state``. Tests override this dependency to inject a fake, so the real Redis wiring
    never runs in unit tests.
    """
    service: GuestAuthService | None = getattr(request.app.state, AppStateKeys.AUTH_SERVICE, None)
    if service is None:
        service = build_guest_auth_service(request.app)
        setattr(request.app.state, AppStateKeys.AUTH_SERVICE, service)
    return service


def get_sso_auth_service(request: Request) -> SsoAuthService:
    """FastAPI dependency: the app-scoped :class:`SsoAuthService`, built once and cached.

    Delegates to :func:`app.bootstrap.build_sso_auth_service`; cached on ``app.state``.
    Tests override this to inject a fake wired over in-memory stores, so the OIDC flow runs
    with no live network / Redis / Postgres.
    """
    service: SsoAuthService | None = getattr(request.app.state, AppStateKeys.SSO_AUTH_SERVICE, None)
    if service is None:
        service = build_sso_auth_service(request.app)
        setattr(request.app.state, AppStateKeys.SSO_AUTH_SERVICE, service)
    return service


def get_guest_upgrade_service(request: Request) -> GuestUpgradeService:
    """FastAPI dependency: the app-scoped :class:`GuestUpgradeService`, built once and cached.

    Delegates construction to the composition root
    (:func:`app.bootstrap.build_guest_upgrade_service`); cached on ``app.state``. Tests
    override this to inject a fake wired over in-memory stores, so the upgrade flow runs with
    no live Redis / Postgres.
    """
    service: GuestUpgradeService | None = getattr(
        request.app.state, AppStateKeys.GUEST_UPGRADE_SERVICE, None
    )
    if service is None:
        service = build_guest_upgrade_service(request.app)
        setattr(request.app.state, AppStateKeys.GUEST_UPGRADE_SERVICE, service)
    return service


@router.post("/guest", status_code=201)
async def create_guest_session(
    payload: GuestSessionRequest | None = None,
    service: GuestAuthService = Depends(get_guest_auth_service),
) -> GuestSessionResponse:
    """Start an anonymous guest session and return a bearer token (§7.1 / §9).

    No authentication required — this is how a guest begins. Gated by the consent check
    (§6.22): the body must carry ``consent=true`` (the login screen's ToS/privacy checkbox),
    otherwise the request is rejected ``400`` and **no** session is minted. A missing body is
    treated as no consent (fail closed). On success, creates a TTL'd Redis session record (no
    Postgres history, per §4, stamped with the accepted policy version) and returns a
    backend-signed session JWT with ``role="guest"`` plus the ``session_id`` the client uses
    for subsequent chat/rate-limit calls — the same token shape logged-in users receive in
    P3-02, so the frontend treats both uniformly.
    """
    consent = payload is not None and payload.consent
    try:
        return await service.create_guest_session(consent=consent)
    except ConsentRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent to the Terms of Service and Privacy Notice is required.",
        ) from exc


@router.post("/upgrade", status_code=201)
async def begin_upgrade(
    current_user: CurrentUser = Depends(require_auth),
    service: GuestUpgradeService = Depends(get_guest_upgrade_service),
) -> UpgradeTicketResponse:
    """Mint a single-use ticket to carry the current guest session into a new account (§4).

    Requires a valid **guest** bearer token: the ticket is bound server-side to *that*
    verified guest ``session_id`` (never a client-supplied id), so a subsequent
    ``GET /api/auth/login/{provider}?upgrade_ticket=...`` preserves the active conversation.
    A logged-in user has nothing to upgrade — that is a ``409 Conflict``.
    """
    if current_user.role != "guest":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a guest session can be upgraded.",
        )
    return await service.create_ticket(current_user.session_id)


@router.get("/login/{provider}")
async def sso_login(
    provider: str,
    upgrade_ticket: str | None = Query(
        default=None,
        description="Optional single-use ticket (from POST /api/auth/upgrade) to carry the "
        "originating guest session over to the new account.",
    ),
    consent: bool = Query(
        default=False,
        description="Whether the ToS + privacy notice was accepted on the login screen "
        "(§6.22) — required to start the login; rejected 400 otherwise.",
    ),
    service: SsoAuthService = Depends(get_sso_auth_service),
) -> RedirectResponse:
    """Begin the OIDC login: 302-redirect to the provider consent screen (§7.1).

    Builds a PKCE authorization request with minimal scopes (``openid email profile``) and
    stores the pending transaction; the browser is sent to the provider. The consent gate
    (§6.22): without ``consent=true`` (the login screen's checkbox) the attempt is rejected
    ``400`` **before** redirecting to the provider and before any upgrade ticket is consumed.
    An unsupported ``{provider}`` is a ``404``; a *supported* provider with no OAuth
    credentials configured on this deployment is a ``503`` (fail cleanly in-stack rather than
    redirect to the provider with a blank ``client_id``). A valid ``upgrade_ticket`` binds this
    login to the guest session it names so the callback preserves that conversation (P3-03).
    """
    try:
        url = await service.begin_login(provider, upgrade_ticket=upgrade_ticket, consent=consent)
    except UnknownProvider as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown SSO provider: {provider}",
        ) from exc
    except ProviderNotConfigured as exc:
        # A supported provider without OAuth credentials on this deployment (§7.1): fail
        # cleanly inside our own stack (503) instead of redirecting the browser to the
        # provider with a blank client_id. The BFF maps this to ?login_error=provider_unavailable.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"SSO provider is not configured: {provider}",
        ) from exc
    except ConsentRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent to the Terms of Service and Privacy Notice is required.",
        ) from exc
    except OIDCError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SSO provider is unavailable",
        ) from exc
    # 302 so the browser follows to the provider with a GET.
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/callback/{provider}")
async def sso_callback(
    provider: str,
    code: str = Query(..., description="Authorization code returned by the provider."),
    state: str = Query(..., description="CSRF/transaction state echoed by the provider."),
    service: SsoAuthService = Depends(get_sso_auth_service),
) -> RedirectResponse:
    """Complete the OIDC exchange and 302-redirect to the frontend with the token (§7.1).

    Verifies ``state`` against the stored transaction, exchanges ``code`` (with the PKCE
    verifier), upserts the ``users`` row, and mints the backend session JWT. The token is
    handed to the SPA in the redirect URL **fragment** so it never reaches server logs or
    the Referer header. A bad/expired/replayed ``state`` is a ``400``; a provider-side
    failure is a ``502``.
    """
    try:
        session = await service.complete_login(provider, code=code, state=state)
    except UnknownProvider as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown SSO provider: {provider}",
        ) from exc
    except InvalidOAuthState as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired login state",
        ) from exc
    except OIDCError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="SSO code exchange failed",
        ) from exc

    fragment = urlencode(
        {
            "access_token": session.access_token,
            "token_type": session.token_type,
            "session_id": session.session_id,
            "role": session.role,
            "expires_in": session.expires_in,
        }
    )
    location = f"{settings.OAUTH_POST_LOGIN_REDIRECT}#{fragment}"
    # NB (SEC-04): this "token in the redirect fragment" shape is *server-to-server only*
    # now. The backend publishes no host port; the browser never reaches this endpoint or
    # follows this redirect. The Next.js BFF callback handler
    # (frontend/app/api/auth/callback/[provider]/route.ts) calls this with
    # redirects **not** auto-followed, reads the token out of this Location header inside its
    # Node process, sets it in an httpOnly cookie, and redirects the *browser* to a clean URL.
    # So the token never enters browser JS, history, or the Referer header (design §7.2 /
    # §6.13). Do not "fix" this back into a browser-facing fragment redirect — that would
    # re-introduce the XSS-exposed token-in-URL pattern SEC-04 removed.
    return RedirectResponse(location, status_code=status.HTTP_302_FOUND)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: CurrentUser = Depends(require_auth),
    authenticator: SessionAuthenticator = Depends(get_session_authenticator),
) -> None:
    """End the caller's session (§7.1 / §9).

    Requires a valid bearer token (guest or user), then deletes the server-side session
    record — so the still-unexpired JWT stops resolving on subsequent requests (immediate
    revocation without a token denylist). Idempotent and returns ``204``.
    """
    await authenticator.end_session(current_user.session_id)
