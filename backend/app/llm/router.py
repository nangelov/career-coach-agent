"""Multi-LLM failover router (design §6.6).

A single HF endpoint that is slow or down would stall the whole app. The
:class:`LLMRouter` wraps an **ordered list** of :class:`LLMClient` instances
(one per model) and adds the reliability policy the single-provider client
(P1-01) deliberately left out:

* **Failover order** — primary ``zai-org/GLM-5.2`` → secondary
  ``Qwen/Qwen3.6-27B`` (both free OSS via HF Inference Providers), config-driven
  via :attr:`Settings.LLM_MODELS` so the order can change with **no code change**.
  **No paid last-resort** entry — the list is free/OSS only.
* **Per-call timeout** reused from the client, plus a **first-token deadline** for
  streaming (a primary that accepts the request but never emits a token fails over).
* **Retry/backoff** for transient ``5xx``/``429`` on the *same* model, distinct from
  failover to the *next* model.
* **Redis-backed circuit-breaker** (:class:`CircuitBreaker`): a model that recently
  errored/timed out is skipped for a cooldown window, then probed again when the
  cooldown key expires (the next request after cooldown *is* the recovery probe).
* **Mid-stream failover = resume [DECIDED]:** if a model fails *after* tokens have
  streamed, the router resumes on the next model by prefilling the partial
  assistant text, and yields only the *continuation* — the caller sees one
  continuous stream, never a restart or a "switching models" notice.

Callers (``agents/`` graph, ``api/chat.py``) depend on this router, not a raw
``LLMClient`` — its :meth:`complete` / :meth:`stream` mirror the client surface so
it is a drop-in that adds resilience.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.config import Settings, settings

from .client import HFOpenAICompatibleClient, LLMClient, ToolSchema
from .errors import (
    LLMAllModelsFailedError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from .redaction import redact_messages
from .types import ChatMessage, CompletionResult, StreamChunk

if TYPE_CHECKING:  # pragma: no cover - typing only
    import httpx


@runtime_checkable
class RedisLike(Protocol):
    """The minimal async Redis surface the circuit-breaker needs.

    Kept as a structural :class:`Protocol` (not a hard import of ``redis``) so this
    module carries no datastore dependency and unit tests can inject a fake. The
    real ``redis.asyncio.Redis`` — acquired from the shared connection pool in
    ``repositories/redis.py`` (§4) — satisfies this shape; the router never
    constructs its own Redis client.
    """

    async def get(self, name: str) -> Any: ...
    async def set(self, name: str, value: Any, *, ex: int | None = None) -> Any: ...
    async def incr(self, name: str) -> int: ...
    async def expire(self, name: str, time: int) -> Any: ...
    async def delete(self, *names: str) -> Any: ...


class CircuitBreaker:
    """Per-model health tracking in Redis (§6.6).

    State is two short-lived keys per model:

    * ``<prefix>:<model>:fails`` — a failure counter with a rolling-window TTL.
    * ``<prefix>:<model>:open``  — an "open circuit" marker with a cooldown TTL;
      while it exists the model is skipped.

    When the failure count reaches ``fail_threshold`` within the window the open
    marker is set for ``cooldown_seconds`` and the counter cleared. The marker's
    natural TTL expiry *is* the recovery probe: once it lapses the model is
    eligible again and the next request retries (probes) it; a success clears all
    state, a fresh failure starts the count over.
    """

    def __init__(
        self,
        redis_client: RedisLike,
        *,
        fail_threshold: int = 3,
        cooldown_seconds: int = 30,
        window_seconds: int = 60,
        key_prefix: str = "llm:cb",
    ) -> None:
        self._redis = redis_client
        self._fail_threshold = max(1, fail_threshold)
        self._cooldown_seconds = cooldown_seconds
        self._window_seconds = window_seconds
        self._key_prefix = key_prefix

    def _open_key(self, model: str) -> str:
        return f"{self._key_prefix}:{model}:open"

    def _fail_key(self, model: str) -> str:
        return f"{self._key_prefix}:{model}:fails"

    async def is_open(self, model: str) -> bool:
        """Whether ``model``'s circuit is open (should be skipped)."""
        return await self._redis.get(self._open_key(model)) is not None

    async def record_failure(self, model: str) -> None:
        """Count a failure; trip the circuit when the threshold is reached."""
        fail_key = self._fail_key(model)
        count = await self._redis.incr(fail_key)
        if count == 1:
            # First failure in a new window — bound the counter's lifetime.
            await self._redis.expire(fail_key, self._window_seconds)
        if count >= self._fail_threshold:
            await self._redis.set(self._open_key(model), "1", ex=self._cooldown_seconds)
            await self._redis.delete(fail_key)

    async def record_success(self, model: str) -> None:
        """Clear all failure/open state for ``model`` (it is healthy)."""
        await self._redis.delete(self._fail_key(model), self._open_key(model))


class LLMRouter:
    """Failover router over an ordered list of :class:`LLMClient` instances (§6.6).

    One :class:`LLMClient` is bound to one model; the router holds several in
    priority order and applies retry/backoff, per-call + first-token timeouts, a
    Redis circuit-breaker, and mid-stream resume across them.
    """

    def __init__(
        self,
        clients: Sequence[LLMClient],
        breaker: CircuitBreaker,
        *,
        max_retries: int = 2,
        backoff_base_seconds: float = 0.5,
        backoff_max_seconds: float = 8.0,
        first_token_timeout: float | None = 15.0,
        per_call_timeout: float | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not clients:
            raise ValueError("LLMRouter requires at least one LLMClient")
        self._clients = list(clients)
        self._breaker = breaker
        self._max_retries = max(0, max_retries)
        self._backoff_base = backoff_base_seconds
        self._backoff_max = backoff_max_seconds
        self._first_token_timeout = first_token_timeout
        self._per_call_timeout = per_call_timeout
        self._sleep = sleep

    @classmethod
    def from_settings(
        cls,
        config: Settings = settings,
        *,
        redis_client: RedisLike,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> LLMRouter:
        """Build a router from application config (env / HF Space secrets).

        The model list comes from :attr:`Settings.LLM_MODELS` when set, else the
        primary/secondary pair — always free/OSS, **no paid last-resort** (§6.6).
        One :class:`HFOpenAICompatibleClient` is created per model id.
        """
        model_ids = config.LLM_MODELS or [
            config.LLM_PRIMARY_MODEL,
            config.LLM_SECONDARY_MODEL,
        ]
        clients = [
            HFOpenAICompatibleClient.from_settings(config, model=model_id, http_client=http_client)
            for model_id in model_ids
        ]
        breaker = CircuitBreaker(
            redis_client,
            fail_threshold=config.LLM_CIRCUIT_FAIL_THRESHOLD,
            cooldown_seconds=config.LLM_CIRCUIT_COOLDOWN_SECONDS,
            window_seconds=config.LLM_CIRCUIT_WINDOW_SECONDS,
        )
        return cls(
            clients,
            breaker,
            max_retries=config.LLM_MAX_RETRIES,
            backoff_base_seconds=config.LLM_RETRY_BACKOFF_SECONDS,
            backoff_max_seconds=config.LLM_RETRY_BACKOFF_MAX_SECONDS,
            first_token_timeout=config.LLM_FIRST_TOKEN_TIMEOUT_SECONDS,
            per_call_timeout=float(config.LLM_TIMEOUT_SECONDS),
            sleep=sleep,
        )

    @property
    def models(self) -> list[str]:
        """The model ids in failover priority order."""
        return [client.model for client in self._clients]

    async def aclose(self) -> None:
        """Close every underlying client (best-effort)."""
        for client in self._clients:
            aclose = getattr(client, "aclose", None)
            if callable(aclose):
                await aclose()

    # -- non-streaming ------------------------------------------------------

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        """Complete against the first healthy model, failing over on failure.

        Transient ``5xx``/``429`` are retried on the same model (backoff) before
        failing over; a client ``4xx`` (non-429) is not failed over — it would
        fail on every model — and is re-raised immediately.

        Contact-detail PII is stripped from outbound content here (§6.16 / §7.6),
        at this single chokepoint, before any underlying ``client`` call.
        """
        messages = redact_messages(messages)
        last_error: LLMError | None = None
        attempted = False
        for client in self._clients:
            if await self._breaker.is_open(client.model):
                continue
            attempted = True
            try:
                result = await self._complete_one(
                    client,
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except LLMError as exc:
                if self._is_client_error(exc):
                    raise
                await self._breaker.record_failure(client.model)
                last_error = exc
                continue
            await self._breaker.record_success(client.model)
            return result
        raise LLMAllModelsFailedError(self._exhausted_message(attempted)) from last_error

    async def _complete_one(
        self,
        client: LLMClient,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None,
        tool_choice: str | dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> CompletionResult:
        """One model's completion with same-model retry for transient errors."""
        attempt = 0
        while True:
            try:
                return await client.complete(
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self._per_call_timeout,
                )
            except LLMError as exc:
                if self._is_transient(exc) and attempt < self._max_retries:
                    attempt += 1
                    await self._sleep(self._backoff(attempt))
                    continue
                raise

    # -- streaming ----------------------------------------------------------

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream from the first healthy model, resuming on the next on failure.

        Mid-stream failover = **resume** (§6.6): the content emitted so far is
        buffered; if the active model fails after tokens have flowed, the router
        prefills that partial text as a trailing assistant message and streams the
        *continuation* from the next model. The caller sees one continuous stream
        — no restart, no user-facing "switching models" notice. A failure before
        any token is a clean failover (fresh stream, no prefill).

        Contact-detail PII is stripped from outbound content here (§6.16 / §7.6),
        at this single chokepoint, before any underlying ``client`` call. The
        mid-stream ``accumulated`` prefill is model-generated continuation (built
        from already-redacted input) and is not re-redacted.
        """
        base_messages = redact_messages(messages)
        accumulated = ""
        last_error: LLMError | None = None
        attempted = False
        for client in self._clients:
            if await self._breaker.is_open(client.model):
                continue
            attempted = True
            attempt_messages = (
                [*base_messages, ChatMessage(role="assistant", content=accumulated)]
                if accumulated
                else base_messages
            )
            try:
                async for chunk in self._stream_one(
                    client,
                    attempt_messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    if chunk.content:
                        accumulated += chunk.content
                    yield chunk
            except LLMError as exc:
                if self._is_client_error(exc):
                    raise
                await self._breaker.record_failure(client.model)
                last_error = exc
                continue
            await self._breaker.record_success(client.model)
            return
        raise LLMAllModelsFailedError(self._exhausted_message(attempted)) from last_error

    async def _stream_one(
        self,
        client: LLMClient,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None,
        tool_choice: str | dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> AsyncIterator[StreamChunk]:
        """One model's stream: retry the *open* on transient errors, enforce a
        first-token deadline, then relay chunks. Once a token has been emitted, an
        error propagates (to the caller's failover) rather than retrying here."""
        attempt = 0
        while True:
            emitted = False
            agen = client.stream(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self._per_call_timeout,
            )
            try:
                first = await self._first_chunk(agen)
                if first is not None:
                    emitted = True
                    yield first
                    async for chunk in agen:
                        yield chunk
                return
            except LLMError as exc:
                if not emitted and self._is_transient(exc) and attempt < self._max_retries:
                    attempt += 1
                    await self._sleep(self._backoff(attempt))
                    continue
                raise
            finally:
                if isinstance(agen, AsyncGenerator):
                    await agen.aclose()

    async def _first_chunk(self, agen: AsyncIterator[StreamChunk]) -> StreamChunk | None:
        """Pull the first chunk under the first-token deadline (§6.6).

        Returns ``None`` for an empty stream; a breached deadline surfaces as
        :class:`LLMTimeoutError` so the caller fails over to the next model.
        """
        try:
            if self._first_token_timeout is None:
                return await agen.__anext__()
            return await asyncio.wait_for(agen.__anext__(), timeout=self._first_token_timeout)
        except StopAsyncIteration:
            return None
        except TimeoutError as exc:
            raise LLMTimeoutError(
                f"first-token deadline of {self._first_token_timeout}s exceeded"
            ) from exc

    # -- policy helpers -----------------------------------------------------

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff (base * 2**(attempt-1)), capped."""
        return min(self._backoff_base * (2.0 ** (attempt - 1)), self._backoff_max)

    @staticmethod
    def _is_transient(exc: LLMError) -> bool:
        """Retry the *same* model: rate-limit (429) or a transient ``5xx``."""
        if isinstance(exc, LLMRateLimitError):
            return True
        if isinstance(exc, LLMResponseError):
            code = exc.status_code
            return code is not None and 500 <= code < 600
        return False

    @staticmethod
    def _is_client_error(exc: LLMError) -> bool:
        """A ``4xx`` (non-429) that would fail on every model — do not fail over."""
        if isinstance(exc, LLMRateLimitError):
            return False
        if isinstance(exc, LLMResponseError):
            code = exc.status_code
            return code is not None and 400 <= code < 500
        return False

    @staticmethod
    def _exhausted_message(attempted: bool) -> str:
        if not attempted:
            return "all LLM models are unhealthy (every circuit is open)"
        return "all LLM models failed to serve the request"
