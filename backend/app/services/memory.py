"""Memory-panel service — view/edit explicit prefs + view/delete learned memories (P9-05, §5.4).

The **policy** layer behind the thin ``/api/memory`` router (Router → Service → Repository, §8):
it owns the transparency-&-control business logic so the router stays HTTP-only. This is the
opt-out surface §6.10 decided on — learned memory is applied silently (recall, P9-02) but is
**viewable and deletable** here, with **no per-fact confirmation workflow** (deletes and
preference edits are immediate).

It composes two data-access seams:

* :class:`~app.services.preferences.PreferenceStore` — the explicit, authoritative
  ``preferences`` document (§5.4 point 4: explicit edits override inferred memories);
* a :class:`LearnedMemoryStore` — the inferred ``user_memories`` rows (satisfied in production by
  :class:`~app.memory.store.UserMemoryStore`, whose typed list/delete/clear methods P9-05 reuses).

The service owns the validate/serialize boundary for preferences (typed
:class:`~app.schemas.memory.Preferences` ⇄ stored ``dict``) and the ``str → UUID`` parse for the
memory store, so both stores stay thin. Every method is caller-scoped: the ``user_id`` is always
the verified token subject (the router rejects guests before calling here).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.repositories.vector_search import UserMemoryListItem
from app.schemas.memory import LearnedMemory, MemoryView, Preferences
from app.services.preferences import PreferenceStore

__all__ = ["LearnedMemoryStore", "MemoryService"]


class LearnedMemoryStore(Protocol):
    """The learned-``user_memories`` capability the panel needs (structural, DIP-clean).

    A :class:`~typing.Protocol` (not a hard import of the concrete
    :class:`~app.memory.store.UserMemoryStore`) so the service depends on a *capability*, not a
    class — the production store satisfies it and unit tests inject a fake, mirroring the RAG
    worker's ``SessionProvider`` seam.
    """

    async def list_memories(self, user_id: uuid.UUID) -> list[UserMemoryListItem]: ...

    async def delete_memory_for_user(self, memory_id: uuid.UUID, user_id: uuid.UUID) -> bool: ...

    async def clear_memories(self, user_id: uuid.UUID) -> int: ...


class MemoryService:
    """View/edit preferences + view/delete learned memories over the two stores (§8 layering)."""

    def __init__(self, *, preferences: PreferenceStore, memories: LearnedMemoryStore) -> None:
        self._preferences = preferences
        self._memories = memories

    @staticmethod
    def _as_uuid(value: str) -> uuid.UUID | None:
        """Parse ``value`` to a UUID, or ``None`` if malformed (fail-safe)."""
        try:
            return uuid.UUID(value)
        except ValueError:
            return None

    async def view(self, user_id: str) -> MemoryView:
        """Return the caller's explicit preferences + their learned memories (``GET /api/memory``).

        Preferences are validated back through :class:`Preferences` (an empty/absent row → an
        empty model, so the panel always renders); memories are the newest-first list with
        embeddings excluded. A malformed ``user_id`` yields no memories rather than raising.
        """
        prefs_data = await self._preferences.get(user_id)
        preferences = Preferences.model_validate_lenient(prefs_data)
        uid = self._as_uuid(user_id)
        items = await self._memories.list_memories(uid) if uid is not None else []
        return MemoryView(
            preferences=preferences,
            memories=[
                LearnedMemory(
                    id=str(item.memory_id),
                    text=item.text,
                    memory_type=item.memory_type,
                    confidence=item.confidence,
                    created_at=item.created_at,
                )
                for item in items
            ],
        )

    async def update_preferences(self, user_id: str, preferences: Preferences) -> Preferences:
        """Upsert the caller's explicit preferences (``PUT /api/memory/preferences``).

        Replaces the whole ``preferences.data`` document with the validated body (immediate — no
        confirmation workflow, §6.10). Returns the stored settings, re-validated through
        :class:`Preferences` for a consistent response shape.
        """
        stored = await self._preferences.upsert(user_id, preferences.model_dump())
        return Preferences.model_validate_lenient(stored)

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """Delete one of the caller's learned memories (``DELETE /api/memory/{memory_id}``).

        Ownership-scoped: a memory id that is unknown, malformed, *or* belongs to another user
        returns ``False`` (the router maps it to a uniform ``404`` — no ownership leak).
        """
        uid = self._as_uuid(user_id)
        mid = self._as_uuid(memory_id)
        if uid is None or mid is None:
            return False
        return await self._memories.delete_memory_for_user(mid, uid)

    async def clear_memories(self, user_id: str) -> int:
        """Delete **all** the caller's learned memories, returning the count (bulk clear).

        The "forget everything you've learned about me" action — leaves explicit ``preferences``
        untouched (a separate, user-authored thing). A malformed ``user_id`` clears nothing.
        """
        uid = self._as_uuid(user_id)
        if uid is None:
            return 0
        return await self._memories.clear_memories(uid)
