"""Unit tests for the SSO login service (P3-02).

Drives :class:`~app.services.auth.SsoAuthService` with the process-local stores + a scripted
:class:`~tests.fakes.FakeOIDCClient` (no network). Coverage mirrors the acceptance criteria:
``begin_login`` builds a config-derived redirect URI and persists the PKCE transaction;
``complete_login`` verifies state, exchanges the code, upserts the user (no password), mints
a ``role="user"`` bearer token, and creates a session record; unknown provider / bad state /
provider-mismatch are rejected.
"""

from __future__ import annotations

import pytest

from app.security.tokens import SessionTokenCodec
from app.services.auth import (
    ConsentRequired,
    InvalidOAuthState,
    SsoAuthService,
    UnknownProvider,
)
from app.services.oauth_state_store import InMemoryOAuthStateStore
from app.services.session_store import InMemorySessionStore
from app.services.user_store import InMemoryUserStore
from tests.fakes import FakeOIDCClient

_SECRET = "sso-service-test-secret"
_BASE_URL = "https://app.example"
_POLICY = "2026-07-13"


def _service(
    *,
    oidc: FakeOIDCClient | None = None,
    states: InMemoryOAuthStateStore | None = None,
    users: InMemoryUserStore | None = None,
    sessions: InMemorySessionStore | None = None,
    consent_policy_version: str = _POLICY,
) -> SsoAuthService:
    return SsoAuthService(
        oidc or FakeOIDCClient(),
        states or InMemoryOAuthStateStore(),
        users or InMemoryUserStore(),
        sessions or InMemorySessionStore(),
        SessionTokenCodec(secret=_SECRET, expire_minutes=60),
        redirect_base_url=_BASE_URL,
        state_ttl_seconds=600,
        session_ttl_seconds=3600,
        providers=frozenset({"google", "linkedin"}),
        consent_policy_version=consent_policy_version,
    )


async def test_begin_login_returns_consent_url_and_persists_transaction() -> None:
    oidc = FakeOIDCClient()
    states = InMemoryOAuthStateStore()
    service = _service(oidc=oidc, states=states)

    url = await service.begin_login("google", consent=True)

    assert url.startswith("https://provider.example/consent")
    # Redirect URI is derived from config, not hard-coded per provider (§7.1).
    provider, redirect_uri = oidc.authorization_requests[0]
    assert provider == "google"
    assert redirect_uri == "https://app.example/api/auth/callback/google"
    # The PKCE transaction was stored under the returned state (single-use).
    record = await states.pop("state-1")
    assert record is not None
    assert record.provider == "google"
    assert record.code_verifier == "verifier-1"
    # The accepted consent policy version is threaded into the transaction (§6.22).
    assert record.consent_policy_version == _POLICY


async def test_begin_login_without_consent_is_rejected() -> None:
    states = InMemoryOAuthStateStore()
    service = _service(states=states)
    with pytest.raises(ConsentRequired):
        await service.begin_login("google", consent=False)
    # No transaction was stored (rejected before the provider redirect, §6.22).
    assert await states.pop("state-1") is None


async def test_begin_login_unknown_provider_raises() -> None:
    with pytest.raises(UnknownProvider):
        await _service().begin_login("myspace", consent=True)


async def test_complete_login_mints_user_session() -> None:
    oidc = FakeOIDCClient()
    states = InMemoryOAuthStateStore()
    users = InMemoryUserStore()
    sessions = InMemorySessionStore()
    service = _service(oidc=oidc, states=states, users=users, sessions=sessions)

    await service.begin_login("google", consent=True)
    session = await service.complete_login("google", code="auth-code", state="state-1")

    assert session.token_type == "bearer"
    assert session.role == "user"
    assert session.expires_in == 3600
    # The code exchange used the stored PKCE verifier.
    assert oidc.exchanges[0]["code"] == "auth-code"
    assert oidc.exchanges[0]["code_verifier"] == "verifier-1"

    # A session record was persisted for the resolved user.
    record = await sessions.get(session.session_id)
    assert record is not None
    assert record.role == "user"
    assert record.user_id is not None

    # Consent (§6.22) was recorded against the user row: version + a timestamp.
    account = users._by_identity[("google", "sub-123")]  # type: ignore[attr-defined]
    assert account.consent_policy_version == _POLICY
    assert account.consent_accepted_at is not None

    # The bearer token names the user (sub == users.id), not the session.
    claims = SessionTokenCodec(secret=_SECRET).decode(session.access_token)
    assert claims.role == "user"
    assert claims.sub == record.user_id
    assert claims.sid == session.session_id


async def test_complete_login_records_current_policy_on_returning_stale_user() -> None:
    # A returning user whose stored consent is stale gets re-recorded on next login (§6.22).
    # One shared OIDC client + state store spans both logins (so state ids don't collide).
    users = InMemoryUserStore()
    oidc = FakeOIDCClient()
    states = InMemoryOAuthStateStore()

    # First login under an old policy version.
    old = _service(oidc=oidc, states=states, users=users, consent_policy_version="2025-01-01")
    await old.begin_login("google", consent=True)
    await old.complete_login("google", code="c1", state="state-1")
    assert (
        users._by_identity[("google", "sub-123")].consent_policy_version  # type: ignore[attr-defined]
        == "2025-01-01"
    )

    # Next login under the bumped policy re-records the current version (same identity).
    current = _service(oidc=oidc, states=states, users=users, consent_policy_version="2026-07-13")
    await current.begin_login("google", consent=True)
    await current.complete_login("google", code="c2", state="state-2")
    assert (
        users._by_identity[("google", "sub-123")].consent_policy_version  # type: ignore[attr-defined]
        == "2026-07-13"
    )


async def test_complete_login_is_idempotent_on_returning_user() -> None:
    users = InMemoryUserStore()
    service = _service(users=users)

    await service.begin_login("google", consent=True)
    first = await service.complete_login("google", code="c1", state="state-1")
    await service.begin_login("google", consent=True)
    second = await service.complete_login("google", code="c2", state="state-2")

    a = SessionTokenCodec(secret=_SECRET).decode(first.access_token)
    b = SessionTokenCodec(secret=_SECRET).decode(second.access_token)
    # Same OIDC identity → same durable users.id, but a fresh session each login.
    assert a.sub == b.sub
    assert a.sid != b.sid


async def test_complete_login_rejects_unknown_state() -> None:
    service = _service()
    with pytest.raises(InvalidOAuthState):
        await service.complete_login("google", code="c", state="never-issued")


async def test_complete_login_rejects_provider_mismatch() -> None:
    service = _service()
    # State was issued for google; replaying it on the linkedin callback must fail.
    await service.begin_login("google", consent=True)
    with pytest.raises(InvalidOAuthState):
        await service.complete_login("linkedin", code="c", state="state-1")


async def test_complete_login_state_is_single_use() -> None:
    service = _service()
    await service.begin_login("google", consent=True)
    await service.complete_login("google", code="c", state="state-1")
    # Replaying the same state must fail (transaction consumed).
    with pytest.raises(InvalidOAuthState):
        await service.complete_login("google", code="c", state="state-1")
