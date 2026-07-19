"""Guest personalization store seam — session-only, Redis-backed (P9-07, design §5.4).

A **guest** (``user_id is None``) gets the same *within-conversation* adaptation a logged-in
user gets from the recall/learn loop (P9-02/03), but **ephemeral**: it lives only in Redis,
keyed by ``session_id``, TTL-bounded to the guest session lifetime, and is **never** written to
the durable Postgres ``preferences`` / ``user_memories`` stores — until the guest upgrades to an
account, at which point :mod:`app.memory.guest_personalization` migrates it across (§5.4:
*"Guests: personalization is session-only (Redis, ephemeral) — nothing durable is learned
without an account; upgrading persists it."*).

This is a deliberately **separate** seam from :class:`~app.services.session_memory.SessionMemory`
(which holds the conversation *transcript*): overloading that store with personalization state
would conflate two concerns. It follows the same interface-before-implementation idiom as the
sibling stores (``SessionMemory`` / ``SessionStore`` / ``UpgradeTicketStore``): this module
defines the narrow port + a process-local test double; the **Redis-backed** implementation
(:class:`~app.repositories.redis.RedisGuestMemory`) lives in the repository layer, so services
depend only on the ABC and never touch a Redis driver directly (§8 layering).

The stored shape (:class:`GuestPersonalization`) mirrors :class:`~app.agents.state.MemoryContext`
(explicit-preference-like ``preferences`` + a bounded list of learned-memory ``memories``) so the
recall step can hand it straight to the responder without a shape change (§5.4).

.. warning::
   :class:`InMemoryGuestMemory` keeps state in a process-local dict with no real TTL expiry — a
   test double only, not production (lost on restart, not shared across workers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field


class GuestPersonalization(BaseModel):
    """A guest's ephemeral, session-only personalization (P9-07, §5.4).

    Same shape as :class:`~app.agents.state.MemoryContext`: ``preferences`` are explicit,
    setting-like key/values; ``memories`` is the bounded, ordered list of learned-memory strings
    (already PII-redacted / Art. 9-filtered before they land here — see
    :mod:`app.memory.guest_personalization`). Pydantic so it round-trips through Redis as JSON.
    """

    preferences: dict[str, Any] = Field(default_factory=dict)
    memories: list[str] = Field(default_factory=list)


class GuestMemory(ABC):
    """Load / update a guest's Redis-only personalization, keyed by ``session_id``.

    Implementations own storage (process-local here, Redis in the repository layer) and the TTL /
    bound; callers (recall, guest-learn, upgrade migration) depend only on this interface.
    """

    @abstractmethod
    async def load(self, session_id: str) -> GuestPersonalization:
        """Return the stored personalization for ``session_id`` (empty if none / expired)."""

    @abstractmethod
    async def record(
        self,
        session_id: str,
        *,
        memories: Sequence[str] = (),
        preferences: Mapping[str, Any] | None = None,
    ) -> GuestPersonalization:
        """Merge ``preferences`` and append ``memories`` for ``session_id``; return the new state.

        One read-modify-write: ``preferences`` are shallow-merged over the existing dict; each of
        ``memories`` is appended (de-duplicated case-insensitively — an already-known memory is
        ignored, keeping its original position/casing) and the list is capped to the
        implementation's bound (oldest dropped first). The write refreshes the key's TTL (sliding,
        so an active guest's personalization stays warm and an idle one lapses).
        """


class InMemoryGuestMemory(GuestMemory):
    """Process-local :class:`GuestMemory` — test double only (no restart survival, no real TTL).

    An optional ``max_memories`` cap mirrors the Redis store so a test can exercise the bound.
    """

    def __init__(self, *, max_memories: int = 50) -> None:
        self._store: dict[str, GuestPersonalization] = {}
        self._max_memories = max(1, max_memories)

    async def load(self, session_id: str) -> GuestPersonalization:
        current = self._store.get(session_id)
        return current.model_copy(deep=True) if current is not None else GuestPersonalization()

    async def record(
        self,
        session_id: str,
        *,
        memories: Sequence[str] = (),
        preferences: Mapping[str, Any] | None = None,
    ) -> GuestPersonalization:
        current = self._store.get(session_id) or GuestPersonalization()
        merged_prefs = {**current.preferences, **(preferences or {})}
        merged_memories = _merge_memories(current.memories, memories, self._max_memories)
        updated = GuestPersonalization(preferences=merged_prefs, memories=merged_memories)
        self._store[session_id] = updated
        return updated.model_copy(deep=True)


def _merge_memories(existing: Sequence[str], incoming: Sequence[str], cap: int) -> list[str]:
    """Append ``incoming`` to ``existing``, de-dupe case-insensitively (first wins), cap length.

    The **first** occurrence of a memory wins — an already-known memory is ignored rather than
    re-added, so insertion order and original casing are stable — and only the most recent ``cap``
    are kept (oldest dropped first) so the ephemeral list stays bounded. Shared by the in-memory
    and Redis stores so both bound identically.
    """
    ordered: dict[str, str] = {}
    for text in (*existing, *incoming):
        cleaned = text.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key not in ordered:
            ordered[key] = cleaned
    return list(ordered.values())[-max(1, cap) :]
