"""Unit tests for the guest personalization learn + upgrade migration (P9-07, design §5.4).

Covers the acceptance criteria for the two write-side halves:

* :class:`~app.memory.guest_personalization.GuestPersonalizationLearner` — a guest turn's learn
  writes to the Redis-only store (never Postgres), and the **same** P9-04 PII redaction + GDPR
  Art. 9 exclusion gate applies even to the ephemeral write (a special-category memory never
  accumulates; contact PII is redacted).
* :class:`~app.memory.guest_personalization.GuestPersonalizationMigrator` — on upgrade the guest's
  ephemeral preferences + memories are migrated durably, re-passing the gate on the way in (an
  Art. 9 ephemeral memory does not survive migration), and an empty guest store is a clean no-op.

Fakes only — no LLM, no Redis, no Postgres.
"""

from __future__ import annotations

import uuid

from app.memory.guest_personalization import (
    GuestPersonalizationLearner,
    GuestPersonalizationMigrator,
)
from app.memory.learn import MemoryCandidate
from app.services.guest_memory import InMemoryGuestMemory
from app.services.preferences import InMemoryPreferenceStore

_UID = str(uuid.uuid4())


class FakeExtractor:
    """A :class:`~app.memory.learn.MemoryExtractor` double returning preset candidates."""

    def __init__(
        self,
        candidates: list[MemoryCandidate] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._candidates = candidates or []
        self._error = error
        self.calls: list[dict[str, str]] = []

    async def propose(self, *, user_text: str, assistant_text: str) -> list[MemoryCandidate]:
        self.calls.append({"user_text": user_text, "assistant_text": assistant_text})
        if self._error is not None:
            raise self._error
        return list(self._candidates)


class FakeMemoryWriter:
    """A :class:`~app.memory.guest_personalization.DurableMemoryWriter` double (records adds)."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.added: list[tuple[uuid.UUID, str, str, float]] = []

    async def add_memory(
        self,
        user_id: uuid.UUID,
        text: str,
        *,
        memory_type: str,
        confidence: float,
        source_message_id: str | None = None,
    ) -> uuid.UUID:
        if self._error is not None:
            raise self._error
        self.added.append((user_id, text, memory_type, confidence))
        return uuid.uuid4()


# --------------------------------------------------------------------------- #
# Learner — Redis-only write, with the PII/Art. 9 gate
# --------------------------------------------------------------------------- #
async def test_guest_learn_writes_to_redis_only() -> None:
    store = InMemoryGuestMemory()
    extractor = FakeExtractor(
        [MemoryCandidate(text="based in Berlin", memory_type="fact", confidence=0.8)]
    )
    learner = GuestPersonalizationLearner(extractor=extractor, guest_memory=store)

    await learner(session_id="s1", user_text="I live in Berlin", assistant_text="Great")

    assert (await store.load("s1")).memories == ["based in Berlin"]
    assert extractor.calls == [{"user_text": "I live in Berlin", "assistant_text": "Great"}]


async def test_guest_learn_redacts_pii_before_storing() -> None:
    store = InMemoryGuestMemory()
    extractor = FakeExtractor(
        [MemoryCandidate(text="reachable at jane@doe.com", memory_type="fact", confidence=0.7)]
    )
    learner = GuestPersonalizationLearner(extractor=extractor, guest_memory=store)

    await learner(session_id="s1", user_text="my email is jane@doe.com", assistant_text="ok")

    (memory,) = (await store.load("s1")).memories
    assert "jane@doe.com" not in memory  # contact PII redacted before it lands in Redis


async def test_guest_learn_drops_special_category_memory() -> None:
    store = InMemoryGuestMemory()
    extractor = FakeExtractor(
        [
            MemoryCandidate(text="has depression", memory_type="fact", confidence=0.9),
            MemoryCandidate(text="targeting product mgmt", memory_type="fact", confidence=0.8),
        ]
    )
    learner = GuestPersonalizationLearner(extractor=extractor, guest_memory=store)

    await learner(session_id="s1", user_text="...", assistant_text="...")

    # The Art. 9 (health) candidate is dropped even for the ephemeral Redis write; the benign one
    # survives.
    assert (await store.load("s1")).memories == ["targeting product mgmt"]


async def test_guest_learn_is_fail_soft_on_extractor_error() -> None:
    store = InMemoryGuestMemory()
    learner = GuestPersonalizationLearner(
        extractor=FakeExtractor(error=RuntimeError("llm down")), guest_memory=store
    )

    await learner(session_id="s1", user_text="hi", assistant_text="ok")  # must not raise

    assert (await store.load("s1")).memories == []


async def test_guest_learn_nothing_to_learn_is_a_noop() -> None:
    store = InMemoryGuestMemory()
    learner = GuestPersonalizationLearner(extractor=FakeExtractor([]), guest_memory=store)

    await learner(session_id="s1", user_text="hi", assistant_text="ok")

    assert (await store.load("s1")).memories == []


# --------------------------------------------------------------------------- #
# Migrator — Redis → Postgres on upgrade, re-gated
# --------------------------------------------------------------------------- #
def _migrator(
    store: InMemoryGuestMemory,
    prefs: InMemoryPreferenceStore,
    memories: FakeMemoryWriter,
) -> GuestPersonalizationMigrator:
    return GuestPersonalizationMigrator(guest_memory=store, preferences=prefs, memories=memories)


async def test_migrate_moves_preferences_and_memories() -> None:
    store = InMemoryGuestMemory()
    await store.record(
        "guest-1", memories=["based in Berlin", "targeting PM"], preferences={"tone": "concise"}
    )
    prefs = InMemoryPreferenceStore()
    memories = FakeMemoryWriter()

    await _migrator(store, prefs, memories).migrate(guest_session_id="guest-1", user_id=_UID)

    assert await prefs.get(_UID) == {"tone": "concise"}
    assert [text for _, text, _, _ in memories.added] == ["based in Berlin", "targeting PM"]
    assert {mtype for _, _, mtype, _ in memories.added} == {"fact"}
    assert all(uid == uuid.UUID(_UID) for uid, _, _, _ in memories.added)


async def test_migrate_merges_preferences_guest_wins() -> None:
    store = InMemoryGuestMemory()
    await store.record("guest-1", preferences={"tone": "concise"})
    prefs = InMemoryPreferenceStore()
    await prefs.upsert(_UID, {"tone": "formal", "language": "en"})

    await _migrator(store, prefs, FakeMemoryWriter()).migrate(
        guest_session_id="guest-1", user_id=_UID
    )

    # Existing keys preserved; the just-expressed guest value wins for the overlap.
    assert await prefs.get(_UID) == {"tone": "concise", "language": "en"}


async def test_migrate_re_gates_special_category_memory() -> None:
    store = InMemoryGuestMemory()
    # Seed the Redis store directly (bypassing the learn gate) to prove the migration re-gates —
    # an Art. 9 memory that somehow sits in Redis must not become durable on upgrade.
    await store.record("guest-1", memories=["has depression", "targeting PM"])
    memories = FakeMemoryWriter()

    await _migrator(store, InMemoryPreferenceStore(), memories).migrate(
        guest_session_id="guest-1", user_id=_UID
    )

    assert [text for _, text, _, _ in memories.added] == ["targeting PM"]  # health dropped


async def test_migrate_with_no_personalization_is_a_clean_noop() -> None:
    prefs = InMemoryPreferenceStore()
    memories = FakeMemoryWriter()

    await _migrator(InMemoryGuestMemory(), prefs, memories).migrate(
        guest_session_id="empty", user_id=_UID
    )

    assert await prefs.get(_UID) == {}
    assert memories.added == []


async def test_migrate_malformed_user_id_skips_durable_write() -> None:
    store = InMemoryGuestMemory()
    await store.record("guest-1", memories=["m1"], preferences={"tone": "concise"})
    prefs = InMemoryPreferenceStore()
    memories = FakeMemoryWriter()

    await _migrator(store, prefs, memories).migrate(
        guest_session_id="guest-1", user_id="not-a-uuid"
    )

    assert memories.added == []
    assert await prefs.get("not-a-uuid") == {}


async def test_migrate_memory_write_failure_is_best_effort() -> None:
    store = InMemoryGuestMemory()
    await store.record("guest-1", memories=["m1"], preferences={"tone": "concise"})
    memories = FakeMemoryWriter(error=RuntimeError("db down"))

    # A durable-write failure must not raise out of the migration (the upgrade must not break).
    await _migrator(store, InMemoryPreferenceStore(), memories).migrate(
        guest_session_id="guest-1", user_id=_UID
    )
