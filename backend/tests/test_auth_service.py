"""Unit tests for the guest auth service (P3-01).

Drives :class:`~app.services.auth.GuestAuthService` with the process-local
``InMemorySessionStore`` and the real :class:`~app.security.tokens.SessionTokenCodec` (a
pure primitive, no I/O). Coverage mirrors the acceptance criteria: a session record is
created with the configured TTL, the response carries a decodable guest bearer token whose
claims match the session, and two guest sessions get distinct ids/tokens.
"""

from __future__ import annotations

from app.security.tokens import SessionTokenCodec
from app.services.auth import GuestAuthService
from app.services.session_store import InMemorySessionStore

_SECRET = "auth-service-test-secret"


def _service(store: InMemorySessionStore, *, ttl: int = 3600) -> GuestAuthService:
    codec = SessionTokenCodec(secret=_SECRET, expire_minutes=60)
    return GuestAuthService(store, codec, session_ttl_seconds=ttl)


async def test_create_guest_session_persists_record() -> None:
    store = InMemorySessionStore()
    service = _service(store)

    response = await service.create_guest_session()

    stored = await store.get(response.session_id)
    assert stored is not None
    assert stored.role == "guest"
    assert stored.user_id is None


async def test_response_carries_a_decodable_guest_token() -> None:
    store = InMemorySessionStore()
    service = _service(store)

    response = await service.create_guest_session()

    assert response.token_type == "bearer"
    assert response.role == "guest"
    assert response.expires_in == 3600  # 60 minutes

    claims = SessionTokenCodec(secret=_SECRET).decode(response.access_token)
    assert claims.role == "guest"
    assert claims.sid == response.session_id
    assert claims.sub == response.session_id


async def test_two_guest_sessions_are_distinct() -> None:
    store = InMemorySessionStore()
    service = _service(store)

    a = await service.create_guest_session()
    b = await service.create_guest_session()

    assert a.session_id != b.session_id
    assert a.access_token != b.access_token


async def test_session_id_fits_persistence_bound() -> None:
    # uuid4().hex is 32 chars — within the 64-char sessions.id / ChatRequest.session_id bound.
    response = await _service(InMemorySessionStore()).create_guest_session()
    assert 1 <= len(response.session_id) <= 64
