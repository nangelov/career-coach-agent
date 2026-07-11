"""Request + streamed-event schemas for ``POST /api/chat`` (design §9).

The chat endpoint streams **Server-Sent Events**. The service layer
(:mod:`app.services.chat`) yields the typed :class:`ChatEvent` union defined here
and stays free of any HTTP/SSE concern; the router (:mod:`app.api.chat`) is the
only place that serialises an event to the SSE wire format. Keeping the event
vocabulary in ``schemas/`` means the Next.js frontend (P1-08) has one authoritative
contract to consume.

SSE event vocabulary (the ``event:`` line ↔ the model's ``event`` field):

* ``start``       — the assistant turn began; carries the ``message_id``.
* ``plan``        — the planner's decision for this turn (intent + human-readable steps +
  which workers run), emitted **before** token streaming so the UI can render the
  "thinking"/worker steps (design §3 multi-agent graph; consumed by the paired (F) task
  *"stream planner/worker steps to the UI"*). Additive to the P1 vocabulary — a client that
  does not understand it simply ignores it.
* ``token``       — one incremental content delta (token-by-token streaming).
* ``tool_call``   — a legacy P1 native tool-call event (the model asked to run a tool);
  retained in the union for wire-compatibility but no longer emitted by the graph-driven
  service, whose workers are graph nodes surfaced via ``plan`` instead.
* ``tool_result`` — the paired legacy tool-result event; likewise retained, no longer emitted.
* ``done``        — the turn completed successfully; repeats ``message_id`` +
  ``finish_reason`` and now carries the ``citations`` backing the answer (design §3
  *"synthesize, cite sources"*).
* ``cancelled``   — the turn was stopped by a client ``POST /api/chat/{session}/cancel``
  (the "stop" button, P1-08); terminal, repeats ``message_id`` so any partial answer
  already streamed stays attributable/feedback-ready. Distinct from ``done`` so the UI
  can tell a user-stopped turn from a natural completion.
* ``error``       — a terminal failure (all models down, iteration cap, or an
  unexpected error). The stream ends cleanly after this — never a mid-stream 500.

``message_id`` is the stable, feedback-ready id of the assistant turn (§5.5): one
uuid4 assigned once per turn in :class:`~app.services.chat.ChatService`, identical
across every ``message_id``-bearing event here (``start`` ↔ ``done``/``cancelled``),
and stamped onto the persisted assistant answer (:attr:`app.llm.types.ChatMessage.message_id`)
so it survives a session-memory round trip and can be keyed on by the future feedback
surface (``message_feedback`` table P2, ``POST /api/messages/{message_id}/feedback`` P9).
It is never sent to the LLM provider.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.llm.types import ChatMessage


class ChatRequest(BaseModel):
    """A single user turn.

    The conversation is keyed by ``session_id`` and stored behind the
    :class:`~app.services.session_memory.SessionMemory` seam (Redis-backed). ``history`` is
    an optional escape hatch to seed/replay a conversation without server-side state (useful
    for stateless clients and tests); when omitted the server-side session memory is the
    source of truth.

    **Identity is never taken from the request body (P3-04, §7 AuthZ).** The caller's
    ``user_id`` (and whether the turn is guest vs. logged-in) is derived server-side from the
    verified session JWT (``require_auth`` → :class:`~app.schemas.auth.CurrentUser`), *not*
    from a client-sent field — a client cannot claim to be another user. The router also
    enforces that ``session_id`` matches the caller's own session
    (:func:`~app.security.dependencies.authorize_session_access`), so a caller cannot post
    into someone else's conversation. There is deliberately **no** ``user_id`` field here
    (the P2 interim stand-in was removed once real auth landed).

    ``session_id`` is capped at 64 chars to match the ``sessions.id`` /
    ``conversations.session_id`` ``String(64)`` columns (P2-03): a longer value would fail
    the Postgres insert on a logged-in turn, which — being best-effort — would silently drop
    durable history. Real ids are 36-char ``crypto.randomUUID()`` (P1-08), well within bound.
    """

    session_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=8000)
    history: list[ChatMessage] | None = Field(
        default=None,
        description="Optional client-supplied prior turns; when set, seeds this turn "
        "instead of the server-side session memory.",
    )


# --------------------------------------------------------------------------- #
# Streamed events (the SSE vocabulary)
# --------------------------------------------------------------------------- #
class SourceCitation(BaseModel):
    """One grounding source backing the answer, surfaced on ``done`` (design §3 "cite sources").

    The **wire projection** of an internal :class:`app.agents.state.Citation`: the chat service
    maps the graph's accumulated worker citations onto this DTO, so the schema layer stays
    independent of the agent layer (Router → Service → Agent). All fields are optional — a
    worker emits whatever provenance it has (a KB chunk id, a crawled URL, a job link).
    """

    source_id: str | None = None
    title: str | None = None
    url: str | None = None
    snippet: str | None = None
    #: Which worker contributed this source (``rag`` / ``web_search`` / ``job_search`` /
    #: ``pdp_resume``) — the plain :class:`app.agents.state.WorkerName` value.
    worker: str | None = None


class StartEvent(BaseModel):
    """The assistant turn has begun."""

    event: Literal["start"] = "start"
    message_id: str


class PlanEvent(BaseModel):
    """The planner's routing decision for this turn (design §3 Planner).

    Emitted once, right after ``start`` and before the first ``token``, so the client can show
    the classified intent, the human-readable plan steps, and which workers the turn ran — the
    "visible thinking / worker steps" the design calls for and the paired (F) task renders.
    """

    event: Literal["plan"] = "plan"
    #: The classified :class:`app.agents.state.Intent` value (e.g. ``chat``, ``job_search``).
    intent: str
    #: Ordered, human-readable decomposition of the turn.
    steps: list[str] = Field(default_factory=list)
    #: The worker node names that ran this turn (:class:`app.agents.state.WorkerName` values).
    workers: list[str] = Field(default_factory=list)


class TokenEvent(BaseModel):
    """One incremental content delta of the assistant's answer."""

    event: Literal["token"] = "token"
    content: str


class ToolCallEvent(BaseModel):
    """The model requested a tool call; emitted just before it is executed."""

    event: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: str


class ToolResultEvent(BaseModel):
    """A tool finished executing; carries its (JSON string) output."""

    event: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    name: str
    content: str


class DoneEvent(BaseModel):
    """The assistant turn completed successfully.

    Carries the ``citations`` that back the streamed answer (design §3 Response Agent
    *"synthesize, cite sources"*) — folded into the terminal event rather than a separate
    frame since sources are only complete once the answer is. Empty when the turn ran no
    grounding worker (a plain chat / smalltalk answer).
    """

    event: Literal["done"] = "done"
    message_id: str
    finish_reason: str | None = None
    citations: list[SourceCitation] = Field(default_factory=list)


class CancelledEvent(BaseModel):
    """The turn was stopped via the cancel endpoint; terminal, ends the stream.

    Emitted when an in-flight turn observes the Redis-backed cancel signal set by
    ``POST /api/chat/{session}/cancel`` (P1-06). Carries the same ``message_id`` as
    ``start`` so any partial answer already streamed remains attributable (and
    feedback-ready per §5.5 / P1-07). The stream ends cleanly after this event.
    """

    event: Literal["cancelled"] = "cancelled"
    message_id: str


class ErrorEvent(BaseModel):
    """A terminal failure; the stream ends cleanly after this event."""

    event: Literal["error"] = "error"
    message: str


#: Every event the chat service can yield. The ``event`` literal is the SSE
#: ``event:`` name and the discriminator for the frontend.
ChatEvent = (
    StartEvent
    | PlanEvent
    | TokenEvent
    | ToolCallEvent
    | ToolResultEvent
    | DoneEvent
    | CancelledEvent
    | ErrorEvent
)
