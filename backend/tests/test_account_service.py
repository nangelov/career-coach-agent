"""Unit tests for :class:`~app.services.account.AccountService` (SEC-05, §7.6).

Drives the service over the in-memory fakes (:class:`InMemoryAccountRepository` +
:class:`~app.services.session_store.InMemorySessionStore`) so no real Postgres/Redis runs.
Asserts the erasure contract: every one of the user's live Redis sessions is revoked (all
devices), the Postgres delete is invoked, the operation is idempotent on an unknown user, and
export is a straight passthrough of the repository's scoped document.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.account import AccountExport
from app.schemas.auth import SessionRecord
from app.services.account import AccountService, InMemoryAccountRepository
from app.services.session_store import InMemorySessionStore


async def _seed_session(store: InMemorySessionStore, session_id: str, user_id: str) -> None:
    await store.create(
        SessionRecord(
            session_id=session_id,
            role="user",
            user_id=user_id,
            created_at=datetime.now(UTC),
        ),
        ttl_seconds=3600,
    )


async def test_erase_revokes_all_sessions_and_deletes_user() -> None:
    repo = InMemoryAccountRepository()
    store = InMemorySessionStore()
    await _seed_session(store, "s1", "u1")
    await _seed_session(store, "s2", "u1")
    # A different user's session must be left untouched.
    await _seed_session(store, "other", "u2")

    service = AccountService(repo, store)
    await service.erase("u1")

    # Every one of u1's live sessions is revoked (all devices), not just the caller's.
    assert await store.get("s1") is None
    assert await store.get("s2") is None
    # Another user's session is unaffected.
    assert await store.get("other") is not None
    # The Postgres delete was invoked for u1.
    assert repo.deleted == ["u1"]


async def test_erase_is_idempotent_on_unknown_user() -> None:
    repo = InMemoryAccountRepository()
    store = InMemorySessionStore()
    service = AccountService(repo, store)

    # No sessions, no data — must not raise, just a no-op delete.
    await service.erase("ghost")
    await service.erase("ghost")

    assert repo.deleted == ["ghost", "ghost"]


async def test_export_passes_through_repository_document() -> None:
    repo = InMemoryAccountRepository()
    store = InMemorySessionStore()
    doc = AccountExport(user={"id": "u1", "email": "u1@example.com"}, goals=[{"title": "Staff"}])
    repo.exports_by_user["u1"] = doc

    service = AccountService(repo, store)
    result = await service.export("u1")

    assert result is doc
    assert result.user == {"id": "u1", "email": "u1@example.com"}


async def test_export_unknown_user_is_empty() -> None:
    service = AccountService(InMemoryAccountRepository(), InMemorySessionStore())
    result = await service.export("nobody")
    assert result == AccountExport()
