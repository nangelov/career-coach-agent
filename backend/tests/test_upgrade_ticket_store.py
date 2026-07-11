"""Unit tests for the guest→account upgrade-ticket store port (P3-03).

Exercises the process-local :class:`~app.services.upgrade_ticket_store.InMemoryUpgradeTicketStore`
against the port contract the Redis adapter also satisfies: a ticket resolves once and only
once (single-use), an unknown/consumed ticket resolves to ``None``, and distinct tickets do
not collide.
"""

from __future__ import annotations

from app.services.upgrade_ticket_store import InMemoryUpgradeTicketStore


async def test_put_then_pop_returns_guest_session_id() -> None:
    store = InMemoryUpgradeTicketStore()
    await store.put("ticket-1", "guest-abc", ttl_seconds=300)

    assert await store.pop("ticket-1") == "guest-abc"


async def test_pop_is_single_use() -> None:
    store = InMemoryUpgradeTicketStore()
    await store.put("ticket-1", "guest-abc", ttl_seconds=300)

    assert await store.pop("ticket-1") == "guest-abc"
    # A replayed ticket cannot authorize a second upgrade.
    assert await store.pop("ticket-1") is None


async def test_pop_unknown_ticket_returns_none() -> None:
    store = InMemoryUpgradeTicketStore()
    assert await store.pop("never-issued") is None


async def test_distinct_tickets_do_not_collide() -> None:
    store = InMemoryUpgradeTicketStore()
    await store.put("ticket-a", "guest-a", ttl_seconds=300)
    await store.put("ticket-b", "guest-b", ttl_seconds=300)

    assert await store.pop("ticket-b") == "guest-b"
    assert await store.pop("ticket-a") == "guest-a"
