"""Shared test doubles for the chat tool-call loop (single source of truth).

The chat-service unit/integration suites all drive :class:`~app.services.chat.ChatService`
with the same two fakes — a scripted LLM router and a canned tool registry. They used to be
re-declared near-verbatim in five modules (with subtle drift). They live here now so the
scripted-router / canned-registry contract has one home; import them from ``tests.fakes``.

Both intentionally satisfy their real counterparts *structurally* (duck typing) rather than
by subclassing, so callers pass them where an ``LLMRouter`` / ``ToolRegistry`` is expected
(with a ``cast`` or ``# type: ignore[arg-type]`` at the seam, as the suites already do).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.llm.types import ChatMessage, StreamChunk, ToolCall

#: A scripted stream: a list of ``StreamChunk``s to yield, or an ``Exception`` to raise
#: when the stream is opened (models an all-models-failed / transport error).
Script = list[StreamChunk] | Exception


class FakeRouter:
    """A scripted :class:`~app.llm.router.LLMRouter` stand-in.

    Each :meth:`stream` call consumes the next scripted response and records the messages
    it was handed (in :attr:`calls`), so tests can assert what the model saw. Set
    ``always`` to replay a single script indefinitely (for the iteration-cap test).
    """

    def __init__(
        self, scripts: Sequence[Script] | None = None, *, always: Script | None = None
    ) -> None:
        self._scripts = list(scripts or [])
        self._always = always
        self.calls: list[list[ChatMessage]] = []

    async def stream(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[StreamChunk]:
        self.calls.append(list(messages))
        script = self._always if self._always is not None else self._scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        for chunk in script:
            yield chunk

    async def aclose(self) -> None:
        pass


class FakeRegistry:
    """A minimal tool registry: one canned tool result per executed call.

    Records the calls it executed in :attr:`executed` so tests can assert the reassembled
    tool call reached the registry with merged arguments.
    """

    def __init__(self, result: str = '{"ok": true}') -> None:
        self._result = result
        self.executed: list[ToolCall] = []

    def schemas(self) -> list[dict[str, Any]]:
        return []

    async def execute(self, tool_call: ToolCall) -> ChatMessage:
        self.executed.append(tool_call)
        return ChatMessage(
            role="tool",
            content=self._result,
            name=tool_call.function.name,
            tool_call_id=tool_call.id,
        )
