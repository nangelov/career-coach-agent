"""Unit tests for the user-account store port (P3-02).

Covers the process-local :class:`~app.services.user_store.InMemoryUserStore` upsert contract
the SSO service depends on: a first login creates a stable id, a return login for the same
``(provider, sub)`` reuses that id while refreshing the mutable PII, and distinct identities
get distinct ids.
"""

from __future__ import annotations

from app.services.user_store import InMemoryUserStore


async def test_first_upsert_creates_account() -> None:
    store = InMemoryUserStore()

    account = await store.upsert(
        provider="google", sub="sub-1", email="a@example.com", display_name="A"
    )

    assert account.id
    assert account.provider == "google"
    assert account.sub == "sub-1"
    assert account.email == "a@example.com"
    assert account.display_name == "A"


async def test_return_login_reuses_id_and_updates_pii() -> None:
    store = InMemoryUserStore()
    first = await store.upsert(
        provider="google", sub="sub-1", email="old@example.com", display_name="Old"
    )

    second = await store.upsert(
        provider="google", sub="sub-1", email="new@example.com", display_name="New"
    )

    # Same identity → same durable id, refreshed email/name.
    assert second.id == first.id
    assert second.email == "new@example.com"
    assert second.display_name == "New"


async def test_distinct_identities_get_distinct_ids() -> None:
    store = InMemoryUserStore()

    google = await store.upsert(
        provider="google", sub="sub-1", email="a@example.com", display_name=None
    )
    linkedin = await store.upsert(
        provider="linkedin", sub="sub-1", email="a@example.com", display_name=None
    )

    # Same sub on different providers is a different account.
    assert google.id != linkedin.id


async def test_is_admin_reflects_granted_ids() -> None:
    # Admin (P3-05) is granted out-of-band; the in-memory double models it via ``admin_ids``.
    store = InMemoryUserStore()
    assert await store.is_admin("u1") is False  # fail-closed default

    store.admin_ids.add("u1")
    assert await store.is_admin("u1") is True
    assert await store.is_admin("u2") is False  # unknown id → not admin
