"""Unit tests for the session authenticator (P3-02) — verify, resolve, revoke.

Covers :class:`~app.services.auth.SessionAuthenticator`: a valid bearer token over a live
session record resolves to the right :class:`~app.schemas.auth.CurrentUser` (user vs guest
mapping), an expired/forged token is rejected, and ``end_session`` (logout) revokes
immediately — a still-unexpired token stops resolving once its record is deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.auth import SessionRecord, SessionRole
from app.security.tokens import InvalidSessionToken, SessionTokenCodec
from app.services.auth import SessionAuthenticator
from app.services.session_store import InMemorySessionStore

_SECRET = "authenticator-test-secret"


async def _seed_session(
    store: InMemorySessionStore, *, session_id: str, role: SessionRole, user_id: str | None
) -> None:
    await store.create(
        SessionRecord(
            session_id=session_id,
            role=role,
            user_id=user_id,
            created_at=datetime.now(UTC),
        ),
        ttl_seconds=3600,
    )


async def test_authenticates_user_token() -> None:
    store = InMemorySessionStore()
    codec = SessionTokenCodec(secret=_SECRET, expire_minutes=60)
    await _seed_session(store, session_id="sid-1", role="user", user_id="user-1")
    token = codec.encode(sub="user-1", role="user", session_id="sid-1")

    current = await SessionAuthenticator(codec, store).authenticate(token)

    assert current.role == "user"
    assert current.user_id == "user-1"
    assert current.session_id == "sid-1"


async def test_authenticates_guest_token_with_no_user_id() -> None:
    store = InMemorySessionStore()
    codec = SessionTokenCodec(secret=_SECRET, expire_minutes=60)
    await _seed_session(store, session_id="sid-g", role="guest", user_id=None)
    token = codec.encode(sub="sid-g", role="guest", session_id="sid-g")

    current = await SessionAuthenticator(codec, store).authenticate(token)

    assert current.role == "guest"
    assert current.user_id is None
    assert current.session_id == "sid-g"


async def test_rejects_expired_token() -> None:
    store = InMemorySessionStore()
    await _seed_session(store, session_id="sid-1", role="user", user_id="user-1")
    expired = SessionTokenCodec(secret=_SECRET, expire_minutes=-1).encode(
        sub="user-1", role="user", session_id="sid-1"
    )

    with pytest.raises(InvalidSessionToken):
        await SessionAuthenticator(SessionTokenCodec(secret=_SECRET), store).authenticate(expired)


async def test_rejects_token_signed_with_wrong_key() -> None:
    store = InMemorySessionStore()
    await _seed_session(store, session_id="sid-1", role="user", user_id="user-1")
    forged = SessionTokenCodec(secret="a-different-signing-secret-value").encode(
        sub="user-1", role="user", session_id="sid-1"
    )

    with pytest.raises(InvalidSessionToken):
        await SessionAuthenticator(SessionTokenCodec(secret=_SECRET), store).authenticate(forged)


async def test_logout_revokes_a_valid_token() -> None:
    store = InMemorySessionStore()
    codec = SessionTokenCodec(secret=_SECRET, expire_minutes=60)
    await _seed_session(store, session_id="sid-1", role="user", user_id="user-1")
    authenticator = SessionAuthenticator(codec, store)
    token = codec.encode(sub="user-1", role="user", session_id="sid-1")

    # Valid before logout...
    assert (await authenticator.authenticate(token)).user_id == "user-1"

    await authenticator.end_session("sid-1")

    # ...and rejected after, even though the JWT itself has not expired.
    with pytest.raises(InvalidSessionToken):
        await authenticator.authenticate(token)
