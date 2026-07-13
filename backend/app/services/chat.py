"""Chat service — drives one turn through the multi-agent graph behind ``POST /api/chat``.

This is the P4 graph-driven replacement for P1's walking skeleton. Instead of a single
LLM-router + tool-registry loop, a turn is now run through the compiled multi-agent
LangGraph (:mod:`app.agents.graph`): **guardrails → recall → planner → workers →
responder** (design §3). The service owns the cross-cutting concerns the graph does *not*
— session history, durable persistence, cancel/stop — and translates the graph's output
into the typed :class:`~app.schemas.chat.ChatEvent` SSE stream.

Layering (Router → Service → Agent/Repository): the FastAPI router
(:mod:`app.api.chat`) stays a thin request/response + SSE plumbing layer; **this** service
owns the turn and knows nothing about HTTP or SSE. The graph itself is injected as a
:class:`GraphTurnRunner` (structurally the :class:`~app.agents.graph.GraphTurnStreamer`
wired at the composition root) so the service depends on a *capability*, not on LangGraph —
and unit tests drive it with a fake runner.

The turn, per user message:

1. Load prior history for the session; build an :class:`~app.agents.state.AgentState`.
2. Run the pre-responder pipeline (:meth:`GraphTurnRunner.plan`) — planner classifies the
   intent and fans out to the selected workers — then emit a ``plan`` event so the client
   can show which workers ran.
3. Stream the responder's answer token-by-token (:meth:`GraphTurnRunner.stream_response`),
   emitting ``token`` events; poll the Redis-backed cancel flag periodically.
4. Persist the turn (session memory + durable Postgres for logged-in users) and emit
   ``done`` carrying the answer's citations.
5. A cancel observed at a checkpoint ends the stream with a terminal ``cancelled`` event
   (persisting any partial answer); an unexpected failure surfaces as a single terminal
   ``error`` event — never an unhandled mid-stream 500. The graph nodes themselves fail
   soft (planner / workers / responder degrade rather than raise), so an all-models-down
   turn now yields a graceful fallback answer + ``done`` rather than an ``error`` event.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import uuid4

from app.agents.state import AgentState, Citation
from app.guardrails import screen_output
from app.llm.errors import LLMAllModelsFailedError, LLMError
from app.llm.types import ChatMessage, StreamChunk
from app.schemas.auth import SessionRole
from app.schemas.chat import (
    CancelledEvent,
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    PlanEvent,
    SourceCitation,
    StartEvent,
    TokenEvent,
)
from app.services.cancellation import CancelRegistry, InMemoryCancelRegistry
from app.services.conversation_store import ConversationStore
from app.services.session_memory import InMemorySessionMemory, SessionMemory

logger = logging.getLogger(__name__)

#: How often (in streamed chunks) the loop polls the Redis-backed cancel flag while the
#: responder is streaming. Per-chunk polling would add a Redis round-trip per token; every N
#: chunks bounds cancel latency to a few tokens while keeping overhead low. The service also
#: checks the flag once before the (latent) graph run and once before the token stream.
DEFAULT_CANCEL_CHECK_INTERVAL = 8


@runtime_checkable
class GraphTurnRunner(Protocol):
    """The graph capability the chat service needs: plan a turn, then stream its answer.

    A structural :class:`~typing.Protocol` (not a hard import of
    :class:`~app.agents.graph.GraphTurnStreamer`) so the service depends on a *capability*,
    not on LangGraph — the compiled-once streamer satisfies this shape in production and unit
    tests inject a scripted fake. Split into two phases so a latent multi-agent turn stays
    cancellable between planning and responding, and its plan/worker steps can be surfaced
    before tokens stream.
    """

    async def plan(self, state: AgentState) -> AgentState:
        """Run the pre-responder pipeline; return the merged turn state (plan + workers)."""
        ...

    def stream_response(self, state: AgentState) -> AsyncIterator[StreamChunk]:
        """Stream the responder's token deltas over the merged ``state``."""
        ...

    async def aclose(self) -> None:
        """Release the underlying LLM resources (best-effort)."""
        ...


@dataclass
class _ResponseResult:
    """Accumulated result of streaming the responder (async generators can't ``return``)."""

    content: str = ""
    finish_reason: str | None = None
    #: Set when streaming stopped early because a cancel was observed; ``content`` then holds
    #: the partial answer streamed so far.
    cancelled: bool = False


class ChatService:
    """Drives one chat turn through the multi-agent graph → a stream of :class:`ChatEvent`.

    Depends on a :class:`GraphTurnRunner` (the compiled multi-agent graph), a
    :class:`~app.services.session_memory.SessionMemory` (conversation history), a
    :class:`~app.services.cancellation.CancelRegistry` (stop/cancel signal), and an optional
    :class:`~app.services.conversation_store.ConversationStore` (durable Postgres history for
    logged-in users) — all injected, so tests drive it with fakes and the Redis/Postgres/graph
    implementations are wired at the composition root (:func:`app.bootstrap.build_chat_service`).

    The ``ConversationStore`` is optional: when absent (``None``) — the guest path, or any
    deployment without a Postgres provider — the service behaves as Redis working-memory only.
    When present, a logged-in user's turn (``user_id`` set on :meth:`stream_turn`) is *also*
    persisted to Postgres so the conversation survives a restart / Redis eviction (design §4).
    """

    def __init__(
        self,
        runner: GraphTurnRunner,
        memory: SessionMemory | None = None,
        cancel: CancelRegistry | None = None,
        *,
        conversations: ConversationStore | None = None,
        cancel_check_interval: int = DEFAULT_CANCEL_CHECK_INTERVAL,
    ) -> None:
        self._runner = runner
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
        self._cancel_check_interval = max(1, cancel_check_interval)

    async def aclose(self) -> None:
        """Release the underlying graph runner's resources (best-effort)."""
        await self._runner.aclose()

    async def request_cancel(self, session_id: str) -> None:
        """Request cancellation of the in-flight turn for ``session_id``.

        Backs ``POST /api/chat/{session}/cancel`` (design §9): sets the Redis-backed cancel
        flag and returns immediately — it does **not** wait for the in-flight stream to stop.
        The streaming turn observes the flag at its next checkpoint (before the graph run,
        before the token stream, or every few chunks) and ends the SSE stream cleanly with a
        terminal ``cancelled`` event.
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
            session_id: The conversation key (Redis-backed session memory).
            user_message: The new user message text.
            history: Optional caller-supplied prior turns; when given it seeds this turn
                instead of the server-side session memory (still persisted under ``session_id``).
            user_id: Logged-in user id, or ``None`` for a guest. When set and a
                :class:`~app.services.conversation_store.ConversationStore` is wired, the turn is
                durably persisted to Postgres (and, if Redis working memory is empty, its context
                is rehydrated from Postgres) so account history survives a restart. ``None`` →
                guest → Redis-only.

        Yields:
            :class:`ChatEvent` values: ``start`` → ``plan`` → ``token`` (repeated) → ``done``
            on success, or a terminal ``cancelled`` / ``error``.
        """
        # The single generation point for the turn's stable, feedback-ready id (design §5.5).
        # Assigned once here, threaded through the graph (``AgentState.message_id``), reused for
        # every ``message_id``-bearing event, and stamped onto the persisted assistant answer.
        message_id = uuid4().hex
        prior = await self._load_prior(session_id, history, user_id)

        role: SessionRole = "user" if user_id else "guest"
        user_msg = ChatMessage(role="user", content=user_message)
        state = AgentState(
            session_id=session_id,
            user_id=user_id,
            role=role,
            user_message=user_message,
            message_id=message_id,
            history=list(prior),
        )

        yield StartEvent(message_id=message_id)

        # A fresh turn is never born cancelled: drop any stale flag left on this session (e.g. a
        # cancel that raced a previous, already-finished turn) so it cannot wrongly abort this
        # one. The cancel *for this turn* arrives later, while we are running/streaming below.
        await self._cancel.clear(session_id)

        try:
            # Checkpoint before the (latent) multi-agent run — a cancel that arrived before we
            # started must stop the turn without doing the planner/worker work.
            if await self._cancel.is_requested(session_id):
                yield await self._finish_cancelled(session_id, [user_msg], message_id)
                await self._persist_turn(user_id, session_id, user_msg, None)
                return

            # Phase 1: planner classifies the intent and fans out to workers. Surface the plan
            # (which workers ran) before tokens so the UI can render the "thinking" steps.
            merged = await self._runner.plan(state)
            if merged.plan is not None:
                yield PlanEvent(
                    intent=merged.plan.intent.value,
                    steps=list(merged.plan.steps),
                    workers=[w.value for w in merged.plan.workers],
                )

            # Checkpoint after planning/workers (a more latent step than a single completion)
            # and before the token stream opens.
            if await self._cancel.is_requested(session_id):
                yield await self._finish_cancelled(session_id, [user_msg], message_id)
                await self._persist_turn(user_id, session_id, user_msg, None)
                return

            # Phase 2: stream the responder's answer token-by-token.
            result = _ResponseResult()
            async for event in self._stream_response(merged, result, session_id):
                yield event

            if result.cancelled:
                # Stopped mid-answer; persist the partial answer for continuity. It keeps the
                # turn's ``message_id`` so a 👍/👎 on the cut-off answer resolves here (§5.5).
                partial: ChatMessage | None = None
                produced: list[ChatMessage] = [user_msg]
                if result.content:
                    partial = ChatMessage(
                        role="assistant", content=result.content, message_id=message_id
                    )
                    produced.append(partial)
                yield await self._finish_cancelled(session_id, produced, message_id)
                await self._persist_turn(user_id, session_id, user_msg, partial)
                return

            # Success: the user-facing answer carries the turn's stable ``message_id`` so it
            # survives the session-memory round trip and is feedback-addressable later (§5.5).
            assistant = ChatMessage(role="assistant", content=result.content, message_id=message_id)
            await self._memory.append(session_id, [user_msg, assistant])
            yield DoneEvent(
                message_id=message_id,
                finish_reason=result.finish_reason or "stop",
                citations=_to_source_citations(merged.citations),
            )
            # Durable persist happens *after* the terminal event so the DB write never delays the
            # user-visible stream; best-effort (logged, never raised — see _persist_turn).
            await self._persist_turn(user_id, session_id, user_msg, assistant)
        # The terminal-error handlers below deliberately do NOT persist: an errored turn is a
        # failure (all models down / unexpected error), and the except may itself be triggered
        # by a datastore issue — attempting a DB write there would be futile and noisy. Note the
        # graph nodes fail soft, so these branches are a safety net for infrastructure failures
        # rather than the normal all-models-down path (which yields a fallback answer + done).
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

    async def _stream_response(
        self, merged: AgentState, result: _ResponseResult, session_id: str
    ) -> AsyncIterator[ChatEvent]:
        """Stream the responder's answer, yielding ``token`` events as content arrives.

        Content deltas are yielded immediately (token-by-token SSE); the accumulated content and
        terminal ``finish_reason`` are written to ``result`` (an async generator cannot
        ``return`` them). The Redis-backed cancel flag is polled every ``cancel_check_interval``
        chunks so a long answer stops promptly; on cancel the generator returns early with
        ``result.cancelled = True`` and the partial content captured. The responder stream is
        explicitly closed in ``finally`` so an early return (cancel) does not leak the underlying
        async generator or its upstream HTTP connection.

        Each content delta is run through the minimal output guardrail
        (:func:`app.guardrails.screen_output`, SEC-02 / design §7.3 point 4) before it is
        emitted, stripping any canonical injection phrasing the model echoed back out of
        untrusted grounding material. This is the streaming counterpart to the graph's
        :func:`~app.agents.graph.output_guardrail_node` (which nets the buffered path); both are
        the coarse deterministic placeholder swapped for the full classifier in P10. As a coarse
        per-chunk net it neutralises phrasing contained within a single delta — windowing across
        chunk boundaries is deferred to the P10 classifier.
        """
        parts: list[str] = []
        chunk_count = 0

        stream = self._runner.stream_response(merged)
        try:
            async for chunk in stream:
                if chunk.content:
                    content = screen_output(chunk.content).text
                    parts.append(content)
                    yield TokenEvent(content=content)
                if chunk.finish_reason:
                    result.finish_reason = chunk.finish_reason

                chunk_count += 1
                if chunk_count % self._cancel_check_interval == 0:
                    if await self._cancel.is_requested(session_id):
                        result.cancelled = True
                        result.content = "".join(parts)
                        return
        finally:
            # Deterministic cleanup: closing the async generator on an early cancel return
            # releases the upstream stream/connection promptly (rather than at GC). ``aclose`` is
            # a no-op on an already-exhausted stream. Guarded by getattr since the runner's
            # public type is only ``AsyncIterator``.
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

        result.content = "".join(parts)

    async def _load_prior(
        self,
        session_id: str,
        history: Sequence[ChatMessage] | None,
        user_id: str | None,
    ) -> list[ChatMessage]:
        """Resolve the prior turns that seed this turn's context.

        Precedence: an explicit caller-supplied ``history`` wins; otherwise the Redis working
        memory; and — only for a logged-in user whose Redis memory is empty (fresh Redis / TTL
        expired / app restarted) — the durable Postgres history. This Postgres fallback is what
        makes account chat history survive a restart (design §4). The fallback is best-effort: a
        load failure must not break the turn, so it logs and falls back to an empty context.
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
        # Seed the (empty) Redis working memory with what we just rehydrated so the *next* turn
        # on this session finds the full context in Redis and does not skip this rehydration
        # branch. Without this, only the first post-restart turn would see the pre-restart
        # history: turn 2 would find Redis non-empty (holding just turn 1's new pair) and silently
        # start from a truncated context, losing all pre-restart context.
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
        :class:`~app.services.conversation_store.ConversationStore` is wired — the Redis-only
        guest path (nothing in Postgres). A persistence failure is logged and swallowed: it must
        **never** break the user-visible SSE stream (which has already delivered its terminal
        event by this point).
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
        self, session_id: str, produced: list[ChatMessage], message_id: str
    ) -> CancelledEvent:
        """Clear the flag, persist what was produced, and build the terminal event.

        Persisting ``produced`` (the user message and — on a mid-answer stop — the partial
        assistant answer) keeps the conversation coherent for the next turn. The flag is deleted
        so it cannot leak into a future request on this ``session_id`` (belt-and-braces with its
        TTL).
        """
        await self._cancel.clear(session_id)
        await self._memory.append(session_id, produced)
        logger.info("chat turn cancelled by client (session=%s)", session_id)
        return CancelledEvent(message_id=message_id)


def _to_source_citations(citations: Sequence[Citation]) -> list[SourceCitation]:
    """Map internal graph :class:`~app.agents.state.Citation`s onto the wire DTO.

    Keeps the schema layer independent of the agent layer (the SSE contract never leaks an
    internal model): the service is the single adapter from the graph's accumulated worker
    citations to the ``done`` event's ``citations`` field.
    """
    return [
        SourceCitation(
            source_id=c.source_id,
            title=c.title,
            url=c.url,
            snippet=c.snippet,
            worker=c.worker.value if c.worker is not None else None,
        )
        for c in citations
    ]
