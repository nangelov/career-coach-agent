"""Unit tests for the post-turn teachable-memory learn step (P9-03, §5.4 point 3 / §5.5).

Exercise :func:`~app.memory.learn.run_learn_from_turn` — the injectable core of the Celery
learn task — with fakes for every collaborator (memory store / extractor / feedback), so no
real HF / embedder / Postgres / Celery is involved. Covers the acceptance criteria:

* a turn that yields a new memory → **inserted** (with a non-1.0 confidence),
* a turn whose candidate near-duplicates an existing memory → the existing row is **updated**
  (reinforced), not duplicated,
* a turn with no learnable content → **no-op**,
* a **thumbs-down** turn → the memories learned from it are **demoted / removed**, and a
  down-vote reason learns an explicit "avoid X" preference,
* a guest / malformed user id → **skipped**, and
* the :class:`~app.memory.learn.LLMMemoryExtractor` native tool-call parsing (fail-soft).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.llm.types import CompletionResult, FunctionCall, ToolCall
from app.memory.learn import (
    LearnConfig,
    LLMMemoryExtractor,
    MemoryCandidate,
    run_learn_from_turn,
)
from app.repositories.vector_search import MemorySearchResult, UserMemoryRecord
from app.schemas.message_feedback import MessageFeedbackResponse
from app.services.message_feedback import InMemoryMessageFeedbackStore, MessageOwner

_UID = str(uuid4())


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeMemoryStore:
    """A :class:`~app.memory.learn.MemoryWriter` double: records writes, scripts search hits."""

    def __init__(
        self,
        *,
        search_hits: list[MemorySearchResult] | None = None,
        by_message: dict[str, list[UserMemoryRecord]] | None = None,
    ) -> None:
        self._search_hits = search_hits or []
        self._by_message = by_message or {}
        self.added: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.deleted: list[uuid.UUID] = []

    async def search_memories(
        self, user_id: uuid.UUID, query: str, *, k: int | None = None
    ) -> list[MemorySearchResult]:
        return list(self._search_hits)

    async def add_memory(
        self,
        user_id: uuid.UUID,
        text: str,
        *,
        memory_type: str,
        confidence: float,
        source_message_id: str | None = None,
    ) -> uuid.UUID:
        memory_id = uuid4()
        self.added.append(
            {
                "memory_id": memory_id,
                "user_id": user_id,
                "text": text,
                "memory_type": memory_type,
                "confidence": confidence,
                "source_message_id": source_message_id,
            }
        )
        return memory_id

    async def update_memory(
        self, memory_id: uuid.UUID, *, text: str | None = None, confidence: float | None = None
    ) -> bool:
        self.updated.append({"memory_id": memory_id, "text": text, "confidence": confidence})
        # Mirror the real store: an update bumps ``updated_at`` (onupdate=now) and applies the new
        # confidence, so a later demotion pass sees the row as already touched (idempotency).
        self._mutate_stored(
            memory_id,
            confidence=confidence,
            text=text,
            updated_at=datetime.now(UTC),
        )
        return True

    async def delete_memory(self, memory_id: uuid.UUID) -> bool:
        self.deleted.append(memory_id)
        for msg_id, records in self._by_message.items():
            self._by_message[msg_id] = [r for r in records if r.memory_id != memory_id]
        return True

    async def list_memories_for_message(
        self, user_id: uuid.UUID, source_message_id: str
    ) -> list[UserMemoryRecord]:
        return list(self._by_message.get(source_message_id, []))

    def _mutate_stored(
        self,
        memory_id: uuid.UUID,
        *,
        confidence: float | None,
        text: str | None,
        updated_at: datetime,
    ) -> None:
        for msg_id, records in self._by_message.items():
            self._by_message[msg_id] = [
                replace(
                    r,
                    updated_at=updated_at,
                    confidence=confidence if confidence is not None else r.confidence,
                    text=text if text is not None else r.text,
                )
                if r.memory_id == memory_id
                else r
                for r in records
            ]


class FakeExtractor:
    """A :class:`~app.memory.learn.MemoryExtractor` double returning preset candidates."""

    def __init__(self, candidates: list[MemoryCandidate] | None = None) -> None:
        self._candidates = candidates or []
        self.calls: list[dict[str, str]] = []

    async def propose(self, *, user_text: str, assistant_text: str) -> list[MemoryCandidate]:
        self.calls.append({"user_text": user_text, "assistant_text": assistant_text})
        return list(self._candidates)


def _hit(
    *,
    memory_id: uuid.UUID,
    similarity: float,
    memory_type: str = "preference",
    confidence: float = 0.7,
) -> MemorySearchResult:
    return MemorySearchResult(
        memory_id=memory_id,
        text="existing",
        similarity=similarity,
        memory_type=memory_type,
        confidence=confidence,
    )


#: A memory learned well before any down-vote — so the demotion pass treats it as demotable
#: (its ``updated_at`` predates the vote). Individual tests override when they need a fresh row.
_LEARNED_AT = datetime(2020, 1, 1, tzinfo=UTC)


def _record(
    *,
    memory_id: uuid.UUID,
    confidence: float,
    source_message_id: str,
    updated_at: datetime = _LEARNED_AT,
) -> UserMemoryRecord:
    return UserMemoryRecord(
        memory_id=memory_id,
        text="learned earlier",
        memory_type="fact",
        confidence=confidence,
        source_message_id=source_message_id,
        updated_at=updated_at,
    )


def _no_feedback() -> InMemoryMessageFeedbackStore:
    return InMemoryMessageFeedbackStore()


async def _seed_downvote(
    *, message_id: str, user_id: str, reason: str | None = None
) -> InMemoryMessageFeedbackStore:
    store = InMemoryMessageFeedbackStore(owners={message_id: MessageOwner(user_id=user_id)})
    await store.record(
        message_id=message_id, rating="down", reason=reason, user_id=user_id, session_id="s"
    )
    return store


# --------------------------------------------------------------------------- #
# New memory → inserted (with a real, non-1.0 confidence)
# --------------------------------------------------------------------------- #
async def test_new_candidate_is_inserted() -> None:
    store = FakeMemoryStore(search_hits=[])  # nothing similar exists
    extractor = FakeExtractor(
        [MemoryCandidate(text="prefers bullet points", memory_type="style", confidence=0.8)]
    )

    result = await run_learn_from_turn(
        user_id=_UID,
        message_id="m1",
        user_text="please keep it short and use bullets",
        assistant_text="Sure: - a\n- b",
        store=store,
        extractor=extractor,
        feedback=_no_feedback(),
    )

    assert len(store.added) == 1
    assert store.added[0]["text"] == "prefers bullet points"
    assert store.added[0]["memory_type"] == "style"
    assert store.added[0]["source_message_id"] == "m1"
    assert store.added[0]["confidence"] == 0.8  # not blindly 1.0
    assert result.inserted and not result.updated


async def test_missing_confidence_falls_back_to_default_not_one() -> None:
    store = FakeMemoryStore(search_hits=[])
    extractor = FakeExtractor(
        [MemoryCandidate(text="based in Berlin", memory_type="fact", confidence=-1.0)]
    )
    cfg = LearnConfig(default_confidence=0.6)

    await run_learn_from_turn(
        user_id=_UID,
        message_id="m1",
        user_text="I live in Berlin",
        assistant_text="Great.",
        store=store,
        extractor=extractor,
        feedback=_no_feedback(),
        config=cfg,
    )

    assert store.added[0]["confidence"] == 0.6


# --------------------------------------------------------------------------- #
# Near-duplicate → existing row updated, not duplicated
# --------------------------------------------------------------------------- #
async def test_near_duplicate_updates_existing_not_inserts() -> None:
    existing_id = uuid4()
    store = FakeMemoryStore(
        search_hits=[
            _hit(memory_id=existing_id, similarity=0.95, memory_type="preference", confidence=0.7)
        ]
    )
    extractor = FakeExtractor(
        [MemoryCandidate(text="prefers concise answers", memory_type="preference", confidence=0.8)]
    )

    result = await run_learn_from_turn(
        user_id=_UID,
        message_id="m2",
        user_text="keep it concise",
        assistant_text="ok",
        store=store,
        extractor=extractor,
        feedback=_no_feedback(),
    )

    assert store.added == []  # no twin inserted
    assert len(store.updated) == 1
    assert store.updated[0]["memory_id"] == existing_id
    # Reinforced: confidence bumped from 0.7 by the default increment (0.1).
    assert store.updated[0]["confidence"] == 0.7 + 0.1
    assert result.updated == [existing_id] and not result.inserted


async def test_low_similarity_hit_is_not_treated_as_duplicate() -> None:
    store = FakeMemoryStore(search_hits=[_hit(memory_id=uuid4(), similarity=0.5)])
    extractor = FakeExtractor(
        [MemoryCandidate(text="targeting PM roles", memory_type="preference", confidence=0.8)]
    )

    await run_learn_from_turn(
        user_id=_UID,
        message_id="m3",
        user_text="I want to move into product",
        assistant_text="ok",
        store=store,
        extractor=extractor,
        feedback=_no_feedback(),
    )

    assert len(store.added) == 1 and store.updated == []


async def test_same_similarity_different_type_is_not_duplicate() -> None:
    # A very similar memory but of a different memory_type must not be reinforced/collapsed.
    store = FakeMemoryStore(
        search_hits=[_hit(memory_id=uuid4(), similarity=0.99, memory_type="fact")]
    )
    extractor = FakeExtractor(
        [MemoryCandidate(text="prefers concise answers", memory_type="preference", confidence=0.8)]
    )

    await run_learn_from_turn(
        user_id=_UID,
        message_id="m4",
        user_text="concise please",
        assistant_text="ok",
        store=store,
        extractor=extractor,
        feedback=_no_feedback(),
    )

    assert len(store.added) == 1 and store.updated == []


# --------------------------------------------------------------------------- #
# No learnable content → no-op (the chit-chat case)
# --------------------------------------------------------------------------- #
async def test_no_candidates_is_a_noop() -> None:
    store = FakeMemoryStore()
    extractor = FakeExtractor([])  # extractor proposes nothing (chit-chat)

    result = await run_learn_from_turn(
        user_id=_UID,
        message_id="m5",
        user_text="hi",
        assistant_text="Hello!",
        store=store,
        extractor=extractor,
        feedback=_no_feedback(),
    )

    assert store.added == [] and store.updated == [] and store.deleted == []
    assert not result.inserted and not result.updated


# --------------------------------------------------------------------------- #
# Guest / malformed user id → skipped, nothing touched
# --------------------------------------------------------------------------- #
async def test_malformed_user_id_is_skipped() -> None:
    store = FakeMemoryStore()
    extractor = FakeExtractor([MemoryCandidate(text="x", memory_type="fact", confidence=0.8)])

    result = await run_learn_from_turn(
        user_id="not-a-uuid",
        message_id="m6",
        user_text="hi",
        assistant_text="hello",
        store=store,
        extractor=extractor,
        feedback=_no_feedback(),
    )

    assert result.skipped is True
    assert store.added == [] and not extractor.calls  # never even extracted


# --------------------------------------------------------------------------- #
# Thumbs-down → demotion / removal + explicit negative preference
# --------------------------------------------------------------------------- #
async def test_downvoted_turn_demotes_and_removes_its_memories() -> None:
    high_id = uuid4()  # will be demoted (0.9 - 0.3 = 0.6 > floor)
    low_id = uuid4()  # will be removed (0.2 - 0.3 <= floor)
    store = FakeMemoryStore(
        by_message={
            "m7": [
                _record(memory_id=high_id, confidence=0.9, source_message_id="m7"),
                _record(memory_id=low_id, confidence=0.2, source_message_id="m7"),
            ]
        }
    )
    extractor = FakeExtractor(
        [MemoryCandidate(text="should not be learned", memory_type="fact", confidence=0.9)]
    )
    feedback = await _seed_downvote(message_id="m7", user_id=_UID, reason="too generic")

    result = await run_learn_from_turn(
        user_id=_UID,
        message_id="m7",
        user_text="that advice was useless",
        assistant_text="Here is some generic advice.",
        store=store,
        extractor=extractor,
        feedback=feedback,
    )

    # High-confidence memory demoted in place; low-confidence one removed.
    assert result.demoted == [high_id]
    assert result.removed == [low_id]
    demote = next(u for u in store.updated if u["memory_id"] == high_id)
    assert demote["confidence"] == 0.9 - 0.3
    assert low_id in store.deleted
    # A down-voted turn does NOT mine its disapproved advice for positive memories, but it does
    # learn an explicit "avoid" preference from the reason.
    assert not extractor.calls
    assert len(store.added) == 1
    assert store.added[0]["memory_type"] == "preference"
    assert "too generic" in store.added[0]["text"]


async def test_downvote_without_reason_demotes_but_learns_no_preference() -> None:
    mem_id = uuid4()
    store = FakeMemoryStore(
        by_message={"m8": [_record(memory_id=mem_id, confidence=0.9, source_message_id="m8")]}
    )
    feedback = await _seed_downvote(message_id="m8", user_id=_UID, reason=None)

    result = await run_learn_from_turn(
        user_id=_UID,
        message_id="m8",
        user_text="nope",
        assistant_text="advice",
        store=store,
        extractor=FakeExtractor([]),
        feedback=feedback,
    )

    assert result.demoted == [mem_id]
    assert store.added == []  # no reason → no explicit negative preference


async def test_recent_downvote_on_prior_turn_demotes_that_turns_memory() -> None:
    # Learning from the current (un-voted) turn also demotes a memory tied to a *recent* down-vote.
    prior_mem = uuid4()
    store = FakeMemoryStore(
        search_hits=[],
        by_message={
            "prior": [_record(memory_id=prior_mem, confidence=0.9, source_message_id="prior")]
        },
    )
    feedback = InMemoryMessageFeedbackStore(owners={"prior": MessageOwner(user_id=_UID)})
    await feedback.record(
        message_id="prior", rating="down", reason=None, user_id=_UID, session_id="s"
    )
    extractor = FakeExtractor(
        [MemoryCandidate(text="new fact", memory_type="fact", confidence=0.8)]
    )

    result = await run_learn_from_turn(
        user_id=_UID,
        message_id="current",
        user_text="tell me more",
        assistant_text="here",
        store=store,
        extractor=extractor,
        feedback=feedback,
    )

    assert result.demoted == [prior_mem]  # prior turn's memory demoted
    assert result.inserted  # and the current turn still learns normally


async def test_standing_downvote_demotes_once_not_every_pass() -> None:
    # Regression (code-review C1): a single standing down-vote stays in the recent-downvote window
    # across many later turns. Without idempotency it would demote the same memory on *every* pass
    # (0.9 → 0.6 → 0.3 → deleted), silent progressive data loss. It must demote exactly once.
    mem_id = uuid4()
    store = FakeMemoryStore(
        by_message={
            "voted": [_record(memory_id=mem_id, confidence=0.9, source_message_id="voted")]
        },
    )
    feedback = InMemoryMessageFeedbackStore(owners={"voted": MessageOwner(user_id=_UID)})
    await feedback.record(
        message_id="voted", rating="down", reason=None, user_id=_UID, session_id="s"
    )
    extractor = FakeExtractor([])  # later turns are chit-chat

    # Pass 1: the one down-vote demotes the memory once (0.9 → 0.6).
    first = await run_learn_from_turn(
        user_id=_UID,
        message_id="later-1",
        user_text="hi",
        assistant_text="hello",
        store=store,
        extractor=extractor,
        feedback=feedback,
    )
    assert first.demoted == [mem_id]
    assert store.updated[-1]["confidence"] == pytest.approx(0.6)

    # Pass 2 (and any later pass): the *same* standing down-vote must NOT demote again — the
    # memory's updated_at now post-dates the vote — so it is neither demoted nor removed.
    second = await run_learn_from_turn(
        user_id=_UID,
        message_id="later-2",
        user_text="hi again",
        assistant_text="hello again",
        store=store,
        extractor=extractor,
        feedback=feedback,
    )
    assert second.demoted == [] and second.removed == []
    assert store.deleted == []  # never driven to deletion
    # Confidence held at the single demotion, not compounded.
    remaining = await store.list_memories_for_message(uuid.UUID(_UID), "voted")
    assert remaining[0].confidence == pytest.approx(0.6)


# --------------------------------------------------------------------------- #
# LLMMemoryExtractor — native tool-call parsing (fail-soft)
# --------------------------------------------------------------------------- #
class FakeCompleter:
    """A completer double returning a scripted ``record_memories`` tool call (or raising)."""

    def __init__(self, *, arguments: str | None = None, error: Exception | None = None) -> None:
        self._arguments = arguments
        self._error = error

    async def complete(self, messages: Any, **_: Any) -> CompletionResult:
        if self._error is not None:
            raise self._error
        tool_calls = (
            [
                ToolCall(
                    id="c1",
                    function=FunctionCall(name="record_memories", arguments=self._arguments),
                )
            ]
            if self._arguments is not None
            else []
        )
        return CompletionResult(content=None, tool_calls=tool_calls, model="fake")


async def test_extractor_parses_valid_tool_call() -> None:
    args = (
        '{"memories": [{"text": "prefers bullet points", "memory_type": "style", '
        '"confidence": 0.9}, {"text": "based in Berlin", "memory_type": "fact"}]}'
    )
    extractor = LLMMemoryExtractor(FakeCompleter(arguments=args))

    candidates = await extractor.propose(user_text="hi", assistant_text="ok")

    assert [c.text for c in candidates] == ["prefers bullet points", "based in Berlin"]
    assert candidates[0].confidence == 0.9
    assert candidates[1].confidence == -1.0  # missing → sentinel, clamped later


async def test_extractor_drops_invalid_items_and_bad_types() -> None:
    args = (
        '{"memories": [{"text": "", "memory_type": "fact"}, '
        '{"text": "ok", "memory_type": "bogus"}, '
        '{"memory_type": "fact"}, '
        '{"text": "keep me", "memory_type": "preference"}]}'
    )
    extractor = LLMMemoryExtractor(FakeCompleter(arguments=args))

    candidates = await extractor.propose(user_text="hi", assistant_text="ok")

    assert [c.text for c in candidates] == ["keep me"]


async def test_extractor_empty_list_and_no_tool_call_yield_nothing() -> None:
    empty = LLMMemoryExtractor(FakeCompleter(arguments='{"memories": []}'))
    assert await empty.propose(user_text="hi", assistant_text="ok") == []

    no_call = LLMMemoryExtractor(FakeCompleter(arguments=None))
    assert await no_call.propose(user_text="hi", assistant_text="ok") == []


async def test_extractor_blank_user_text_short_circuits() -> None:
    args = '{"memories": [{"text":"x","memory_type":"fact"}]}'
    extractor = LLMMemoryExtractor(FakeCompleter(arguments=args))
    assert await extractor.propose(user_text="   ", assistant_text="ok") == []


async def test_extractor_llm_error_is_fail_soft() -> None:
    from app.llm.errors import LLMAllModelsFailedError

    extractor = LLMMemoryExtractor(FakeCompleter(error=LLMAllModelsFailedError("down")))
    assert await extractor.propose(user_text="hi", assistant_text="ok") == []


async def test_extractor_invalid_json_is_fail_soft() -> None:
    extractor = LLMMemoryExtractor(FakeCompleter(arguments="not json"))
    assert await extractor.propose(user_text="hi", assistant_text="ok") == []


def test_message_feedback_response_shape_is_consumed() -> None:
    # Guard that the feedback DTO the learn step reads keeps ``rating`` / ``reason`` fields.
    fb = MessageFeedbackResponse(
        message_id="m", rating="down", reason="why", created_at=datetime.now(UTC)
    )
    assert fb.rating == "down" and fb.reason == "why"
