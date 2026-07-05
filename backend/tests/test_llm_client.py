"""Unit tests for the HF OpenAI-compatible ``LLMClient``.

All tests run against a **mocked HTTP transport** (``httpx.MockTransport``) injected
into the client — no real HF endpoint is contacted, so CI makes no network calls.
Coverage: plain completion, native tool-call round trip, streaming (content +
tool-call deltas), and timeout translation to the first-party error hierarchy.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.llm import (
    ChatMessage,
    HFOpenAICompatibleClient,
    LLMTimeoutError,
    StreamChunk,
)

BASE_URL = "https://api-inference.huggingface.co/v1"


def _build_client(handler: Callable[[httpx.Request], httpx.Response]) -> HFOpenAICompatibleClient:
    """Client wired to a mock transport that runs ``handler`` for every request."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url=BASE_URL)
    return HFOpenAICompatibleClient(
        model="zai-org/GLM-5.2",
        api_token="test-token",
        base_url=BASE_URL,
        default_timeout=5.0,
        http_client=http_client,
    )


def _completion_body(
    *,
    content: str | None = None,
    tool_calls: list[dict[str, object]] | None = None,
    finish_reason: str = "stop",
) -> dict[str, object]:
    """A minimal OpenAI-compatible ``chat.completion`` response body."""
    message: dict[str, object] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "zai-org/GLM-5.2",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


def _sse(chunks: list[dict[str, object]]) -> bytes:
    """Serialize completion chunks as an OpenAI-style SSE stream (+ ``[DONE]``)."""
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


async def test_plain_completion() -> None:
    """A plain completion returns text content, usage, and no tool calls."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json=_completion_body(content="Hello there"))

    client = _build_client(handler)
    result = await client.complete([ChatMessage(role="user", content="hi")])

    assert result.content == "Hello there"
    assert result.tool_calls == []
    assert result.finish_reason == "stop"
    assert result.model == "zai-org/GLM-5.2"
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 7
    await client.aclose()


async def test_tool_call_round_trip() -> None:
    """Tool schemas go out on the request; native ``tool_calls`` come back parsed.

    No ReAct/regex parsing — the tool call is read straight from the structured
    response, and a follow-up ``tool`` message round-trips through the wire format.
    """
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.update(payload)
        return httpx.Response(
            200,
            json=_completion_body(
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "search_jobs",
                            "arguments": '{"query": "data engineer"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            ),
        )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_jobs",
                "description": "Search job listings",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]

    client = _build_client(handler)
    result = await client.complete(
        [ChatMessage(role="user", content="find data engineer jobs")],
        tools=tools,
        tool_choice="auto",
    )

    # Request carried the tool schema and tool_choice through to the provider.
    assert captured["tools"] == tools
    assert captured["tool_choice"] == "auto"

    # Response tool call parsed into first-party models.
    assert result.content is None
    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "call_1"
    assert call.function.name == "search_jobs"
    assert json.loads(call.function.arguments) == {"query": "data engineer"}

    # A tool-result message round-trips into the OpenAI wire shape.
    tool_msg = ChatMessage(role="tool", content="[]", tool_call_id="call_1", name="search_jobs")
    assert tool_msg.to_openai() == {
        "role": "tool",
        "content": "[]",
        "name": "search_jobs",
        "tool_call_id": "call_1",
    }
    await client.aclose()


async def test_streaming_yields_content_and_tool_deltas() -> None:
    """``stream`` yields incremental content deltas and tool-call deltas in order."""
    chunks = [
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "zai-org/GLM-5.2",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hel"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "zai-org/GLM-5.2",
            "choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": None}],
        },
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "zai-org/GLM-5.2",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "search_jobs", "arguments": '{"q":'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "zai-org/GLM-5.2",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(chunks),
        )

    client = _build_client(handler)
    received: list[StreamChunk] = [
        chunk async for chunk in client.stream([ChatMessage(role="user", content="hi")])
    ]

    text = "".join(c.content for c in received if c.content)
    assert text == "Hello"

    tool_deltas = [d for c in received if c.tool_call_deltas for d in c.tool_call_deltas]
    assert len(tool_deltas) == 1
    assert tool_deltas[0].name == "search_jobs"
    assert tool_deltas[0].arguments == '{"q":'
    assert received[-1].finish_reason == "stop"
    await client.aclose()


async def test_timeout_is_translated() -> None:
    """A transport timeout surfaces as the first-party ``LLMTimeoutError``."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    client = _build_client(handler)
    with pytest.raises(LLMTimeoutError):
        await client.complete([ChatMessage(role="user", content="hi")])
    await client.aclose()
