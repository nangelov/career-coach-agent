"""Unit tests for the pending-OIDC-transaction store port (P3-02).

Covers the process-local :class:`~app.services.oauth_state_store.InMemoryOAuthStateStore`
contract the auth service depends on: a stored transaction round-trips, ``pop`` is
single-use (a replayed ``state`` cannot complete a second login), and an unknown ``state``
returns ``None``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.oauth_state_store import InMemoryOAuthStateStore, OAuthStateRecord


def _record(provider: str = "google") -> OAuthStateRecord:
    return OAuthStateRecord(
        provider=provider,
        code_verifier="verifier-abc",
        nonce="nonce-xyz",
        redirect_uri="http://localhost:8000/api/auth/callback/google",
        created_at=datetime.now(UTC),
    )


async def test_put_then_pop_round_trips() -> None:
    store = InMemoryOAuthStateStore()
    record = _record()

    await store.put("state-1", record, ttl_seconds=600)
    popped = await store.pop("state-1")

    assert popped is not None
    assert popped.provider == "google"
    assert popped.code_verifier == "verifier-abc"
    assert popped.nonce == "nonce-xyz"


async def test_pop_is_single_use() -> None:
    store = InMemoryOAuthStateStore()
    await store.put("state-1", _record(), ttl_seconds=600)

    assert await store.pop("state-1") is not None
    # A second pop for the same state must miss — the transaction is consumed.
    assert await store.pop("state-1") is None


async def test_pop_unknown_state_returns_none() -> None:
    store = InMemoryOAuthStateStore()
    assert await store.pop("never-issued") is None
