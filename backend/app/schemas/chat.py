"""Request + streamed-event schemas for ``POST /api/chat`` (design §9).

The chat endpoint streams **Server-Sent Events**. The service layer
(:mod:`app.services.chat`) yields the typed :class:`ChatEvent` union defined here
and stays free of any HTTP/SSE concern; the router (:mod:`app.api.chat`) is the
only place that serialises an event to the SSE wire format. Keeping the event
vocabulary in ``schemas/`` means the Next.js frontend (P1-08) has one authoritative
contract to consume.

SSE event vocabulary (the ``event:`` line ↔ the model's ``event`` field):

* ``start``       — the assistant turn began; carries the ``message_id``.
* ``token``       — one incremental content delta (token-by-token streaming).
* ``tool_call``   — the model asked to run a tool; emitted just before execution.
* ``tool_result`` — a tool finished; carries its output for UI visibility.
* ``done``        — the turn completed successfully; repeats ``message_id`` +
  ``finish_reason``.
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

    Interim shape (P1-04): the conversation is keyed by ``session_id`` and stored
    behind the :class:`~app.services.session_memory.SessionMemory` seam (an
    in-memory implementation for now). P1-05 swaps in a Redis-backed store behind
    the **same** interface without changing this public contract. ``history`` is an
    optional escape hatch to seed/replay a conversation without server-side state
    (useful for stateless clients and tests); when omitted the server-side session
    memory is the source of truth.

    ``user_id`` is an **interim** field (P2-07), following the same seam pattern as
    the fields above. Real SSO/JWT auth is P3 — there is no verified identity in the
    request path yet — so this is an explicit, documented stand-in for the
    JWT-derived identity P3 will provide (concretely, the authenticated ``users.id``).
    When ``None`` the turn is a **guest** turn: Redis-only working memory, **nothing**
    persisted to Postgres (design §4: "Guests get NO persisted history") — byte-for-byte
    the P1 behavior. When set, the turn is treated as logged-in and is *also* durably
    persisted (:class:`~app.services.conversation_store.ConversationStore`) so account
    history survives a restart. P3 will populate it from the verified session JWT rather
    than trusting a client-sent value; until then it is not an authorization boundary.

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
    user_id: str | None = Field(
        default=None,
        max_length=64,
        description="Interim (P2-07) stand-in for the P3 JWT-derived user id. None → "
        "guest (Redis-only, no Postgres history); set → logged-in (also persisted to "
        "Postgres). Populated from the verified session JWT once P3 lands.",
    )


# --------------------------------------------------------------------------- #
# Streamed events (the SSE vocabulary)
# --------------------------------------------------------------------------- #
class StartEvent(BaseModel):
    """The assistant turn has begun."""

    event: Literal["start"] = "start"
    message_id: str


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
    """The assistant turn completed successfully."""

    event: Literal["done"] = "done"
    message_id: str
    finish_reason: str | None = None


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
    | TokenEvent
    | ToolCallEvent
    | ToolResultEvent
    | DoneEvent
    | CancelledEvent
    | ErrorEvent
)
