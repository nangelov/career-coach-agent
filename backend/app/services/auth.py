"""Auth service layer — guest sessions, SSO login/verify/logout (§7.1 / §9).

Three collaborators live here, all depending only on **ports** (session store, OIDC client,
user store, OAuth-state store, token codec) so they touch no datastore driver directly
(Router → Service → Repository) and are trivially unit-testable with fakes:

* :class:`GuestAuthService` — ``POST /api/auth/guest``: starts an **anonymous, Redis-only**
  session and hands back a backend-signed bearer token (P3-01).
* :class:`SsoAuthService` — the OIDC login flow (P3-02): ``begin_login`` builds the provider
  consent URL and remembers the PKCE transaction; ``complete_login`` finishes the exchange,
  upserts the ``users`` row (no password ever stored), and mints the **same** bearer-token
  shape a guest gets so the frontend treats both uniformly.
* :class:`SessionAuthenticator` — verifies a bearer token (signature + expiry) *and* that
  its server-side session record still exists, resolving the caller for protected routes;
  :meth:`SessionAuthenticator.end_session` is what ``POST /api/auth/logout`` calls to revoke
  a session immediately (deleting the record makes the still-unexpired JWT stop resolving).

Guests never touch Postgres ``conversations``/``messages`` (§4: *"Guests get NO persisted
history"*): the only server-side state a guest gets is the Redis session record, whose
``session_id`` is the handle later used for the per-session guest rate limit (P3-04).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.config import Settings, settings
from app.schemas.auth import (
    CurrentUser,
    GuestSessionResponse,
    SessionRecord,
    SessionResponse,
)
from app.security.oidc import OIDCClient
from app.security.tokens import InvalidSessionToken, SessionTokenCodec
from app.services.guest_upgrade import GuestUpgradeService
from app.services.oauth_state_store import OAuthStateRecord, OAuthStateStore
from app.services.session_store import SessionStore
from app.services.user_store import UserStore


class GuestAuthService:
    """Create anonymous guest sessions (Redis record + signed bearer JWT).

    Ports and the session TTL are injected at construction (via :meth:`from_settings`),
    matching the adapter convention — nothing reads the global ``settings`` in a method body.
    """

    def __init__(
        self,
        store: SessionStore,
        tokens: SessionTokenCodec,
        *,
        session_ttl_seconds: int,
    ) -> None:
        self._store = store
        self._tokens = tokens
        self._session_ttl_seconds = session_ttl_seconds

    @classmethod
    def from_settings(
        cls,
        store: SessionStore,
        tokens: SessionTokenCodec,
        config: Settings = settings,
    ) -> GuestAuthService:
        """Build from application config (guest session record TTL)."""
        return cls(
            store,
            tokens,
            session_ttl_seconds=config.GUEST_SESSION_TTL_SECONDS,
        )

    async def create_guest_session(self) -> GuestSessionResponse:
        """Start a guest session: mint a session id, persist a Redis record, sign a JWT.

        The ``session_id`` is a server-minted ``uuid4().hex`` (32 chars, within the 64-char
        ``sessions.id`` / ``ChatRequest.session_id`` bound). Nothing is written to Postgres —
        the guest is Redis-only by design (§4). The returned token carries ``role="guest"``
        so downstream request handling can distinguish a guest from a logged-in user.
        """
        session_id = uuid4().hex
        record = SessionRecord(
            session_id=session_id,
            role="guest",
            user_id=None,
            created_at=datetime.now(UTC),
        )
        await self._store.create(record, ttl_seconds=self._session_ttl_seconds)

        token = self._tokens.encode(sub=session_id, role="guest", session_id=session_id)
        return GuestSessionResponse(
            access_token=token,
            session_id=session_id,
            role="guest",
            expires_in=self._tokens.expires_in_seconds,
        )


class UnknownProvider(Exception):
    """Raised when a login/callback names a provider the app is not configured for.

    The API maps this to ``404 Not Found`` — the ``{provider}`` path segment simply is not a
    supported resource.
    """


class InvalidOAuthState(Exception):
    """Raised when a callback's ``state`` has no matching (or mismatched) pending record.

    Covers an expired/replayed/forged ``state`` and a provider that does not match the one
    the flow was started for. The API maps this to ``400 Bad Request``.
    """


class SsoAuthService:
    """The OIDC login flow (§7.1) — begin at the provider, complete into a session JWT.

    Ports are injected at construction (via :meth:`from_settings`): the
    :class:`~app.security.oidc.OIDCClient` (OAuth mechanics), the
    :class:`~app.services.oauth_state_store.OAuthStateStore` (the PKCE transaction spanning
    the two requests), the :class:`~app.services.user_store.UserStore` (upsert the ``users``
    row), the :class:`~app.services.session_store.SessionStore` (server-side session record)
    and the :class:`~app.security.tokens.SessionTokenCodec` (mint the bearer JWT).
    """

    def __init__(
        self,
        oidc: OIDCClient,
        states: OAuthStateStore,
        users: UserStore,
        sessions: SessionStore,
        tokens: SessionTokenCodec,
        *,
        redirect_base_url: str,
        state_ttl_seconds: int,
        session_ttl_seconds: int,
        providers: frozenset[str],
        upgrades: GuestUpgradeService | None = None,
    ) -> None:
        self._oidc = oidc
        self._states = states
        self._users = users
        self._sessions = sessions
        self._tokens = tokens
        self._redirect_base_url = redirect_base_url.rstrip("/")
        self._state_ttl_seconds = state_ttl_seconds
        self._session_ttl_seconds = session_ttl_seconds
        self._providers = providers
        # Optional (P3-03): when wired, a login carrying a valid upgrade ticket carries the
        # originating guest session over to the new account. ``None`` → plain login only.
        self._upgrades = upgrades

    @classmethod
    def from_settings(
        cls,
        oidc: OIDCClient,
        states: OAuthStateStore,
        users: UserStore,
        sessions: SessionStore,
        tokens: SessionTokenCodec,
        config: Settings = settings,
        *,
        upgrades: GuestUpgradeService | None = None,
    ) -> SsoAuthService:
        """Build from application config (redirect base, TTLs, supported providers)."""
        return cls(
            oidc,
            states,
            users,
            sessions,
            tokens,
            redirect_base_url=config.OAUTH_REDIRECT_BASE_URL,
            state_ttl_seconds=config.OAUTH_STATE_TTL_SECONDS,
            session_ttl_seconds=config.USER_SESSION_TTL_SECONDS,
            providers=frozenset(config.OAUTH_METADATA_URLS),
            upgrades=upgrades,
        )

    def _redirect_uri(self, provider: str) -> str:
        """Derive the provider callback URI from config (never hard-coded, §7.1).

        Locked to the deployed domain: ``<OAUTH_REDIRECT_BASE_URL>/api/auth/callback/
        {provider}`` — the exact value that must be registered in the provider console.
        """
        return f"{self._redirect_base_url}/api/auth/callback/{provider}"

    def _require_known_provider(self, provider: str) -> None:
        if provider not in self._providers:
            raise UnknownProvider(provider)

    async def begin_login(self, provider: str, *, upgrade_ticket: str | None = None) -> str:
        """Start the OIDC flow: return the provider consent URL to redirect the user to.

        Builds a PKCE authorization request and persists the per-attempt transaction (state
        → verifier + nonce + redirect_uri) so the callback can complete it. The ``state``
        both keys the transaction and is the CSRF token echoed back by the provider.

        When ``upgrade_ticket`` is supplied (a guest→account upgrade, P3-03) and the upgrade
        service is wired, the ticket is **consumed** here (single-use) and the guest session
        id it authorizes is stashed *server-side* in the transaction — so the callback can
        carry that guest session over to the new account. An unknown/expired ticket simply
        yields a plain login (no carry-over), never an error.
        """
        self._require_known_provider(provider)
        upgrade_session_id: str | None = None
        if upgrade_ticket and self._upgrades is not None:
            upgrade_session_id = await self._upgrades.resolve_ticket(upgrade_ticket)
        redirect_uri = self._redirect_uri(provider)
        request = await self._oidc.create_authorization_request(
            provider=provider, redirect_uri=redirect_uri
        )
        await self._states.put(
            request.state,
            OAuthStateRecord(
                provider=provider,
                code_verifier=request.code_verifier,
                nonce=request.nonce,
                redirect_uri=redirect_uri,
                created_at=datetime.now(UTC),
                upgrade_session_id=upgrade_session_id,
            ),
            ttl_seconds=self._state_ttl_seconds,
        )
        return request.url

    async def complete_login(self, provider: str, *, code: str, state: str) -> SessionResponse:
        """Finish the OIDC flow: verify state, exchange the code, mint a user session.

        Consumes the pending transaction (single-use), exchanges the authorization ``code``
        with the stored PKCE verifier, upserts the ``users`` row from the verified claims
        (no password ever stored, §7.1), records a server-side session, and mints the
        short-lived bearer JWT (``role="user"``, ``sub=users.id``).
        """
        self._require_known_provider(provider)
        record = await self._states.pop(state)
        if record is None or record.provider != provider:
            # Unknown/expired/replayed state, or a state minted for a different provider.
            raise InvalidOAuthState(state)

        userinfo = await self._oidc.exchange_code(
            provider=provider,
            redirect_uri=record.redirect_uri,
            code=code,
            code_verifier=record.code_verifier,
        )
        account = await self._users.upsert(
            provider=userinfo.provider,
            sub=userinfo.sub,
            email=userinfo.email,
            display_name=userinfo.display_name,
        )

        session_id = await self._resolve_session(record.upgrade_session_id, account.id)
        token = self._tokens.encode(sub=account.id, role="user", session_id=session_id)
        return SessionResponse(
            access_token=token,
            session_id=session_id,
            role="user",
            expires_in=self._tokens.expires_in_seconds,
        )

    async def _resolve_session(self, upgrade_session_id: str | None, user_id: str) -> str:
        """Return the ``session_id`` for this login — the upgraded guest one, or a fresh one.

        A guest→account upgrade (P3-03) carries the *originating* guest session over so the
        user lands back in the same conversation: when ``upgrade_session_id`` is present and
        the upgrade succeeds, that same id is kept (the upgrade service has already promoted
        its record + backfilled its history). Otherwise — a plain login, no upgrade wired, or
        the guest session lapsed before callback — a fresh session record is minted, the
        unchanged P3-02 behavior.
        """
        if upgrade_session_id is not None and self._upgrades is not None:
            upgraded = await self._upgrades.upgrade(
                guest_session_id=upgrade_session_id,
                user_id=user_id,
                session_ttl_seconds=self._session_ttl_seconds,
            )
            if upgraded:
                return upgrade_session_id

        session_id = uuid4().hex
        await self._sessions.create(
            SessionRecord(
                session_id=session_id,
                role="user",
                user_id=user_id,
                created_at=datetime.now(UTC),
            ),
            ttl_seconds=self._session_ttl_seconds,
        )
        return session_id


class SessionAuthenticator:
    """Verify a bearer token + live session record and resolve the caller (§7.1).

    The reusable auth primitive behind the ``require_auth`` FastAPI dependency. It checks
    both that the JWT is validly signed and unexpired **and** that its session record still
    exists — so ``POST /api/auth/logout`` (which deletes the record) revokes a session
    immediately without a token denylist, at the cost of one store read per request (the
    accepted tradeoff, given a short JWT TTL as the backstop).
    """

    def __init__(self, tokens: SessionTokenCodec, sessions: SessionStore) -> None:
        self._tokens = tokens
        self._sessions = sessions

    @classmethod
    def from_deps(cls, tokens: SessionTokenCodec, sessions: SessionStore) -> SessionAuthenticator:
        """Build from the shared codec + session store (composition-root wiring)."""
        return cls(tokens, sessions)

    async def authenticate(self, token: str) -> CurrentUser:
        """Resolve ``token`` to a :class:`CurrentUser` or raise :class:`InvalidSessionToken`.

        Raises :class:`~app.security.tokens.InvalidSessionToken` on a bad signature, an
        expired token, malformed claims, **or** a session whose record no longer exists
        (logged out / lapsed) — the API maps all of these to ``401``.
        """
        claims = self._tokens.decode(token)
        record = await self._sessions.get(claims.sid)
        if record is None:
            raise InvalidSessionToken("session ended")
        user_id = claims.sub if claims.role == "user" else None
        return CurrentUser(session_id=claims.sid, role=claims.role, user_id=user_id)

    async def end_session(self, session_id: str) -> None:
        """Delete the session record for ``session_id`` (logout; idempotent)."""
        await self._sessions.delete(session_id)
