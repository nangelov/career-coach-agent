"""Provider-agnostic LLM message and result types.

These models are the vocabulary the rest of the app (agents, router, services)
speaks — deliberately decoupled from any concrete provider SDK (``openai``,
``huggingface_hub``, …).  ``client.py`` translates between these models and the
OpenAI-compatible wire format; nothing outside ``llm/`` imports the provider SDK.

Native tool-calling is first-class here (``tool_calls`` / ``ToolCallDelta``) — the
v1 ReAct text-parsing path is intentionally gone (design §6, §6.6).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

#: Chat roles supported by the OpenAI-compatible chat-completions surface.
Role = Literal["system", "user", "assistant", "tool"]

#: A native tool definition in JSON-schema form (the OpenAI ``tools[]`` shape:
#: ``{"type": "function", "function": {"name", "description", "parameters"}}``). Defined
#: here — in the SDK-free vocabulary module — so both the LLM client (which passes it to
#: the provider) and ``app/tools/`` (which produces it) share **one** authoritative alias
#: without ``tools/`` having to import the ``openai`` SDK that lives in ``client.py``.
ToolSchema = dict[str, Any]


class FunctionCall(BaseModel):
    """The function a model asked to call: name + raw JSON-string arguments.

    ``arguments`` is kept as the provider's raw JSON *string* (not parsed) so the
    caller decides how/when to ``json.loads`` it — the client never guesses at a
    schema here.
    """

    name: str
    arguments: str = ""


class ToolCall(BaseModel):
    """A complete tool call emitted by the model (native function-calling)."""

    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class ChatMessage(BaseModel):
    """One message in a chat exchange, in either direction.

    Mirrors the OpenAI chat message shape closely enough to round-trip, but stays
    a first-party model so callers never depend on the provider SDK's types.
    """

    role: Role
    content: str | None = None
    #: Optional author name (e.g. the tool name on a ``role="tool"`` message).
    name: str | None = None
    #: Present on assistant messages that requested tool calls.
    tool_calls: list[ToolCall] | None = None
    #: Present on ``role="tool"`` messages — the id of the call being answered.
    tool_call_id: str | None = None
    #: The stable, feedback-ready id of the assistant turn this message belongs to
    #: (design §5.5: "each assistant message carries a stable ``message_id``"). Set by
    #: :class:`~app.services.chat.ChatService` on the user-facing assistant answer so it
    #: survives a round trip through session memory and can be keyed on later by the
    #: ``message_feedback`` table (P2) / ``POST /api/messages/{message_id}/feedback``
    #: (P9). Deliberately **excluded from** :meth:`to_openai` — it is an internal id and
    #: must never leak into the provider payload.
    message_id: str | None = None

    def to_openai(self) -> dict[str, Any]:
        """Render to the OpenAI-compatible ``messages[]`` wire dict.

        Only non-``None`` fields are emitted so the payload matches what the
        provider expects for each role (e.g. a ``tool`` reply carries
        ``tool_call_id``; an assistant tool request carries ``tool_calls``).

        Note: the internal :attr:`message_id` is intentionally **not** emitted here —
        it is a feedback id (§5.5), not part of the provider wire vocabulary.
        """
        payload: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            payload["content"] = self.content
        if self.name is not None:
            payload["name"] = self.name
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": call.type,
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        return payload


class CompletionResult(BaseModel):
    """The full (non-streamed) result of a chat completion."""

    #: Assistant text, or ``None`` when the model only returned tool calls.
    content: str | None = None
    #: Native tool calls the model requested (empty list when none).
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    #: The model id the provider reports it actually served.
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ToolCallDelta(BaseModel):
    """An incremental fragment of a tool call during streaming.

    Providers stream tool calls piecewise: the first delta for a given ``index``
    usually carries the ``id`` and function ``name``; later deltas append
    ``arguments`` fragments.  Consumers accumulate by ``index``.
    """

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


class StreamChunk(BaseModel):
    """One streamed increment: a content delta and/or tool-call deltas."""

    content: str | None = None
    tool_call_deltas: list[ToolCallDelta] | None = None
    finish_reason: str | None = None
