"""Unit tests for the native-tool foundation (P1-03).

Covers: schema shape validity, correct execution on valid input, graceful
error payloads on bad/missing args, and the full registry round trip
(``ToolCall`` → executor → ``role="tool"`` ``ChatMessage``). All ``internet_search``
HTTP is served by an ``httpx.MockTransport`` — no real network in CI. Tavily
provider/failover/promotion/caching are tested separately in ``test_tavily_pool.py``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.llm.types import ChatMessage, FunctionCall, ToolCall
from app.tools import (
    CurrentDateTimeTool,
    InternetSearchTool,
    ToolRegistry,
    ToolResult,
    build_default_registry,
)
from app.tools.tavily_pool import TavilyPool


def _tavily_tool(
    handler: Any | None = None, *, keys: tuple[str, ...] = ("tvly-test",)
) -> InternetSearchTool:
    """Build an ``InternetSearchTool`` over a Tavily pool (mock transport, no redis)."""
    http_client = _mock_search_client(handler) if handler is not None else None
    pool = TavilyPool(list(keys), http_client=http_client)
    return InternetSearchTool(pool=pool)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _tool_call(name: str, arguments: str, call_id: str = "call_1") -> ToolCall:
    return ToolCall(id=call_id, function=FunctionCall(name=name, arguments=arguments))


def _assert_valid_schema(schema: dict[str, Any], expected_name: str) -> None:
    assert schema["type"] == "function"
    function = schema["function"]
    assert function["name"] == expected_name
    assert isinstance(function["description"], str) and function["description"]
    params = function["parameters"]
    assert params["type"] == "object"
    assert isinstance(params["properties"], dict)
    assert isinstance(params["required"], list)


def _mock_search_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- #
# Schema shape
# --------------------------------------------------------------------------- #
def test_current_datetime_schema_shape() -> None:
    _assert_valid_schema(CurrentDateTimeTool().schema, "current_date_and_time")


def test_internet_search_schema_shape() -> None:
    tool = _tavily_tool()
    schema = tool.schema
    _assert_valid_schema(schema, "internet_search")
    assert schema["function"]["parameters"]["required"] == ["query"]


def test_registry_schemas_match_registered_tools() -> None:
    # TAVILY_API_KEY_* default to "" (conftest seeds no value), so the default
    # registry's search tool is inert — safe to build without touching the network.
    registry = build_default_registry()
    names = [s["function"]["name"] for s in registry.schemas()]
    assert names == ["current_date_and_time", "internet_search"]


# --------------------------------------------------------------------------- #
# current_date_and_time execution
# --------------------------------------------------------------------------- #
async def test_current_datetime_default_utc() -> None:
    result = await CurrentDateTimeTool().run({})
    assert not result.is_error
    payload = json.loads(result.content)
    assert payload["timezone"] == "UTC"
    assert set(payload) >= {"iso8601", "date", "time", "weekday", "unix"}


async def test_current_datetime_with_timezone() -> None:
    result = await CurrentDateTimeTool().run({"timezone": "Europe/Sofia"})
    assert not result.is_error
    assert json.loads(result.content)["timezone"] == "Europe/Sofia"


async def test_current_datetime_bad_timezone_is_graceful() -> None:
    result = await CurrentDateTimeTool().run({"timezone": "Mars/Olympus"})
    assert result.is_error
    assert "Unknown timezone" in json.loads(result.content)["error"]


# --------------------------------------------------------------------------- #
# internet_search execution
# --------------------------------------------------------------------------- #
async def test_internet_search_returns_structured_snippets() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Career coaching 101",
                        "url": "https://example.com/a",
                        "content": "How to grow your career.",
                    },
                    {
                        "title": "Resume tips",
                        "url": "https://example.com/b",
                        "content": "Write a strong CV.",
                    },
                ]
            },
        )

    tool = _tavily_tool(handler)
    result = await tool.run({"query": "career coaching", "max_results": 5})

    assert not result.is_error
    payload = json.loads(result.content)
    assert payload["query"] == "career coaching"
    assert len(payload["results"]) == 2
    assert payload["results"][0] == {
        "title": "Career coaching 101",
        "url": "https://example.com/a",
        "snippet": "How to grow your career.",
    }
    assert "tavily" in captured["url"]
    assert captured["body"]["query"] == "career coaching"
    # The secret is carried in the Authorization header, never in the URL.
    assert captured["auth"] == "Bearer tvly-test"
    assert "tvly-test" not in captured["url"]


async def test_internet_search_respects_max_results_cap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        many = [{"title": f"t{i}", "url": f"u{i}", "content": "c"} for i in range(20)]
        return httpx.Response(200, json={"results": many})

    tool = _tavily_tool(handler)
    # max_results=99 must be clamped to MAX_RESULTS_CAP (10).
    result = await tool.run({"query": "x", "max_results": 99})
    assert len(json.loads(result.content)["results"]) == 10


async def test_internet_search_missing_query_is_graceful() -> None:
    tool = _tavily_tool()
    result = await tool.run({})
    assert result.is_error
    assert "query" in json.loads(result.content)["error"]


async def test_internet_search_not_configured_is_graceful() -> None:
    tool = _tavily_tool(keys=())
    result = await tool.run({"query": "anything"})
    assert result.is_error
    assert "not configured" in json.loads(result.content)["error"]


async def test_internet_search_http_error_is_graceful() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    tool = _tavily_tool(handler)
    result = await tool.run({"query": "x"})
    assert result.is_error
    assert "failed" in json.loads(result.content)["error"]


async def test_internet_search_timeout_is_graceful() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    tool = _tavily_tool(handler)
    result = await tool.run({"query": "x"})
    assert result.is_error
    assert "failed" in json.loads(result.content)["error"]


# --------------------------------------------------------------------------- #
# Registry round trip
# --------------------------------------------------------------------------- #
async def test_registry_execute_round_trip() -> None:
    registry = build_default_registry_no_network()
    tool_call = _tool_call("current_date_and_time", '{"timezone": "UTC"}', call_id="abc")

    message = await registry.execute(tool_call)

    assert isinstance(message, ChatMessage)
    assert message.role == "tool"
    assert message.name == "current_date_and_time"
    assert message.tool_call_id == "abc"
    assert message.content is not None
    assert json.loads(message.content)["timezone"] == "UTC"


async def test_registry_execute_unknown_tool_is_graceful() -> None:
    registry = build_default_registry_no_network()
    message = await registry.execute(_tool_call("nope", "{}"))
    assert message.role == "tool"
    assert message.content is not None
    assert "Unknown tool" in json.loads(message.content)["error"]


async def test_registry_execute_bad_json_args_is_graceful() -> None:
    registry = build_default_registry_no_network()
    message = await registry.execute(_tool_call("current_date_and_time", "{not json"))
    assert message.content is not None
    assert "Invalid tool arguments JSON" in json.loads(message.content)["error"]


async def test_registry_execute_non_object_args_is_graceful() -> None:
    registry = build_default_registry_no_network()
    message = await registry.execute(_tool_call("current_date_and_time", "[1, 2, 3]"))
    assert message.content is not None
    assert "must be a JSON object" in json.loads(message.content)["error"]


async def test_registry_execute_empty_args_defaults_to_empty_dict() -> None:
    registry = build_default_registry_no_network()
    message = await registry.execute(_tool_call("current_date_and_time", ""))
    assert message.content is not None
    assert json.loads(message.content)["timezone"] == "UTC"


async def test_registry_execute_catches_tool_exception() -> None:
    class ExplodingTool(CurrentDateTimeTool):
        async def run(self, arguments: Any) -> ToolResult:
            raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(ExplodingTool())
    message = await registry.execute(_tool_call("current_date_and_time", "{}"))
    assert message.content is not None
    assert "failed" in json.loads(message.content)["error"]


def test_registry_rejects_duplicate_registration() -> None:
    registry = ToolRegistry()
    registry.register(CurrentDateTimeTool())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(CurrentDateTimeTool())


# --------------------------------------------------------------------------- #
# Per-tool invocation limit (P10-05, §7.5)
# --------------------------------------------------------------------------- #
class _FakeToolLimiter:
    """A ``ToolInvocationLimiter`` stand-in that allows the first ``allowed`` calls per tool."""

    def __init__(self, *, allowed: int) -> None:
        self._allowed = allowed
        self.calls: list[str] = []

    async def allow(self, tool_name: str) -> bool:
        self.calls.append(tool_name)
        return self.calls.count(tool_name) <= self._allowed


async def test_registry_allows_tool_within_per_tool_limit() -> None:
    limiter = _FakeToolLimiter(allowed=1)
    registry = ToolRegistry(invocation_limiter=limiter)
    registry.register(CurrentDateTimeTool())

    message = await registry.execute(_tool_call("current_date_and_time", "{}"))

    assert message.content is not None
    # Within budget → the real tool ran (no rate-limit error).
    assert json.loads(message.content)["timezone"] == "UTC"
    assert limiter.calls == ["current_date_and_time"]


async def test_registry_denies_tool_over_per_tool_limit_gracefully() -> None:
    limiter = _FakeToolLimiter(allowed=1)
    registry = ToolRegistry(invocation_limiter=limiter)
    registry.register(CurrentDateTimeTool())

    first = await registry.execute(_tool_call("current_date_and_time", "{}"))
    second = await registry.execute(_tool_call("current_date_and_time", "{}"))

    # First runs; the second is over budget → a graceful rate-limit tool message (never raises).
    assert first.content is not None and "timezone" in first.content
    assert second.role == "tool"
    assert second.content is not None
    assert "Rate limit reached for tool" in json.loads(second.content)["error"]


async def test_registry_per_tool_limit_is_per_tool_name() -> None:
    # Each tool name has its own budget: exhausting one must not block another.
    limiter = _FakeToolLimiter(allowed=1)
    registry = ToolRegistry(invocation_limiter=limiter)
    registry.register(CurrentDateTimeTool())
    registry.register(InternetSearchTool(pool=TavilyPool([])))

    await registry.execute(_tool_call("current_date_and_time", "{}"))
    blocked = await registry.execute(_tool_call("current_date_and_time", "{}"))
    # A different tool still has its full budget.
    other = await registry.execute(_tool_call("internet_search", '{"query": "x"}'))

    assert "Rate limit reached" in json.loads(blocked.content or "{}")["error"]
    # internet_search ran (empty pool → its own "not configured" graceful error, not a rate limit).
    assert "not configured" in json.loads(other.content or "{}")["error"]


# --------------------------------------------------------------------------- #
# Local factory: a registry whose search tool has no configured key (empty pool)
# so nothing can reach the network by accident in these tests.
# --------------------------------------------------------------------------- #
def build_default_registry_no_network() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CurrentDateTimeTool())
    registry.register(InternetSearchTool(pool=TavilyPool([])))
    return registry
