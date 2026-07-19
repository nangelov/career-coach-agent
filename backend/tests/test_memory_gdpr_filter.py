"""Unit tests for the P9-04 §7.6 memory PII/GDPR gate.

Two layers:

* :func:`~app.memory.gdpr_filter.special_category_of` /
  :func:`~app.memory.gdpr_filter.contains_special_category` in isolation — every covered
  GDPR Art. 9 category is detected, and benign career/preference text is not flagged.
* the gate **wired into** :func:`~app.memory.learn.run_learn_from_turn` — a benign candidate
  passes through unchanged, a contact-PII candidate is redacted (not dropped), a
  special-category candidate is dropped (never written), and a special-category candidate does
  not suppress an unrelated benign candidate extracted from the same turn.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import uuid4

import pytest

from app.memory.gdpr_filter import contains_special_category, special_category_of
from app.memory.learn import MemoryCandidate, run_learn_from_turn
from app.repositories.vector_search import MemorySearchResult, UserMemoryRecord
from app.services.message_feedback import InMemoryMessageFeedbackStore

_UID = str(uuid4())


# --------------------------------------------------------------------------- #
# The pure filter — each Art. 9 category is detected
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("I am returning to work after cancer treatment", "health"),
        ("currently on medical leave for a few weeks", "health"),
        ("I struggle with anxiety and depression", "health"),
        ("I have ADHD, what roles suit me?", "disability"),
        ("as a wheelchair user I need accessible offices", "disability"),
        ("about my ethnic background and being a person of colour", "ethnicity"),
        ("as a practising Muslim I can't work during Ramadan", "religion"),
        ("I'm an active trade union member", "trade_union"),
        ("I'm openly gay and want an inclusive employer", "sexuality"),
        ("my sexual orientation should not matter for the role", "sexuality"),
    ],
)
def test_special_category_is_detected(text: str, category: str) -> None:
    assert special_category_of(text) == category
    assert contains_special_category(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "prefers concise bullet-point answers",
        "targeting product management roles in fintech",
        "based in Berlin, open to remote work",
        "wants to improve public-speaking and leadership skills",
        "has ten years of experience in the European Union market",  # not a union membership
        "reunion planning is a hobby",  # 'union' inside 'reunion' must not match
        "",
    ],
)
def test_benign_text_is_not_flagged(text: str) -> None:
    assert special_category_of(text) is None
    assert contains_special_category(text) is False


# --------------------------------------------------------------------------- #
# Test doubles (minimal — mirror test_memory_learn.py)
# --------------------------------------------------------------------------- #
class FakeMemoryStore:
    """Records writes; scripts search hits (a :class:`~app.memory.learn.MemoryWriter`)."""

    def __init__(self, *, search_hits: list[MemorySearchResult] | None = None) -> None:
        self._search_hits = search_hits or []
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
        self.added.append({"memory_id": memory_id, "text": text, "memory_type": memory_type})
        return memory_id

    async def update_memory(
        self, memory_id: uuid.UUID, *, text: str | None = None, confidence: float | None = None
    ) -> bool:
        self.updated.append({"memory_id": memory_id, "text": text, "confidence": confidence})
        return True

    async def delete_memory(self, memory_id: uuid.UUID) -> bool:
        self.deleted.append(memory_id)
        return True

    async def list_memories_for_message(
        self, user_id: uuid.UUID, source_message_id: str
    ) -> list[UserMemoryRecord]:
        return []


class FakeExtractor:
    """Returns preset candidates (a :class:`~app.memory.learn.MemoryExtractor`)."""

    def __init__(self, candidates: list[MemoryCandidate]) -> None:
        self._candidates = candidates

    async def propose(self, *, user_text: str, assistant_text: str) -> list[MemoryCandidate]:
        return list(self._candidates)


def _run(store: FakeMemoryStore, candidates: list[MemoryCandidate]) -> Any:
    return run_learn_from_turn(
        user_id=_UID,
        message_id="m1",
        user_text="u",
        assistant_text="a",
        store=store,
        extractor=FakeExtractor(candidates),
        feedback=InMemoryMessageFeedbackStore(),
    )


# --------------------------------------------------------------------------- #
# The gate wired into the learn pass
# --------------------------------------------------------------------------- #
async def test_benign_candidate_passes_through_unchanged() -> None:
    store = FakeMemoryStore(search_hits=[])
    await _run(
        store,
        [MemoryCandidate(text="prefers concise answers", memory_type="preference", confidence=0.8)],
    )
    assert len(store.added) == 1
    assert store.added[0]["text"] == "prefers concise answers"  # substance unchanged


async def test_contact_pii_candidate_is_redacted_not_dropped() -> None:
    store = FakeMemoryStore(search_hits=[])
    await _run(
        store,
        [
            MemoryCandidate(
                text="reach the user at jane.doe@example.com",
                memory_type="fact",
                confidence=0.8,
            )
        ],
    )
    # Written (not dropped) but with the email redacted — PII never lands verbatim.
    assert len(store.added) == 1
    assert "jane.doe@example.com" not in store.added[0]["text"]
    assert "[EMAIL REDACTED]" in store.added[0]["text"]


@pytest.mark.parametrize(
    "text",
    [
        "the user is on medical leave",  # health
        "the user has ADHD",  # disability
        "the user is a practising Muslim",  # religion
        "the user described their ethnic background",  # ethnicity
        "the user is a trade union member",  # union
        "the user is gay",  # sexuality
    ],
)
async def test_special_category_candidate_is_dropped(text: str) -> None:
    store = FakeMemoryStore(search_hits=[])
    await _run(store, [MemoryCandidate(text=text, memory_type="fact", confidence=0.9)])
    assert store.added == [] and store.updated == []  # never persisted


async def test_special_category_does_not_suppress_a_benign_sibling() -> None:
    # Same turn yields two candidates: one benign, one special-category. Only the special one
    # is dropped; the unrelated benign candidate is still written.
    store = FakeMemoryStore(search_hits=[])
    await _run(
        store,
        [
            MemoryCandidate(
                text="prefers concise advice", memory_type="preference", confidence=0.8
            ),
            MemoryCandidate(
                text="the user mentioned being on medical leave",
                memory_type="fact",
                confidence=0.9,
            ),
        ],
    )
    assert len(store.added) == 1
    assert store.added[0]["text"] == "prefers concise advice"


async def test_redact_first_then_classify_do_not_fight() -> None:
    # Both a phone number (redact) and a health signal (drop) present. Redaction must not hide
    # the Art. 9 signal: the candidate is still dropped, never written.
    store = FakeMemoryStore(search_hits=[])
    await _run(
        store,
        [
            MemoryCandidate(
                text="call the user on +1 (415) 555-0198 about their cancer treatment",
                memory_type="fact",
                confidence=0.9,
            )
        ],
    )
    assert store.added == []  # dropped despite the redactable phone number


async def test_downvote_reason_candidate_is_also_gated() -> None:
    # The "avoid X" preference synthesised from a down-vote reason is user text too — it must
    # flow through the same gate. A reason mentioning a special category is dropped.
    from app.services.message_feedback import MessageOwner

    store = FakeMemoryStore(search_hits=[])
    feedback = InMemoryMessageFeedbackStore(owners={"m1": MessageOwner(user_id=_UID)})
    await feedback.record(
        message_id="m1",
        rating="down",
        reason="don't assume I'm healthy — I have a chronic illness",
        user_id=_UID,
        session_id="s",
    )
    await run_learn_from_turn(
        user_id=_UID,
        message_id="m1",
        user_text="u",
        assistant_text="a",
        store=store,
        extractor=FakeExtractor([]),
        feedback=feedback,
    )
    assert store.added == []  # the special-category down-vote reason is not made durable
