"""Chat-service durable-persistence behaviour (P2-07).

Drives :class:`~app.services.chat.ChatService` with a **fake**
:class:`~app.services.conversation_store.ConversationStore` (plus the scripted
``GraphTurnRunner`` fake) to assert the Postgres-persistence wiring *without* a live DB:

* a logged-in turn (``user_id`` set) is persisted (user + assistant, carrying ``message_id``),
* a **guest** turn (no ``user_id``) persists **nothing** — an explicit assertion (§4),
* a cancelled turn persists its partial answer for a logged-in user,
* **restart simulation**: with Redis working memory empty, a logged-in turn rehydrates its
  context from the conversation store,
* a persistence failure is swallowed and never breaks the SSE stream.

The Postgres adapter itself is covered against a real database in
``tests/test_conversation_store.py``.
"""

from __future__ import annotations

from typing import Any, cast

from app.llm.types import ChatMessage, StreamChunk
from app.schemas.chat import (
    CancelledEvent,
    ChatEvent,
    DoneEvent,
)
from app.services.cancellation import CancelRegistry
from app.services.chat import ChatService, GraphTurnRunner
from app.services.conversation_store import ConversationStore
from app.services.session_memory import InMemorySessionMemory, SessionMemory
from tests.fakes import FakeGraphRunner

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeConversationStore(ConversationStore):
    """In-memory :class:`ConversationStore` recording persist calls and replaying history."""

    def __init__(self) -> None:
        #: (user_id, session_id, user_message, assistant_message) per persist_turn call.
        self.persisted: list[tuple[str, str, ChatMessage, ChatMessage | None]] = []
        self._history: dict[tuple[str, str], list[ChatMessage]] = {}

    async def persist_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        conversation_id: str | None,
        user_message: ChatMessage,
        assistant_message: ChatMessage | None,
    ) -> str:
        self.persisted.append((user_id, session_id, user_message, assistant_message))
        hist = self._history.setdefault((user_id, session_id), [])
        hist.append(user_message)
        if assistant_message is not None:
            hist.append(assistant_message)
        return "conv-1"

    async def load_history(self, *, user_id: str, session_id: str) -> list[ChatMessage]:
        return list(self._history.get((user_id, session_id), []))

    def seed(self, user_id: str, session_id: str, messages: list[ChatMessage]) -> None:
        """Pre-populate durable history (test setup helper)."""
        self._history[(user_id, session_id)] = list(messages)


class RaisingConversationStore(ConversationStore):
    """A store whose every method raises — proves persistence failures are swallowed."""

    async def persist_turn(self, **_: Any) -> str:
        raise RuntimeError("db down")

    async def load_history(self, **_: Any) -> list[ChatMessage]:
        raise RuntimeError("db down")


class _TrippingCancel(CancelRegistry):
    """Reports 'requested' after ``trip_after`` polls (mid-stream cancel simulation)."""

    def __init__(self, trip_after: int) -> None:
        self._trip_after = trip_after
        self.polls = 0

    async def request(self, session_id: str) -> None:  # pragma: no cover - unused
        pass

    async def is_requested(self, session_id: str) -> bool:
        self.polls += 1
        return self.polls > self._trip_after

    async def clear(self, session_id: str) -> None:
        pass


def _service(
    runner: FakeGraphRunner,
    *,
    store: ConversationStore | None = None,
    memory: SessionMemory | None = None,
    cancel: CancelRegistry | None = None,
    **kwargs: Any,
) -> ChatService:
    """Build a :class:`ChatService` from the fakes (cast confines the type seam here)."""
    return ChatService(
        cast(GraphTurnRunner, runner),
        memory if memory is not None else InMemorySessionMemory(),
        cancel,
        conversations=store,
        **kwargs,
    )


async def _collect(
    service: ChatService, session: str, message: str, *, user_id: str | None = None
) -> list[ChatEvent]:
    return [event async for event in service.stream_turn(session, message, user_id=user_id)]


# --------------------------------------------------------------------------- #
# Logged-in turn persists; guest turn does not
# --------------------------------------------------------------------------- #
async def test_logged_in_turn_persists_user_and_assistant() -> None:
    router = FakeGraphRunner([[StreamChunk(content="Hello!", finish_reason="stop")]])
    store = FakeConversationStore()
    service = _service(router, store=store)

    events = await _collect(service, "s1", "hi", user_id="user-1")

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    assert len(store.persisted) == 1
    user_id, session_id, user_msg, assistant_msg = store.persisted[0]
    assert user_id == "user-1"
    assert session_id == "s1"
    assert user_msg.role == "user" and user_msg.content == "hi"
    assert assistant_msg is not None
    assert assistant_msg.role == "assistant" and assistant_msg.content == "Hello!"
    # The persisted assistant answer carries the turn's stable message_id (§5.5).
    assert assistant_msg.message_id == done[0].message_id


async def test_guest_turn_persists_nothing() -> None:
    router = FakeGraphRunner([[StreamChunk(content="Hello!", finish_reason="stop")]])
    store = FakeConversationStore()
    service = _service(router, store=store)

    # No user_id → guest → nothing durable, even though a store is wired.
    events = await _collect(service, "s1", "hi", user_id=None)

    assert any(isinstance(e, DoneEvent) for e in events)
    assert store.persisted == []


async def test_no_store_wired_is_a_noop() -> None:
    # A logged-in turn with no ConversationStore behaves exactly like P1 (no crash).
    router = FakeGraphRunner([[StreamChunk(content="Hello!", finish_reason="stop")]])
    service = _service(router)

    events = await _collect(service, "s1", "hi", user_id="user-1")

    assert any(isinstance(e, DoneEvent) for e in events)


# --------------------------------------------------------------------------- #
# Cancelled turn persists its partial answer
# --------------------------------------------------------------------------- #
async def test_cancelled_turn_persists_partial_answer() -> None:
    router = FakeGraphRunner([[StreamChunk(content=f"tok{i}") for i in range(20)]])
    store = FakeConversationStore()
    service = _service(
        router, store=store, cancel=_TrippingCancel(trip_after=2), cancel_check_interval=1
    )

    events = await _collect(service, "s1", "hi", user_id="user-1")

    assert isinstance(events[-1], CancelledEvent)
    assert len(store.persisted) == 1
    _, _, user_msg, assistant_msg = store.persisted[0]
    assert user_msg.content == "hi"
    # The partial answer (whatever streamed before the cancel) was persisted.
    assert assistant_msg is not None
    assert assistant_msg.role == "assistant"
    assert assistant_msg.content
    assert assistant_msg.message_id == events[-1].message_id


# --------------------------------------------------------------------------- #
# Restart simulation: rehydrate context from the store when Redis is empty
# --------------------------------------------------------------------------- #
async def test_restart_rehydrates_history_from_store() -> None:
    store = FakeConversationStore()

    # Turn 1 on the "first process": persisted to the durable store.
    router1 = FakeGraphRunner([[StreamChunk(content="I am well", finish_reason="stop")]])
    service1 = _service(router1, store=store)
    _ = await _collect(service1, "s1", "how are you", user_id="user-1")

    # "Restart": a brand-new service with an EMPTY session memory (Redis lost the key),
    # same durable store. Turn 2 must see turn 1's context, loaded from the store.
    router2 = FakeGraphRunner([[StreamChunk(content="Great, thanks", finish_reason="stop")]])
    service2 = _service(router2, store=store)
    _ = await _collect(service2, "s1", "and now", user_id="user-1")

    # The (only) turn on the restarted service carries the rehydrated turn-1 pair as its
    # graph-state history, with the new message as the current turn.
    turn2 = router2.plan_states[0]
    history = [m.content for m in turn2.history]
    assert "how are you" in history
    assert "I am well" in history
    assert turn2.user_message == "and now"


async def test_restart_preserves_context_across_multiple_turns() -> None:
    """Regression for C1: turn 2+ after a restart must still carry pre-restart context.

    A *single* post-restart turn rehydrates from the durable store fine. But unless that
    rehydrated history is seeded back into the (fresh) Redis working memory, the next turn
    finds Redis non-empty — holding only turn 1's newly produced pair — and skips the
    rehydration branch entirely, silently starting from a truncated context and losing all
    pre-restart history from turn 2 onward. This drives two post-restart turns and asserts
    the second still sees turn 1.
    """
    store = FakeConversationStore()

    # Turn 1 on the "first process": persisted to the durable store.
    router1 = FakeGraphRunner([[StreamChunk(content="A1", finish_reason="stop")]])
    _ = await _collect(_service(router1, store=store), "s1", "Q1", user_id="user-1")

    # "Restart": one fresh service with an EMPTY session memory (Redis lost the key) drives
    # both post-restart turns, so its Redis working memory persists between turn 2 and turn 3.
    memory = InMemorySessionMemory()
    router2 = FakeGraphRunner(
        [
            [StreamChunk(content="A2", finish_reason="stop")],
            [StreamChunk(content="A3", finish_reason="stop")],
        ]
    )
    service = _service(router2, store=store, memory=memory)
    _ = await _collect(service, "s1", "Q2", user_id="user-1")  # turn 2 (rehydrates + seeds)
    _ = await _collect(service, "s1", "Q3", user_id="user-1")  # turn 3 (reads seeded Redis)

    # Turn 3's graph state must still include turn 1's rehydrated pair (would be missing if
    # turn 2 had not seeded Redis with the rehydrated history — the C1 defect).
    turn3 = router2.plan_states[1]
    turn3_history = [m.content for m in turn3.history]
    assert "Q1" in turn3_history
    assert "A1" in turn3_history
    assert "Q2" in turn3_history
    assert "A2" in turn3_history
    assert turn3.user_message == "Q3"


async def test_no_rehydration_for_guest() -> None:
    # A guest turn never reads durable history even if the store happens to hold some.
    store = FakeConversationStore()
    store.seed("user-1", "s1", [ChatMessage(role="user", content="secret")])

    router = FakeGraphRunner([[StreamChunk(content="ok", finish_reason="stop")]])
    service = _service(router, store=store)
    _ = await _collect(service, "s1", "hi", user_id=None)

    history = [m.content for m in router.plan_states[0].history]
    assert "secret" not in history


# --------------------------------------------------------------------------- #
# Persistence failures never break the stream
# --------------------------------------------------------------------------- #
async def test_persist_failure_does_not_break_stream() -> None:
    router = FakeGraphRunner([[StreamChunk(content="Hello!", finish_reason="stop")]])
    service = _service(router, store=RaisingConversationStore())

    events = await _collect(service, "s1", "hi", user_id="user-1")

    # The turn still completes cleanly despite the store raising on persist.
    assert isinstance(events[-1], DoneEvent)


async def test_rehydration_failure_falls_back_to_empty() -> None:
    router = FakeGraphRunner([[StreamChunk(content="Hello!", finish_reason="stop")]])
    service = _service(router, store=RaisingConversationStore())

    events = await _collect(service, "s1", "hi", user_id="user-1")

    # A load_history failure is swallowed: the turn proceeds with an empty history context.
    assert isinstance(events[-1], DoneEvent)
    turn = router.plan_states[0]
    assert turn.history == []
    assert turn.user_message == "hi"
