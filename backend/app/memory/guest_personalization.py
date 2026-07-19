"""Guest personalization: ephemeral Redis learn + upgrade-time migration (P9-07, design §5.4).

The guest counterpart to the logged-in teachable-memory loop (:mod:`app.memory.learn`), split
into the two write-side halves a guest needs:

* :class:`GuestPersonalizationLearner` — the **post-turn learn** step. It reuses the *same*
  extractor (:class:`~app.memory.learn.MemoryExtractor`) and the *same* PII / GDPR Art. 9 gate
  (:func:`~app.memory.learn.gate_candidate`) the logged-in path uses, then writes the surviving
  memory strings to the **Redis-only** :class:`~app.services.guest_memory.GuestMemory` store —
  never Postgres. Even though the store is ephemeral, the gate still runs (§7.6): a career coach
  may hear Art.-9-adjacent things "usable within the turn only", but they must not accumulate into
  a running memory list. Deliberately simpler than the durable learn pass — no similarity dedup
  (the store de-dupes by text), no confidence bookkeeping, no thumb-down demotion (a guest has no
  durable ``message_feedback``).

* :class:`GuestPersonalizationMigrator` — the **upgrade-to-account** step. On a successful
  guest→account upgrade (:mod:`app.services.guest_upgrade`) it reads the guest's Redis
  personalization and writes it durably: ``preferences`` → the user's ``preferences`` row;
  ``memories`` → :meth:`~app.memory.store.UserMemoryStore.add_memory`, each string passing through
  the **same** :func:`~app.memory.learn.gate_candidate` again (defense-in-depth — an ephemeral
  memory is not durably persisted unfiltered just because it was already in Redis). Then the Redis
  copy is left to expire naturally, mirroring the transcript-backfill posture.

Both halves are **fail-soft**: guest learning is best-effort background work (the user already has
their answer), and a migration failure must never break the login/upgrade itself.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol, runtime_checkable

from app.memory.learn import LearnConfig, MemoryCandidate, MemoryExtractor, gate_candidate
from app.services.guest_memory import GuestMemory
from app.services.preferences import PreferenceStore

logger = logging.getLogger(__name__)

__all__ = [
    "DurableMemoryWriter",
    "GuestPersonalizationLearner",
    "GuestPersonalizationMigrator",
]

#: Guest memories are stored as plain strings (they carry no per-item type), so on migration to
#: the durable typed ``user_memories`` schema they default to ``fact`` — the neutral, always-valid
#: ``ck_user_memories_memory_type`` value. A minor fidelity loss (a guest "style" cue migrates as a
#: fact) that is acceptable for ephemeral data and keeps the Redis shape a simple string list.
_MIGRATED_MEMORY_TYPE = "fact"


@runtime_checkable
class DurableMemoryWriter(Protocol):
    """The single durable-write method the migration needs (satisfied by ``UserMemoryStore``).

    Structural (not a hard import of :class:`~app.memory.store.UserMemoryStore`, which pulls in
    LangGraph/pgvector) so this module stays light and unit tests inject a fake writer.
    """

    async def add_memory(
        self,
        user_id: uuid.UUID,
        text: str,
        *,
        memory_type: str,
        confidence: float,
        source_message_id: str | None = ...,
    ) -> uuid.UUID: ...


class GuestPersonalizationLearner:
    """Post-turn guest learn: extract → gate → append to the Redis-only store (§5.4).

    Callable (``async __call__``) so it satisfies the chat service's narrow ``GuestLearner`` seam
    without the service importing this class. Bound once at the composition root with the shared
    LLM-backed extractor + the Redis guest store.
    """

    def __init__(
        self,
        *,
        extractor: MemoryExtractor,
        guest_memory: GuestMemory,
        config: LearnConfig | None = None,
    ) -> None:
        self._extractor = extractor
        self._guest_memory = guest_memory
        self._config = config or LearnConfig()

    async def __call__(self, *, session_id: str, user_text: str, assistant_text: str) -> None:
        """Learn 0+ ephemeral memories from one completed guest turn (best-effort, never raises)."""
        if not session_id:
            return
        try:
            candidates = await self._extractor.propose(
                user_text=user_text, assistant_text=assistant_text
            )
        except Exception:  # noqa: BLE001 - guest learning is best-effort background work
            logger.warning("guest memory extraction failed; learning nothing", exc_info=True)
            return

        # The SAME §7.6 gate the durable path uses: redact contact PII, drop Art. 9 special
        # categories — even though this only ever reaches Redis (an ephemeral list must not
        # accumulate special-category data either).
        gated = [g.text for c in candidates if (g := gate_candidate(c)) is not None]
        if not gated:
            return
        try:
            await self._guest_memory.record(session_id, memories=gated)
        except Exception:  # noqa: BLE001 - a Redis write failure must not surface to the turn
            logger.warning("failed to record guest personalization (session=%s)", session_id)


class GuestPersonalizationMigrator:
    """Migrate a guest's Redis personalization into the durable stores on upgrade (§5.4).

    Reads the guest's :class:`~app.services.guest_memory.GuestPersonalization`, writes its
    ``preferences`` to the user's ``preferences`` row and ``memories`` to ``user_memories`` (each
    re-gated through :func:`~app.memory.learn.gate_candidate`), then
    leaves the Redis copy to expire. A collaborator injected into
    :class:`~app.services.guest_upgrade.GuestUpgradeService` so that service's constructor stays
    focused on the transcript carry-over (SoC).
    """

    def __init__(
        self,
        *,
        guest_memory: GuestMemory,
        preferences: PreferenceStore,
        memories: DurableMemoryWriter,
        config: LearnConfig | None = None,
    ) -> None:
        self._guest_memory = guest_memory
        self._preferences = preferences
        self._memories = memories
        self._config = config or LearnConfig()

    async def migrate(self, *, guest_session_id: str, user_id: str) -> None:
        """Persist the guest's ephemeral personalization durably for ``user_id`` (best-effort).

        A clean no-op when the guest accumulated no personalization. Preferences and memories are
        migrated independently so a failure in one does not lose the other; both stay best-effort —
        the caller (:meth:`~app.services.guest_upgrade.GuestUpgradeService.upgrade`) additionally
        wraps this so the upgrade never fails on a migration error.
        """
        personalization = await self._guest_memory.load(guest_session_id)
        if not personalization.preferences and not personalization.memories:
            return

        uid = _parse_uuid(user_id)
        if uid is None:
            logger.warning("guest personalization migration skipped: malformed user id")
            return

        await self._migrate_preferences(user_id, personalization.preferences)
        await self._migrate_memories(uid, personalization.memories)

    async def _migrate_preferences(self, user_id: str, preferences: dict[str, object]) -> None:
        """Merge the guest's explicit preferences into the user's ``preferences`` row (guest wins).

        Merged over any existing row (``{**existing, **guest}``) so a returning account's other
        settings are preserved while the just-expressed guest values win for overlapping keys.
        """
        if not preferences:
            return
        try:
            existing = await self._preferences.get(user_id)
            await self._preferences.upsert(user_id, {**existing, **preferences})
        except Exception:  # noqa: BLE001 - best-effort; must not abort the upgrade
            logger.warning("failed to migrate guest preferences to Postgres", exc_info=True)

    async def _migrate_memories(self, user_id: uuid.UUID, memories: list[str]) -> None:
        """Re-gate each guest memory string and persist the survivors to ``user_memories``.

        The gate runs again (it already ran on the ephemeral write) as defense-in-depth: an Art. 9
        memory does not become durable just because it was already in Redis. A per-memory failure is
        logged and stops the batch but never aborts the upgrade.
        """
        for text in memories:
            gated = gate_candidate(
                MemoryCandidate(
                    text=text,
                    memory_type=_MIGRATED_MEMORY_TYPE,
                    confidence=self._config.default_confidence,
                )
            )
            if gated is None:
                continue  # dropped by the Art. 9 filter — never durably persisted
            try:
                await self._memories.add_memory(
                    user_id,
                    gated.text,
                    memory_type=gated.memory_type,
                    confidence=gated.confidence,
                    source_message_id=None,
                )
            except Exception:  # noqa: BLE001 - best-effort; must not abort the upgrade
                logger.warning("failed to migrate a guest memory to Postgres", exc_info=True)
                return


def _parse_uuid(user_id: str) -> uuid.UUID | None:
    """Parse a ``users.id`` string to UUID, or ``None`` (malformed → skip durable migration)."""
    if not user_id:
        return None
    try:
        return uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None
