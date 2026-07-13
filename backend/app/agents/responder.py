"""Response Agent — synthesize the workers' outputs into one cited answer (design §3).

This replaces the P4-02 ``responder_node`` **stub** with the real Response Agent design §3
prescribes (*"merges worker outputs into one coherent, cited answer; owns tone/formatting
(adapted to the user's learned communication style); streams tokens"*). It is the fan-in of
the graph: every dispatched worker converges here, and this node turns the merged
:attr:`~app.agents.state.AgentState.worker_results` / accumulated
:attr:`~app.agents.state.AgentState.citations` into the assistant's answer.

**What it does.**

1. Build a synthesis prompt from the conversational persona, the recalled memory / plan,
   the recent history slice, the current turn, and — crucially — the *grounding material*
   the workers retrieved, clearly delineated as untrusted reference data (see below).
2. Call the injected :class:`LLMResponder` (the P1-02 :class:`~app.llm.router.LLMRouter`) to
   compose the answer — buffered (:meth:`Responder.synthesize` / :meth:`Responder.__call__`,
   used by the in-graph node) or token-streamed (:meth:`Responder.stream`, used by the
   graph's streaming entrypoint :func:`~app.agents.graph.stream_graph`).
3. Set :attr:`AgentState.response` + :attr:`AgentState.finish_reason` and reuse the existing
   :attr:`AgentState.message_id` (design §5.5 feedback id), minting one only if still unset.
   The node **does not** re-write ``citations`` — they already accumulated via the P4-01
   reducer and pass through unchanged (writing them again would double them under the
   list-concatenating reducer).

**Untrusted grounding material (design §7 / §10 — this is the boundary that matters).** The
web searcher (P4-05) crawls arbitrary pages and the RAG worker (P4-04) retrieves stored
chunks; that text is **untrusted external data**. This responder is exactly where that
content re-enters an LLM prompt, so it is fenced into a clearly-labelled REFERENCE MATERIAL
block with an explicit instruction that it is data to cite, **not** instructions to follow —
so a crawled page cannot hijack the synthesis call. The full injection/PII classifier is
P10; this task's job is only to *not create* an obvious injection vector here.

**No-worker turns.** When the planner routed no workers (smalltalk / direct chat), the
grounding block is simply empty and the model answers from the persona + history + turn — a
real generated answer, never a canned string.

**Fail-soft (a synthesis failure must not 500 the turn).** If the router raises (all models
down / timeout) the responder degrades to an honest fallback message with a ``"error"``
finish reason rather than propagating the exception out of the node — mirroring the
planner's (P4-03) and workers' (P4-04/05) safe-default posture.

**Dependency injection (mirrors P4-03).** :class:`Responder` takes an :class:`LLMResponder`
(structurally the :class:`~app.llm.router.LLMRouter`) by constructor injection — never a raw
client or the provider SDK. ``build_graph(responder_router=...)`` wires it as the RESPONDER
node; when no router is supplied the graph falls back to the dependency-free deterministic
:func:`~app.agents.graph.responder_node`, so the import-time module graph still compiles.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any, Protocol, runtime_checkable

from app.agents.state import AgentState, Citation, Intent, WorkerResult
from app.guardrails import fence_untrusted
from app.llm.errors import LLMError
from app.llm.types import ChatMessage, CompletionResult, StreamChunk, ToolSchema

logger = logging.getLogger(__name__)

__all__ = [
    "FALLBACK_RESPONSE",
    "JOB_HUNTING_REDIRECT_NOTE",
    "RESPONDER_SYSTEM_PROMPT",
    "LLMResponder",
    "Responder",
]


@runtime_checkable
class LLMResponder(Protocol):
    """The LLM surface the responder needs: buffered **and** streamed completion.

    A structural :class:`~typing.Protocol` (not a hard import of
    :class:`~app.llm.router.LLMRouter`) so the responder depends on a *capability*, not a
    concrete class — the real failover router satisfies this shape and unit tests inject a
    fake without touching HF. Mirrors :meth:`LLMRouter.complete` / :meth:`LLMRouter.stream`
    (the responder never calls tools — the workers already ran — so ``tools`` / ``tool_choice``
    are present only to match the surface, unused here).
    """

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = ...,
        tool_choice: str | dict[str, Any] | None = ...,
        temperature: float | None = ...,
        max_tokens: int | None = ...,
    ) -> CompletionResult: ...

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = ...,
        tool_choice: str | dict[str, Any] | None = ...,
        temperature: float | None = ...,
        max_tokens: int | None = ...,
    ) -> AsyncIterator[StreamChunk]: ...


#: The conversational persona + synthesis brief. This is the Response Agent's system turn
#: (distinct from the planner's classifier brief). Kept close to the P1 walking-skeleton
#: persona so tone is consistent, with the extra "ground + cite" instruction P4 adds.
RESPONDER_SYSTEM_PROMPT = (
    "You are a helpful, encouraging career coach. Give practical, actionable career "
    "guidance in a clear, friendly tone.\n"
    "When REFERENCE MATERIAL is provided below, base your answer on it and cite the "
    "sources you use with their bracketed markers (e.g. [1], [2]). If the reference "
    "material does not cover the question, answer from your own knowledge and say so "
    "rather than inventing sources. Do not fabricate citations."
)

#: Honest degradation shown to the user when synthesis fails (all models down / timeout).
#: A real, apologetic sentence — never a leaked stack trace or a silent empty answer.
FALLBACK_RESPONSE = (
    "I'm sorry — I'm having trouble generating a response right now. Please try again in a moment."
)

#: Framing note appended for a ``job_hunting`` turn (design §7.4 redirect ≠ refusal). The
#: assistant is **not** a job board (§1.1 / §5.6): a "find me openings" request is redirected
#: to the market-requirements answer the MARKET_INTEL worker already produced, steering the
#: user back to development — never a browsable-listings search (there is no such tool).
JOB_HUNTING_REDIRECT_NOTE = (
    "The user asked to find or apply to job openings, but you are a career coach, not a job "
    "board — you cannot search or list vacancies. Do not pretend to. Instead, redirect: use "
    "the reference material to tell them what the market requires for that kind of role "
    "(skills, background, the gap to close), and steer them toward developing those. Be warm "
    "and helpful about the pivot; do not refuse."
)

#: How many trailing history messages to hand the responder (bounded context window).
_HISTORY_CONTEXT_MESSAGES = 8


class Responder:
    """LLM-backed Response Agent node: merge worker outputs into one cited answer (design §3).

    A :class:`Responder` instance is a LangGraph node — it is ``async``-callable with the
    :class:`~app.agents.state.AgentState` and returns the responder's partial update. Construct
    it with an :class:`LLMResponder` (the P1-02 :class:`~app.llm.router.LLMRouter`) and hand it
    to ``build_graph(responder_router=...)``; the streaming entrypoint
    (:func:`~app.agents.graph.stream_graph`) drives :meth:`stream` directly.
    """

    def __init__(
        self,
        router: LLMResponder,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = 1024,
    ) -> None:
        """Bind the responder to an LLM surface.

        Args:
            router: The LLM surface to synthesize with — normally the failover
                :class:`~app.llm.router.LLMRouter`. Injected (not constructed) so pointing the
                responder at a different model tier later is a wiring change (design §6.6).
            temperature: Sampling temperature; a little warmth for prose, still grounded.
            max_tokens: Generation cap for the composed answer.
        """
        self._router = router
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        """Run the responder as a (buffered) graph node → the responder's partial update.

        Returns ``response`` + ``finish_reason`` + ``message_id`` only; ``citations`` are left
        untouched so the accumulated worker citations pass through unchanged (re-writing them
        would duplicate under the list-concatenating P4-01 reducer).
        """
        text, finish_reason = await self.synthesize(state)
        return {
            "response": text,
            "finish_reason": finish_reason,
            "message_id": state.message_id or uuid.uuid4().hex,
        }

    async def synthesize(self, state: AgentState) -> tuple[str, str]:
        """Compose the final answer (buffered), returning ``(text, finish_reason)``.

        Fails soft: any :class:`~app.llm.errors.LLMError` (or an empty completion) yields
        :data:`FALLBACK_RESPONSE` with an ``"error"`` finish reason — the node never raises.
        """
        messages = self._build_messages(state)
        try:
            result = await self._router.complete(
                messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except LLMError:
            logger.warning("responder synthesis failed; using fallback", exc_info=True)
            return FALLBACK_RESPONSE, "error"

        text = (result.content or "").strip()
        if not text:
            logger.warning("responder synthesis returned empty content; using fallback")
            return FALLBACK_RESPONSE, "error"
        return text, result.finish_reason or "stop"

    async def stream(self, state: AgentState) -> AsyncIterator[StreamChunk]:
        """Stream the composed answer as token deltas (design §3 "streams tokens").

        Yields the router's :class:`~app.llm.types.StreamChunk` deltas as they arrive. Fails
        soft: if the router raises before any token, a single fallback chunk (content +
        ``finish_reason="error"``) is yielded; if it raises mid-stream (after the router's own
        failover/resume is exhausted) the partial text already streamed stands and a terminal
        ``finish_reason="error"`` chunk closes it. Never raises out to the caller.
        """
        messages = self._build_messages(state)
        emitted_content = False
        # Manage the stream by hand + close best-effort in ``finally``: the router's
        # ``stream`` is typed ``AsyncIterator[StreamChunk]`` (no ``aclose`` in that type), so
        # ``contextlib.aclosing`` would not type-check — see the aclosing/AsyncIterator note.
        stream = self._router.stream(
            messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        try:
            async for chunk in stream:
                if chunk.content:
                    emitted_content = True
                yield chunk
        except LLMError:
            logger.warning("responder stream failed; degrading", exc_info=True)
            yield StreamChunk(
                content=None if emitted_content else FALLBACK_RESPONSE,
                finish_reason="error",
            )
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

    def _build_messages(self, state: AgentState) -> list[ChatMessage]:
        """Assemble the synthesis prompt: persona → grounding → history → current turn."""
        messages: list[ChatMessage] = [ChatMessage(role="system", content=RESPONDER_SYSTEM_PROMPT)]
        if state.plan is not None and state.plan.intent is Intent.JOB_HUNTING:
            messages.append(ChatMessage(role="system", content=JOB_HUNTING_REDIRECT_NOTE))
        grounding = _grounding_block(state)
        if grounding:
            messages.append(ChatMessage(role="system", content=grounding))
        if state.history:
            messages.extend(state.history[-_HISTORY_CONTEXT_MESSAGES:])
        messages.append(ChatMessage(role="user", content=state.user_message))
        return messages


def _grounding_block(state: AgentState) -> str | None:
    """Render the workers' output + citations into one fenced, untrusted REFERENCE block.

    Returns ``None`` when no worker produced usable content (the no-worker / smalltalk case),
    so the responder simply answers from persona + history. The block is explicitly labelled as
    *data to cite, not instructions to follow* (design §7/§10): the crawled/retrieved text is
    fenced between BEGIN/END markers and prefaced with an ignore-embedded-instructions warning,
    so worker content — above all crawled web pages — cannot hijack the synthesis call.
    """
    worker_texts = _worker_texts(state.worker_results.values())
    citation_lines = _citation_lines(state.citations)
    if not worker_texts and not citation_lines:
        return None

    return fence_untrusted(
        "REFERENCE MATERIAL",
        worker_texts,
        origin="was gathered by retrieval tools (knowledge base, web search, market requirements)",
        sources=citation_lines,
    )


def _worker_texts(results: Iterable[WorkerResult]) -> list[str]:
    """The non-empty ``content`` of each worker result, each labelled by its worker name."""
    texts: list[str] = []
    for result in results:
        content = (result.content or "").strip()
        if content:
            texts.append(f"[{result.worker.value}]\n{content}")
    return texts


def _citation_lines(citations: Sequence[Citation]) -> list[str]:
    """Number the accumulated citations into ``[n] title — url`` lines for the prompt.

    Mirrors the ``[n]`` markers the workers already use inside their bundled content, so the
    model can attribute a source it draws on. A citation with neither title nor url is skipped
    (nothing to show), matching the "correctness of *which* sources over exact rendering" note.
    """
    lines: list[str] = []
    for citation in citations:
        label = citation.title or citation.url
        if not label:
            continue
        line = f"[{len(lines) + 1}] {label}"
        if citation.url and citation.title:
            line = f"{line} — {citation.url}"
        lines.append(line)
    return lines
