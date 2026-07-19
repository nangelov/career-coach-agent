"""Reusable FastAPI auth dependencies — authN (who), authZ (own-data), rate limits (§7 / §7.1).

Three reusable primitives every protected route composes from, kept in the ``security`` layer
(below ``api``) so any router imports them without a router-to-router dependency:

* :func:`require_auth` — **authN**: verify the ``Authorization: Bearer <token>`` credential via
  the shared :class:`~app.services.auth.SessionAuthenticator` (signature + expiry **and** a live
  session record) and inject the resolved :class:`~app.schemas.auth.CurrentUser`. A guest token
  resolves too (``role="guest"``, ``user_id=None``); missing/invalid/expired/revoked all map to
  ``401`` with a ``WWW-Authenticate: Bearer`` challenge.
* :func:`authorize_session_access` — **authZ**: the single own-data-only check for
  session-scoped routes (chat, cancel, …). A caller may only act on **their own** session, so a
  request naming a ``session_id`` other than the one in the caller's verified token is a ``403``.
  Centralized here rather than re-derived per route (§7 AuthZ: *"users can only read their own
  conversations/profiles"*).
* :func:`require_admin` — **authZ**: the reusable admin gate. Composes on
  :func:`require_auth`, then requires the caller's ``users`` row to be flagged ``is_admin``;
  anything less is a ``403``. Replaces v1's ``GET /get-feedback?key=<HF_TOKEN>``
  shared-secret-in-query-string admin pattern with real access control (§7 AuthZ).
* :func:`get_rate_limit_service` + :func:`rate_limit_exceeded_http` — **rate limits**: the
  app-scoped :class:`~app.services.rate_limiting.RateLimitService` (guest 10-msg/1-upload caps +
  generous per-user limits, §6.8/§7) and the mapper that turns an over-budget
  :class:`~app.services.rate_limiting.RateLimitExceeded` into a ``429`` with a clear,
  upgrade-prompting message and a ``Retry-After`` header.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.app_state import AppStateKeys
from app.bootstrap import (
    build_rate_limit_service,
    build_session_authenticator,
    build_user_store,
)
from app.schemas.auth import CurrentUser
from app.security.client_ip import ClientIpResolver
from app.security.tokens import InvalidSessionToken
from app.services.auth import SessionAuthenticator
from app.services.rate_limiting import RateLimitAction, RateLimitExceeded, RateLimitService
from app.services.user_store import UserStore

#: ``auto_error=False`` so a missing header returns ``None`` here (we raise a uniform
#: ``401`` below) rather than HTTPBearer's default ``403`` — an absent credential is
#: "unauthenticated", not "forbidden".
_bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHENTICATED_HEADERS = {"WWW-Authenticate": "Bearer"}


def get_session_authenticator(request: Request) -> SessionAuthenticator:
    """FastAPI dependency: the app-scoped :class:`SessionAuthenticator`, built once/cached.

    Delegates construction to the composition root
    (:func:`app.bootstrap.build_session_authenticator`) and caches the singleton on
    ``app.state``. Tests override this dependency to inject a fake so the real Redis wiring
    never runs in unit tests.
    """
    authenticator: SessionAuthenticator | None = getattr(
        request.app.state, AppStateKeys.SESSION_AUTHENTICATOR, None
    )
    if authenticator is None:
        authenticator = build_session_authenticator(request.app)
        setattr(request.app.state, AppStateKeys.SESSION_AUTHENTICATOR, authenticator)
    return authenticator


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    authenticator: SessionAuthenticator = Depends(get_session_authenticator),
) -> CurrentUser:
    """Resolve the caller from the bearer token or raise ``401``.

    Reusable across all protected routes (``current_user: CurrentUser = Depends(require_auth)``).
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers=_UNAUTHENTICATED_HEADERS,
        )
    try:
        return await authenticator.authenticate(credentials.credentials)
    except InvalidSessionToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers=_UNAUTHENTICATED_HEADERS,
        ) from exc


async def resolve_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    authenticator: SessionAuthenticator = Depends(get_session_authenticator),
) -> CurrentUser | None:
    """Resolve the caller from the bearer token if present/valid, else ``None`` (never raises).

    The **optional** counterpart to :func:`require_auth`, for routes that serve anonymous callers
    but still want a caller identity when one exists — e.g. ``GET /api/roles/{role}/requirements``
    (§5.6: *"guests can query market requirements, no account needed"*). A missing, malformed, or
    expired/revoked token yields ``None`` rather than a ``401``; the route then keys rate limits on
    a fallback identity (e.g. client IP) instead of rejecting the request.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        return await authenticator.authenticate(credentials.credentials)
    except InvalidSessionToken:
        return None


def get_user_store(request: Request) -> UserStore:
    """FastAPI dependency: the app-scoped :class:`UserStore`, built once and cached.

    Delegates construction to the composition root (:func:`app.bootstrap.build_user_store`)
    and caches the singleton on ``app.state`` — the same ``users``-table adapter the SSO flow
    uses, reused here for the admin ``is_admin`` check. Tests override this dependency to
    inject an in-memory store so the real Postgres wiring never runs in unit tests.
    """
    store: UserStore | None = getattr(request.app.state, AppStateKeys.USER_STORE, None)
    if store is None:
        store = build_user_store(request.app)
        setattr(request.app.state, AppStateKeys.USER_STORE, store)
    return store


async def require_admin(
    current_user: CurrentUser = Depends(require_auth),
    users: UserStore = Depends(get_user_store),
) -> CurrentUser:
    """Resolve an **administrator** caller or raise ``403`` (§7 AuthZ).

    Composes on :func:`require_auth` (so a missing/invalid token is a ``401`` first), then
    enforces the admin flag: the caller must be a logged-in user (``role="user"`` with a
    ``user_id`` — a guest can never be an admin) **and** their ``users`` row must have
    ``is_admin = true``. This is the reusable gate for admin-only routes (the feedback-read
    endpoint that replaces v1's ``GET /get-feedback?key=<HF_TOKEN>``), so the rule lives in
    one place rather than being re-derived per handler. Anything short of an admin is a
    uniform ``403`` (the resource is real, the caller merely lacks the privilege).
    """
    if current_user.user_id is None or not await users.is_admin(current_user.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return current_user


def authorize_session_access(session_id: str, current_user: CurrentUser) -> None:
    """Assert ``current_user`` may act on ``session_id`` or raise ``403`` (own-data-only, §7).

    The one centralized authorization check for session-scoped routes: a session belongs to
    exactly one caller (the token's ``sid`` **is** the caller's session), so a request that
    names a *different* ``session_id`` is trying to read/write someone else's data and is
    forbidden. Reused by ``POST /api/chat`` and ``POST /api/chat/{session}/cancel`` (and any
    future session-scoped route) so the rule lives in one place, not duplicated per handler.
    """
    if session_id != current_user.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own session.",
        )


def get_rate_limit_service(request: Request) -> RateLimitService:
    """FastAPI dependency: the app-scoped :class:`RateLimitService`, built once and cached.

    Delegates construction to the composition root
    (:func:`app.bootstrap.build_rate_limit_service`) and caches the singleton on
    ``app.state``. Tests override this dependency to inject a service over an in-memory
    limiter so the real Redis wiring never runs in unit tests.
    """
    service: RateLimitService | None = getattr(
        request.app.state, AppStateKeys.RATE_LIMIT_SERVICE, None
    )
    if service is None:
        service = build_rate_limit_service(request.app)
        setattr(request.app.state, AppStateKeys.RATE_LIMIT_SERVICE, service)
    return service


def get_client_ip_resolver(request: Request) -> ClientIpResolver:
    """FastAPI dependency: the app-scoped :class:`ClientIpResolver`, built once and cached.

    Built from the ``TRUSTED_PROXIES`` allowlist (§7.5) and cached on ``app.state`` so the
    trusted-proxy config is parsed once. Tests override this to inject a resolver with a known
    allowlist (trusted vs. untrusted proxy chains).
    """
    resolver: ClientIpResolver | None = getattr(
        request.app.state, AppStateKeys.CLIENT_IP_RESOLVER, None
    )
    if resolver is None:
        resolver = ClientIpResolver.from_settings()
        setattr(request.app.state, AppStateKeys.CLIENT_IP_RESOLVER, resolver)
    return resolver


def get_client_ip(
    request: Request,
    resolver: ClientIpResolver = Depends(get_client_ip_resolver),
) -> str:
    """FastAPI dependency: the caller's trusted source IP for per-IP rate limiting (§7.5).

    Reads the immediate peer (``request.client``) and the ``X-Forwarded-For`` header and hands
    both to the :class:`ClientIpResolver`, which honors the trusted-proxy allowlist so the header
    is only trusted behind a configured proxy (else the peer is used) — an untrusted client cannot
    spoof its source IP to evade the limit.
    """
    peer = request.client.host if request.client is not None else None
    forwarded_for = request.headers.get("x-forwarded-for")
    return resolver.resolve(peer=peer, forwarded_for=forwarded_for)


def rate_limit_exceeded_http(exc: RateLimitExceeded) -> HTTPException:
    """Map an over-budget :class:`RateLimitExceeded` to a ``429`` HTTP error (§6.8/§7 / §7.5).

    Guests get an upgrade-prompting message (their cap is the whole point of the guest tier);
    logged-in users get a neutral back-off message; a per-IP cap (§7.5) gets a neutral
    per-source-IP message (never guest-flagged — the IP layer is identity-agnostic). A
    ``Retry-After`` header is set from the counter's remaining window when known, so a
    well-behaved client can wait it out.
    """
    if exc.action == RateLimitAction.IP:
        detail = (
            f"Too many requests from your network (at most {exc.limit} per window). "
            "Please try again shortly."
        )
        headers = (
            {"Retry-After": str(exc.retry_after_seconds)}
            if exc.retry_after_seconds is not None
            else None
        )
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers=headers,
        )
    unit = "messages" if exc.action == RateLimitAction.MESSAGE else "document uploads"
    if exc.is_guest:
        detail = (
            f"Guest limit reached: at most {exc.limit} {unit} per guest session. "
            "Sign in to continue."
        )
    else:
        detail = (
            f"Rate limit reached: at most {exc.limit} {unit} per window. Please try again shortly."
        )
    headers = (
        {"Retry-After": str(exc.retry_after_seconds)}
        if exc.retry_after_seconds is not None
        else None
    )
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers=headers,
    )
