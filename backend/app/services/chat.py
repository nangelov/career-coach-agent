"""Chat service — the model-driven tool-call loop behind ``POST /api/chat``.

This is P1's **walking skeleton** (plan.md Phase 1: "no multi-agent yet"): a single
service that drives one conversation turn to completion by looping over the LLM
router and the tool registry — **no LangGraph / multi-agent graph** (that is P4).

Layering (Router → Service → Agent/Repository): the FastAPI router
(:mod:`app.api.chat`) is thin request/response + SSE plumbing; **this** service owns
the whole loop and knows nothing about HTTP or SSE. It yields the typed
:class:`~app.schemas.chat.ChatEvent` union, which the API serialises to the wire.

The loop, per user turn:

1. Load prior history for the session, append the new user message.
2. Stream a completion from :class:`~app.llm.router.LLMRouter` with the registry's
   tool schemas, emitting ``token`` events as content flows and accumulating any
   streamed ``tool_calls``.
3. If the model requested tools: emit ``tool_call`` / ``tool_result`` events, append
   the assistant + tool messages, and loop again.
4. If the model returned a plain answer: persist the turn and emit ``done``.
5. A hard **iteration cap** stops runaway tool-call loops; exhausting all LLM models
   (:class:`~app.llm.errors.LLMAllModelsFailedError`) — or any unexpected error —
   surfaces as a single terminal ``error`` event, never an unhandled mid-stream 500.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from uuid import uuid4

from app.llm.errors import LLMAllModelsFailedError, LLMError
from app.llm.router import LLMRouter
from app.llm.types import ChatMessage, FunctionCall, ToolCall, ToolCallDelta
from app.schemas.chat import (
    CancelledEvent,
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    StartEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from app.services.cancellation import CancelRegistry, InMemoryCancelRegistry
from app.services.session_memory import InMemorySessionMemory, SessionMemory
from app.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

#: Default number of model round-trips per turn before the loop gives up (matches
#: v1's ``max_iterations`` spirit) — a guard against infinite tool-call loops.
DEFAULT_MAX_ITERATIONS = 5

#: How often (in streamed chunks) the loop polls the Redis-backed cancel flag while a
#: single model completion is streaming. Per-chunk polling would add a Redis round-trip
#: per token; every N chunks bounds cancel latency to a few tokens while keeping the
#: overhead low. The loop *also* checks once at each iteration boundary.
DEFAULT_CANCEL_CHECK_INTERVAL = 8

#: Minimal career-coach persona for the walking skeleton. Full prompt engineering
#: (and prompt sourcing) lands with the multi-agent graph in P4.
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, encouraging career coach. Give practical, actionable career "
    "guidance. When a tool would help you answer accurately, call it; otherwise "
    "answer directly and concisely."
)


@dataclass
class _ToolCallAccumulator:
    """Reassembles a streamed tool call from its per-``index`` deltas."""

    id: str = ""
    name: str = ""
    arguments: str = ""

    def update(self, delta: ToolCallDelta) -> None:
        if delta.id:
            self.id = delta.id
        if delta.name:
            self.name = delta.name
        if delta.arguments:
            self.arguments += delta.arguments

    def to_tool_call(self) -> ToolCall:
        return ToolCall(
            id=self.id or uuid4().hex,
            function=FunctionCall(name=self.name, arguments=self.arguments),
        )


@dataclass
class _Turn:
    """Mutable state accumulated while streaming one turn."""

    #: Messages sent to the model this turn (history + user + tool round-trips).
    messages: list[ChatMessage]
    #: New messages produced this turn, to persist to session memory on success.
    produced: list[ChatMessage] = field(default_factory=list)


@dataclass
class _IterationResult:
    """Out-parameter for :meth:`ChatService._run_iteration` (async generators can
    stream events but cannot ``return`` a value, so results land here)."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    #: Set when the iteration stopped early because a cancel was observed mid-stream;
    #: ``content`` then holds the partial answer streamed so far.
    cancelled: bool = False


class ChatService:
    """Drives one chat turn: model ⇄ tools loop → a stream of :class:`ChatEvent`.

    Depends on the :class:`~app.llm.router.LLMRouter` (reliability/failover),
    :class:`~app.tools.base.ToolRegistry` (native tools), a
    :class:`~app.services.session_memory.SessionMemory` (conversation history), and a
    :class:`~app.services.cancellation.CancelRegistry` (stop/cancel signal) — all
    injected, so tests drive it with fakes and the Redis-backed implementations are
    wired at the composition root.
    """

    def __init__(
        self,
        router: LLMRouter,
        registry: ToolRegistry,
        memory: SessionMemory | None = None,
        cancel: CancelRegistry | None = None,
        *,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
        cancel_check_interval: int = DEFAULT_CANCEL_CHECK_INTERVAL,
    ) -> None:
        self._router = router
        self._registry = registry
        self._memory = memory if memory is not None else InMemorySessionMemory()
        self._cancel = cancel if cancel is not None else InMemoryCancelRegistry()
        self._max_iterations = max(1, max_iterations)
        self._system_prompt = system_prompt
        self._cancel_check_interval = max(1, cancel_check_interval)

    async def aclose(self) -> None:
        """Release the underlying router's resources (best-effort)."""
        await self._router.aclose()

    async def request_cancel(self, session_id: str) -> None:
        """Request cancellation of the in-flight turn for ``session_id``.

        Backs ``POST /api/chat/{session}/cancel`` (design §9): sets the Redis-backed
        cancel flag and returns immediately — it does **not** wait for the in-flight
        stream to actually stop. The streaming turn observes the flag at its next
        checkpoint (iteration boundary or every few chunks) and ends the SSE stream
        cleanly with a terminal ``cancelled`` event.
        """
        await self._cancel.request(session_id)

    async def stream_turn(
        self,
        session_id: str,
        user_message: str,
        *,
        history: Sequence[ChatMessage] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Run one user turn to completion, yielding SSE-ready events.

        Args:
            session_id: The conversation key (interim in-memory store; Redis in P1-05).
            user_message: The new user message text.
            history: Optional caller-supplied prior turns; when given it seeds this
                turn instead of the server-side session memory (still persisted back
                under ``session_id``).

        Yields:
            :class:`ChatEvent` values: ``start`` → ``token``/``tool_call``/
            ``tool_result`` (repeated) → ``done`` on success, or a terminal ``error``.
        """
        # The single generation point for the turn's stable, feedback-ready id
        # (design §5.5). Assigned once here and reused for every ``message_id``-bearing
        # SSE event (``start`` → ``done``/``cancelled``) and stamped onto the persisted
        # user-facing assistant answer — never regenerated mid-turn. uuid4 gives
        # uniqueness across turns and sessions.
        message_id = uuid4().hex
        prior = list(history) if history is not None else await self._memory.load(session_id)

        base: list[ChatMessage] = []
        if self._system_prompt:
            base.append(ChatMessage(role="system", content=self._system_prompt))
        base.extend(prior)

        user_msg = ChatMessage(role="user", content=user_message)
        turn = _Turn(messages=[*base, user_msg], produced=[user_msg])

        yield StartEvent(message_id=message_id)

        # A fresh turn is never born cancelled: drop any stale flag left on this
        # session (e.g. a cancel that raced a previous, already-finished turn) so it
        # cannot wrongly abort this one. The cancel *for this turn* arrives later,
        # while we are streaming below.
        await self._cancel.clear(session_id)

        try:
            for _ in range(self._max_iterations):
                # Cancel observed between tool round-trips → stop before the next model
                # call (covers a long tool step completing just after a cancel).
                if await self._cancel.is_requested(session_id):
                    yield await self._finish_cancelled(session_id, turn, message_id)
                    return

                result = _IterationResult()
                # Relay content tokens the instant they arrive (token-by-token SSE).
                async for event in self._run_iteration(turn, result, session_id):
                    yield event

                if result.cancelled:
                    # Stopped mid-completion; persist the partial answer for continuity.
                    # It keeps the turn's ``message_id`` so a 👍/👎 on the cut-off answer
                    # the user actually saw resolves to this stored message (§5.5).
                    if result.content:
                        turn.produced.append(
                            ChatMessage(
                                role="assistant",
                                content=result.content,
                                message_id=message_id,
                            )
                        )
                    yield await self._finish_cancelled(session_id, turn, message_id)
                    return

                if not result.tool_calls:
                    # Plain answer → the turn is done. The user-facing assistant answer
                    # carries the turn's stable ``message_id`` so it survives the session-
                    # memory round trip and is feedback-addressable later (§5.5).
                    turn.produced.append(
                        ChatMessage(role="assistant", content=result.content, message_id=message_id)
                    )
                    await self._memory.append(session_id, turn.produced)
                    yield DoneEvent(message_id=message_id, finish_reason=result.finish_reason)
                    return

                # The model asked for tools: record the request, run each tool,
                # append its result, then loop for the model's next step. This
                # intermediate tool-request message is internal scaffolding (not the
                # user-facing answer), so it deliberately carries **no** ``message_id`` —
                # keeping the turn's id a 1:1 handle for the answer the user reacts to.
                assistant_msg = ChatMessage(
                    role="assistant", content=result.content, tool_calls=result.tool_calls
                )
                turn.messages.append(assistant_msg)
                turn.produced.append(assistant_msg)
                for call in result.tool_calls:
                    yield ToolCallEvent(
                        id=call.id, name=call.function.name, arguments=call.function.arguments
                    )
                    tool_msg = await self._registry.execute(call)
                    turn.messages.append(tool_msg)
                    turn.produced.append(tool_msg)
                    yield ToolResultEvent(
                        tool_call_id=call.id,
                        name=tool_msg.name or call.function.name,
                        content=tool_msg.content or "",
                    )

            # Fell out of the loop → the model kept calling tools past the cap.
            await self._memory.append(session_id, turn.produced)
            logger.warning("chat turn hit iteration cap (%d)", self._max_iterations)
            yield ErrorEvent(
                message="Reached the maximum number of tool-call steps without a final answer."
            )
        except LLMAllModelsFailedError:
            logger.warning("chat turn failed: all LLM models unavailable", exc_info=True)
            yield ErrorEvent(
                message="The assistant is temporarily unavailable. Please try again shortly."
            )
        except LLMError:
            logger.warning("chat turn failed with an LLM error", exc_info=True)
            yield ErrorEvent(message="The assistant hit an error handling your request.")
        except Exception:  # noqa: BLE001 - never leak an unhandled 500 mid-stream
            logger.exception("chat turn failed with an unexpected error")
            yield ErrorEvent(message="An unexpected error occurred. Please try again.")

    async def _finish_cancelled(
        self, session_id: str, turn: _Turn, message_id: str
    ) -> CancelledEvent:
        """Clear the flag, persist what was produced, and build the terminal event.

        Persisting ``turn.produced`` (the user message, any completed tool round-trips,
        and — on a mid-completion stop — the partial assistant answer) keeps the
        conversation coherent for the next turn. The flag is deleted so it cannot leak
        into a future request on this ``session_id`` (belt-and-braces with its TTL).
        """
        await self._cancel.clear(session_id)
        await self._memory.append(session_id, turn.produced)
        logger.info("chat turn cancelled by client (session=%s)", session_id)
        return CancelledEvent(message_id=message_id)

    async def _run_iteration(
        self, turn: _Turn, result: _IterationResult, session_id: str
    ) -> AsyncIterator[ChatEvent]:
        """Stream one model completion, yielding ``token`` events as content arrives.

        Content deltas are yielded immediately (token-by-token SSE); tool-call deltas
        are reassembled by ``index``. The accumulated content, reassembled tool
        calls, and terminal ``finish_reason`` are written to ``result`` (an async
        generator cannot ``return`` them).

        The Redis-backed cancel flag is polled every ``cancel_check_interval`` chunks so
        a long single completion stops promptly; on cancel the iteration returns early
        with ``result.cancelled = True`` and the partial content captured. The router
        stream is explicitly closed in ``finally`` so an early return (cancel) does not
        leak the underlying async generator or its upstream HTTP connection.
        """
        content_parts: list[str] = []
        tool_accs: dict[int, _ToolCallAccumulator] = {}
        chunk_count = 0

        stream = self._router.stream(turn.messages, tools=self._registry.schemas())
        try:
            async for chunk in stream:
                if chunk.content:
                    content_parts.append(chunk.content)
                    yield TokenEvent(content=chunk.content)
                if chunk.tool_call_deltas:
                    for delta in chunk.tool_call_deltas:
                        tool_accs.setdefault(delta.index, _ToolCallAccumulator()).update(delta)
                if chunk.finish_reason:
                    result.finish_reason = chunk.finish_reason

                chunk_count += 1
                if chunk_count % self._cancel_check_interval == 0:
                    if await self._cancel.is_requested(session_id):
                        result.cancelled = True
                        result.content = "".join(content_parts) or None
                        return
        finally:
            # Deterministic cleanup: closing the async generator on an early cancel
            # return releases the upstream stream/connection promptly (rather than at
            # GC). ``aclose`` is a no-op on an already-exhausted stream. Guarded by
            # getattr since the router's public type is only ``AsyncIterator``.
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

        result.tool_calls = [tool_accs[index].to_tool_call() for index in sorted(tool_accs)]
        result.content = "".join(content_parts) or None
