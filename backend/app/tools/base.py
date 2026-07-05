"""Native tool-calling foundation: the `Tool` abstraction + a `ToolRegistry`.

This module defines the **canonical native-tool pattern** the rest of the app
follows (design §8 ``backend/app/tools/``). Each concrete tool exports two things:

* a **JSON-schema definition** (:attr:`Tool.schema`) in the OpenAI ``tools[]`` shape
  ``{"type": "function", "function": {"name", "description", "parameters"}}`` — the
  exact dict the P1-01 :class:`~app.llm.client.LLMClient` / P1-02
  ``LLMRouter`` pass straight through to the HF OpenAI-compatible endpoint; and
* an **async executor** (:meth:`Tool.run`) that takes the model's parsed arguments
  and returns a structured :class:`ToolResult`.

The :class:`ToolRegistry` is the single wiring point: register a tool once, and the
registry can (a) hand the collected schemas to the LLM layer and (b) dispatch a
model-emitted :class:`~app.llm.types.ToolCall` to the right executor, returning a
``role="tool"`` :class:`~app.llm.types.ChatMessage` ready to append to the
conversation. Adding tool #3 later (P4+) is "drop a module in ``tools/``, register
it" — no scattered wiring.

Tool results are treated as **untrusted external data**: executors return plain,
structured JSON strings (never instructions a downstream prompt would execute).
Full guardrails land in P10; this module only avoids doing anything unsafe now.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel

from app.llm.types import ChatMessage, ToolCall, ToolSchema

# ``ToolSchema`` (``dict[str, Any]``) is defined once in the SDK-free ``app.llm.types`` and
# re-exported here so tool modules can keep importing it from ``app.tools.base`` without
# pulling in the ``openai`` SDK that lives in ``app.llm.client``.
__all__ = ["Tool", "ToolRegistry", "ToolResult", "ToolSchema"]


class ToolResult(BaseModel):
    """The structured outcome of executing a tool.

    ``content`` is always a JSON string so it can be placed verbatim into a
    ``role="tool"`` :class:`~app.llm.types.ChatMessage`. ``is_error`` marks a
    graceful failure (bad args, upstream error) — the model still receives a
    well-formed tool message rather than the loop raising.
    """

    content: str
    is_error: bool = False

    @classmethod
    def ok(cls, payload: Any) -> ToolResult:
        """Build a success result from a JSON-serializable ``payload``."""
        return cls(content=json.dumps(payload, ensure_ascii=False), is_error=False)

    @classmethod
    def error(cls, message: str) -> ToolResult:
        """Build a graceful error result (returned to the model, never raised)."""
        return cls(content=json.dumps({"error": message}, ensure_ascii=False), is_error=True)

    def to_message(self, *, tool_call_id: str, name: str) -> ChatMessage:
        """Render this result as a ``role="tool"`` message answering ``tool_call_id``."""
        return ChatMessage(
            role="tool",
            content=self.content,
            name=name,
            tool_call_id=tool_call_id,
        )


class Tool(ABC):
    """Interface every native tool implements.

    A tool is a self-contained unit: it advertises its JSON schema and executes
    against parsed arguments. Concrete tools own their own config/clients (e.g. an
    injected ``httpx`` client) so the registry can dispatch them uniformly.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The function name the model calls (must match ``schema.function.name``)."""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """The OpenAI-compatible ``tools[]`` JSON-schema definition for this tool."""

    @abstractmethod
    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        """Execute the tool against already-parsed ``arguments``.

        Implementations MUST validate their own inputs and return a
        :meth:`ToolResult.error` on bad/missing args rather than raising — a tool
        must never crash the model-driven call loop.
        """


class ToolRegistry:
    """Holds the app's tools and dispatches model tool-calls to them.

    Registration order is preserved, so :meth:`schemas` returns a stable list to
    hand the LLM layer.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add ``tool`` to the registry (raises on a duplicate name)."""
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Return the registered tool named ``name``, or ``None``."""
        return self._tools.get(name)

    def names(self) -> list[str]:
        """The registered tool names, in registration order."""
        return list(self._tools)

    def schemas(self) -> list[ToolSchema]:
        """All tool schemas, ready to pass to ``LLMClient.complete(tools=...)``."""
        return [tool.schema for tool in self._tools.values()]

    async def execute(self, tool_call: ToolCall) -> ChatMessage:
        """Run the tool a model requested and return its ``role="tool"`` reply.

        The full round trip is: model emits ``tool_call`` → this parses the raw
        JSON arguments, dispatches to the executor, and wraps the outcome as a
        tool message tagged with ``tool_call.id``. Every failure mode — unknown
        tool, malformed argument JSON, or an exception inside the executor — is
        turned into a graceful error tool message, never propagated to the caller.
        """
        name = tool_call.function.name
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.error(f"Unknown tool: {name!r}.").to_message(
                tool_call_id=tool_call.id, name=name
            )

        try:
            arguments = _parse_arguments(tool_call.function.arguments)
        except ValueError as exc:
            return ToolResult.error(str(exc)).to_message(tool_call_id=tool_call.id, name=name)

        try:
            result = await tool.run(arguments)
        except Exception as exc:  # noqa: BLE001 - a tool must never crash the call loop
            result = ToolResult.error(f"Tool {name!r} failed: {exc}")
        return result.to_message(tool_call_id=tool_call.id, name=name)


def _parse_arguments(raw: str) -> dict[str, Any]:
    """Parse a model's raw ``function.arguments`` JSON string into a dict.

    An empty/blank string means "no arguments" → ``{}``. Anything that is not a
    JSON object raises :class:`ValueError`, which the registry turns into a
    graceful error tool message.
    """
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid tool arguments JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return cast("dict[str, Any]", parsed)
