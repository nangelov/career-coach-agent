"""Unit tests for the multi-LLM failover router (design §6.6).

All tests run against **fake** ``LLMClient`` doubles and a tiny in-memory fake
Redis — no network, no real Redis, no ML stack. Coverage mirrors the acceptance
criteria: primary succeeds; primary times out → secondary serves; primary 429 →
backoff-retry then failover; circuit-breaker skips a model marked unhealthy in
Redis; and mid-stream failure on the primary → the secondary resumes so the
caller sees one continuous stream.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from app.llm import (
    ChatMessage,
    CircuitBreaker,
    CompletionResult,
    LLMAllModelsFailedError,
    LLMClient,
    LLMRateLimitError,
    LLMResponseError,
    LLMRouter,
    LLMTimeoutError,
    StreamChunk,
    ToolSchema,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeRedis:
    """In-memory async stand-in for the subset of Redis the breaker uses.

    TTLs are ignored (tests do not exercise real-time expiry — cooldown is
    verified structurally via ``is_open``); values are stored verbatim.
    """

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get(self, name: str) -> Any:
        return self.store.get(name)

    async def set(self, name: str, value: Any, *, ex: int | None = None) -> Any:
        self.store[name] = value
        return True

    async def incr(self, name: str) -> int:
        value = int(self.store.get(name, 0)) + 1
        self.store[name] = value
        return value

    async def expire(self, name: str, time: int) -> Any:
        return True

    async def delete(self, *names: str) -> Any:
        for name in names:
            self.store.pop(name, None)
        return len(names)


class FakeLLMClient(LLMClient):
    """Programmable ``LLMClient`` double.

    * ``complete_result`` — returned by :meth:`complete` when no error is set.
    * ``complete_error`` — raised on every :meth:`complete` call when set.
    * ``stream_script`` — an ordered list of either a :class:`StreamChunk` to yield
      or an :class:`Exception` to raise (mid-stream failure).
    Records call counts and the last ``messages`` it received.
    """

    def __init__(
        self,
        model: str,
        *,
        complete_result: CompletionResult | None = None,
        complete_error: Exception | None = None,
        stream_script: Sequence[StreamChunk | Exception] | None = None,
    ) -> None:
        self._model = model
        self._complete_result = complete_result
        self._complete_error = complete_error
        self._stream_script = list(stream_script or [])
        self.complete_calls = 0
        self.stream_calls = 0
        self.last_messages: list[ChatMessage] = []

    @property
    def model(self) -> str:
        return self._model

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> CompletionResult:
        self.complete_calls += 1
        self.last_messages = list(messages)
        if self._complete_error is not None:
            raise self._complete_error
        assert self._complete_result is not None, "FakeLLMClient has no complete_result"
        return self._complete_result

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        self.stream_calls += 1
        self.last_messages = list(messages)
        for item in self._stream_script:
            if isinstance(item, Exception):
                raise item
            yield item


async def _no_sleep(_: float) -> None:
    """Backoff sleep replaced with a no-op so tests do not actually wait."""


def _result(model: str, content: str) -> CompletionResult:
    return CompletionResult(content=content, model=model, finish_reason="stop")


def _breaker(redis: FakeRedis, *, fail_threshold: int = 3) -> CircuitBreaker:
    return CircuitBreaker(redis, fail_threshold=fail_threshold, cooldown_seconds=30)


def _router(clients: Sequence[LLMClient], breaker: CircuitBreaker, **kwargs: Any) -> LLMRouter:
    kwargs.setdefault("sleep", _no_sleep)
    kwargs.setdefault("first_token_timeout", None)
    return LLMRouter(clients, breaker, **kwargs)


MESSAGES = [ChatMessage(role="user", content="hi")]


# --------------------------------------------------------------------------- #
# complete()
# --------------------------------------------------------------------------- #
async def test_primary_succeeds() -> None:
    """When the primary succeeds, the secondary is never touched."""
    redis = FakeRedis()
    primary = FakeLLMClient("primary", complete_result=_result("primary", "ok"))
    secondary = FakeLLMClient("secondary", complete_result=_result("secondary", "no"))
    router = _router([primary, secondary], _breaker(redis))

    result = await router.complete(MESSAGES)

    assert result.content == "ok"
    assert result.model == "primary"
    assert primary.complete_calls == 1
    assert secondary.complete_calls == 0


async def test_primary_timeout_fails_over_to_secondary() -> None:
    """A primary timeout fails over to the secondary and records the failure."""
    redis = FakeRedis()
    primary = FakeLLMClient("primary", complete_error=LLMTimeoutError("slow"))
    secondary = FakeLLMClient("secondary", complete_result=_result("secondary", "served"))
    breaker = _breaker(redis)
    router = _router([primary, secondary], breaker)

    result = await router.complete(MESSAGES)

    assert result.content == "served"
    assert result.model == "secondary"
    assert primary.complete_calls == 1
    assert secondary.complete_calls == 1
    # Failure was recorded against the primary (counter incremented once).
    assert redis.store.get("llm:cb:primary:fails") == 1


async def test_primary_429_retries_then_fails_over() -> None:
    """A 429 is retried on the same model (backoff) before failing over."""
    redis = FakeRedis()
    primary = FakeLLMClient("primary", complete_error=LLMRateLimitError("rate limited"))
    secondary = FakeLLMClient("secondary", complete_result=_result("secondary", "served"))
    router = _router([primary, secondary], _breaker(redis), max_retries=2)

    result = await router.complete(MESSAGES)

    # 1 initial + 2 retries on the primary, then a single secondary attempt.
    assert primary.complete_calls == 3
    assert secondary.complete_calls == 1
    assert result.model == "secondary"


async def test_circuit_breaker_skips_unhealthy_model() -> None:
    """A model whose circuit is open in Redis is skipped entirely."""
    redis = FakeRedis()
    breaker = _breaker(redis)
    # Mark the primary unhealthy directly in the shared store.
    await redis.set("llm:cb:primary:open", "1")

    primary = FakeLLMClient("primary", complete_result=_result("primary", "should-not-run"))
    secondary = FakeLLMClient("secondary", complete_result=_result("secondary", "served"))
    router = _router([primary, secondary], breaker)

    result = await router.complete(MESSAGES)

    assert result.model == "secondary"
    assert primary.complete_calls == 0  # skipped without a call
    assert secondary.complete_calls == 1


async def test_all_circuits_open_raises() -> None:
    """When every model's circuit is open, the router fails with a clear error."""
    redis = FakeRedis()
    await redis.set("llm:cb:primary:open", "1")
    await redis.set("llm:cb:secondary:open", "1")
    primary = FakeLLMClient("primary", complete_result=_result("primary", "x"))
    secondary = FakeLLMClient("secondary", complete_result=_result("secondary", "y"))
    router = _router([primary, secondary], _breaker(redis))

    with pytest.raises(LLMAllModelsFailedError):
        await router.complete(MESSAGES)
    assert primary.complete_calls == 0
    assert secondary.complete_calls == 0


async def test_client_4xx_is_not_failed_over() -> None:
    """A client 4xx (non-429) would fail on every model — re-raised, no failover."""
    redis = FakeRedis()
    bad_request = LLMResponseError("bad request", status_code=400)
    primary = FakeLLMClient("primary", complete_error=bad_request)
    secondary = FakeLLMClient("secondary", complete_result=_result("secondary", "served"))
    router = _router([primary, secondary], _breaker(redis))

    with pytest.raises(LLMResponseError):
        await router.complete(MESSAGES)
    assert primary.complete_calls == 1
    assert secondary.complete_calls == 0  # never reached


# --------------------------------------------------------------------------- #
# stream()
# --------------------------------------------------------------------------- #
async def test_stream_primary_succeeds() -> None:
    """A healthy primary streams straight through; the secondary is untouched."""
    redis = FakeRedis()
    primary = FakeLLMClient(
        "primary",
        stream_script=[StreamChunk(content="Hel"), StreamChunk(content="lo")],
    )
    secondary = FakeLLMClient("secondary", stream_script=[StreamChunk(content="no")])
    router = _router([primary, secondary], _breaker(redis))

    received = [chunk async for chunk in router.stream(MESSAGES)]

    assert "".join(c.content or "" for c in received) == "Hello"
    assert secondary.stream_calls == 0


async def test_stream_midstream_failover_resumes_on_secondary() -> None:
    """Primary fails after tokens flow → secondary resumes; one continuous stream.

    The secondary must receive the partial assistant text as a prefill so it
    *continues* the response, and the caller sees ``"Hello world"`` end-to-end
    with no restart of the already-emitted prefix.
    """
    redis = FakeRedis()
    primary = FakeLLMClient(
        "primary",
        stream_script=[StreamChunk(content="Hello "), LLMTimeoutError("dropped mid-stream")],
    )
    secondary = FakeLLMClient(
        "secondary",
        stream_script=[StreamChunk(content="world"), StreamChunk(finish_reason="stop")],
    )
    breaker = _breaker(redis)
    router = _router([primary, secondary], breaker)

    received = [chunk async for chunk in router.stream(MESSAGES)]

    # One continuous stream: primary prefix + secondary continuation.
    assert "".join(c.content or "" for c in received) == "Hello world"
    assert primary.stream_calls == 1
    assert secondary.stream_calls == 1

    # The secondary was handed the partial text as a trailing assistant message.
    assert secondary.last_messages[-1].role == "assistant"
    assert secondary.last_messages[-1].content == "Hello "
    # The primary's mid-stream failure was recorded against it.
    assert redis.store.get("llm:cb:primary:fails") == 1


async def test_stream_first_token_deadline_fails_over() -> None:
    """A primary that never emits a first token breaches the deadline → failover."""
    redis = FakeRedis()

    class NeverYields(FakeLLMClient):
        async def stream(  # type: ignore[override]
            self,
            messages: Sequence[ChatMessage],
            **kwargs: Any,
        ) -> AsyncIterator[StreamChunk]:
            self.stream_calls += 1
            self.last_messages = list(messages)
            await asyncio.sleep(1.0)  # longer than the first-token deadline
            yield StreamChunk(content="too late")

    primary = NeverYields("primary")
    secondary = FakeLLMClient("secondary", stream_script=[StreamChunk(content="fast")])
    router = _router(
        [primary, secondary],
        _breaker(redis),
        first_token_timeout=0.05,
    )

    received = [chunk async for chunk in router.stream(MESSAGES)]

    assert "".join(c.content or "" for c in received) == "fast"
    assert secondary.stream_calls == 1


# --------------------------------------------------------------------------- #
# circuit-breaker unit behavior
# --------------------------------------------------------------------------- #
async def test_breaker_trips_after_threshold_and_success_resets() -> None:
    """Failures trip the circuit at the threshold; a success clears all state."""
    redis = FakeRedis()
    breaker = CircuitBreaker(redis, fail_threshold=2, cooldown_seconds=30)

    assert await breaker.is_open("m") is False
    await breaker.record_failure("m")
    assert await breaker.is_open("m") is False  # below threshold
    await breaker.record_failure("m")
    assert await breaker.is_open("m") is True  # tripped at threshold

    await breaker.record_success("m")
    assert await breaker.is_open("m") is False  # closed again
