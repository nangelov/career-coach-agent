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
from app.services.conversation_store import ConversationStore
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
    :class:`~app.services.session_memory.SessionMemory` (conversation history), a
    :class:`~app.services.cancellation.CancelRegistry` (stop/cancel signal), and an
    optional :class:`~app.services.conversation_store.ConversationStore` (durable
    Postgres history for logged-in users) — all injected, so tests drive it with fakes and
    the Redis/Postgres-backed implementations are wired at the composition root.

    The ``ConversationStore`` is optional: when absent (``None``) — the guest path, or any
    deployment without a Postgres provider — the service behaves exactly as in P1 (Redis
    working memory only, no durable writes). When present, a turn from a logged-in user
    (``user_id`` set on :meth:`stream_turn`) is *also* persisted to Postgres so the
    conversation survives a restart / Redis eviction (design §4).
    """

    def __init__(
        self,
        router: LLMRouter,
        registry: ToolRegistry,
        memory: SessionMemory | None = None,
        cancel: CancelRegistry | None = None,
        *,
        conversations: ConversationStore | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
        cancel_check_interval: int = DEFAULT_CANCEL_CHECK_INTERVAL,
    ) -> None:
        self._router = router
        self._registry = registry
        # ``memory``/``cancel`` are optional so unit tests can omit them and get the
        # process-local in-memory doubles. But a *production* composition that silently
        # falls back here would reintroduce v1's per-process global-state anti-pattern (the
        # exact failure mode v2 exists to remove) with no signal — so warn loudly when the
        # fallback is taken. (Kept optional rather than required to avoid churning the many
        # unit tests that legitimately omit these; the warning gives the mis-wire signal.)
        fallbacks = [
            name for name, value in (("memory", memory), ("cancel", cancel)) if value is None
        ]
        if fallbacks:
            logger.warning(
                "ChatService using in-memory %s fallback(s) — process-local test double(s), "
                "not for production. A production composition must inject the Redis-backed "
                "adapters (see app.bootstrap.build_chat_service).",
                ", ".join(fallbacks),
            )
        self._memory = memory if memory is not None else InMemorySessionMemory()
        self._cancel = cancel if cancel is not None else InMemoryCancelRegistry()
        self._conversations = conversations
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
        user_id: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        """Run one user turn to completion, yielding SSE-ready events.

        Args:
            session_id: The conversation key (interim in-memory store; Redis in P1-05).
            user_message: The new user message text.
            history: Optional caller-supplied prior turns; when given it seeds this
                turn instead of the server-side session memory (still persisted back
                under ``session_id``).
            user_id: Interim (P2-07) logged-in user id, or ``None`` for a guest. When set
                and a :class:`~app.services.conversation_store.ConversationStore` is wired,
                the turn is durably persisted to Postgres (and, if Redis working memory is
                empty, its context is rehydrated from Postgres) so account history survives
                a restart. ``None`` → guest → the unchanged P1 behavior (Redis only).

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
        prior = await self._load_prior(session_id, history, user_id)

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
                    # No assistant answer was produced this turn; persist the user's
                    # question alone so a logged-in user's turn is not silently dropped.
                    await self._persist_turn(user_id, session_id, user_msg, None)
                    return

                result = _IterationResult()
                # Relay content tokens the instant they arrive (token-by-token SSE).
                async for event in self._run_iteration(turn, result, session_id):
                    yield event

                if result.cancelled:
                    # Stopped mid-completion; persist the partial answer for continuity.
                    # It keeps the turn's ``message_id`` so a 👍/👎 on the cut-off answer
                    # the user actually saw resolves to this stored message (§5.5).
                    partial_assistant: ChatMessage | None = None
                    if result.content:
                        partial_assistant = ChatMessage(
                            role="assistant",
                            content=result.content,
                            message_id=message_id,
                        )
                        turn.produced.append(partial_assistant)
                    yield await self._finish_cancelled(session_id, turn, message_id)
                    # Persist the partial turn for logged-in users too (parity with the
                    # Redis persist-on-cancel above), after the terminal event.
                    await self._persist_turn(user_id, session_id, user_msg, partial_assistant)
                    return

                if not result.tool_calls:
                    # Plain answer → the turn is done. The user-facing assistant answer
                    # carries the turn's stable ``message_id`` so it survives the session-
                    # memory round trip and is feedback-addressable later (§5.5).
                    final_assistant = ChatMessage(
                        role="assistant", content=result.content, message_id=message_id
                    )
                    turn.produced.append(final_assistant)
                    await self._memory.append(session_id, turn.produced)
                    yield DoneEvent(message_id=message_id, finish_reason=result.finish_reason)
                    # Durable persist happens *after* the terminal event is yielded so the
                    # DB write never delays the user-visible stream; best-effort (logged,
                    # never raised — see _persist_turn).
                    await self._persist_turn(user_id, session_id, user_msg, final_assistant)
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
            # No assistant answer was produced, but persist the user's question alone (as the
            # cancel-before-content path does) so a logged-in user's turn is not silently
            # dropped from durable history on the iteration-cap path.
            await self._persist_turn(user_id, session_id, user_msg, None)
        # The terminal-error handlers below deliberately do NOT persist: an errored turn is a
        # failure (all models down / unexpected error), and the except may itself be triggered
        # by a datastore issue — attempting a DB write there would be futile and noisy.
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

    async def _load_prior(
        self,
        session_id: str,
        history: Sequence[ChatMessage] | None,
        user_id: str | None,
    ) -> list[ChatMessage]:
        """Resolve the prior turns that seed this turn's context.

        Precedence: an explicit caller-supplied ``history`` wins; otherwise the Redis
        working memory; and — only for a logged-in user whose Redis memory is empty
        (fresh Redis / TTL expired / app restarted) — the durable Postgres history. This
        Postgres fallback is what makes account chat history survive a restart (design §4).
        The fallback is best-effort: a load failure must not break the turn, so it logs and
        falls back to an empty context rather than raising.
        """
        if history is not None:
            return list(history)
        prior = await self._memory.load(session_id)
        if prior or not user_id or self._conversations is None:
            return prior
        try:
            loaded = await self._conversations.load_history(user_id=user_id, session_id=session_id)
        except Exception:  # noqa: BLE001 - a durable-history read must never break the turn
            logger.warning(
                "failed to rehydrate history from Postgres (session=%s)", session_id, exc_info=True
            )
            return []
        # Seed the (empty) Redis working memory with what we just rehydrated so the *next*
        # turn on this session finds the full context in Redis and does not skip this
        # rehydration branch. Without this, only the first post-restart turn would see the
        # pre-restart history: turn 2 would find Redis non-empty (holding just turn 1's new
        # pair) and silently start from a truncated context, losing all pre-restart context.
        if loaded:
            await self._memory.append(session_id, loaded)
        return loaded

    async def _persist_turn(
        self,
        user_id: str | None,
        session_id: str,
        user_message: ChatMessage,
        assistant_message: ChatMessage | None,
    ) -> None:
        """Durably persist a completed/cancelled turn for a logged-in user (best-effort).

        A no-op for guests (``user_id is None``) or when no
        :class:`~app.services.conversation_store.ConversationStore` is wired — that is the
        unchanged P1 guest path (Redis only, nothing in Postgres). A persistence failure is
        logged and swallowed: it must **never** break the user-visible SSE stream (which has
        already delivered its terminal event by this point).
        """
        if not user_id or self._conversations is None:
            return
        try:
            await self._conversations.persist_turn(
                user_id=user_id,
                session_id=session_id,
                conversation_id=None,
                user_message=user_message,
                assistant_message=assistant_message,
            )
        except Exception:  # noqa: BLE001 - persistence must never break the stream
            logger.warning(
                "failed to persist turn to Postgres (session=%s)", session_id, exc_info=True
            )

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
