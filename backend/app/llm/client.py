"""``LLMClient`` interface + HF Inference Providers (OpenAI-compatible) client.

Design refs: app-design-and-features.md §6 item 6 (primary LLM, native
tool-calling — the v1 ReAct parser stays deleted), §6.6 (this client is the clean
single-provider unit the failover **router** wraps), §8 (`backend/app/llm/client.py`).

Scope of *this* module (P1-01): a single-provider client only — chat completion
with native tool-calling, and token streaming.  **No** failover / retry-across-
models / circuit-breaker logic: that is `llm/router.py` (P1-02), which composes one
`LLMClient` per model.  Accordingly this client defaults to ``max_retries=0`` so
retry/backoff policy lives in exactly one place (the router).

The concrete client talks to HF Inference Providers through its **OpenAI-compatible**
chat-completions endpoint via the ``openai`` async SDK.  The provider SDK is an
implementation detail confined to this file — callers depend on the ``LLMClient``
ABC and the first-party models in ``types.py`` / ``errors.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any, cast

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
    RateLimitError,
    omit,
)

from app.config import Settings, settings

from .errors import (
    LLMConnectionError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from .types import (
    ChatMessage,
    CompletionResult,
    FunctionCall,
    StreamChunk,
    ToolCall,
    ToolCallDelta,
    ToolSchema,
)

__all__ = [
    "HFOpenAICompatibleClient",
    "LLMClient",
    "ToolSchema",
]

if TYPE_CHECKING:
    from openai.types.chat import (
        ChatCompletionMessageParam,
        ChatCompletionToolChoiceOptionParam,
        ChatCompletionToolParam,
    )


class LLMClient(ABC):
    """Interface every LLM caller depends on — never a concrete provider SDK.

    Two capabilities, both with native tool-calling:

    * :meth:`complete` — a full (buffered) chat completion.
    * :meth:`stream` — an async generator of incremental deltas (content and, when
      the provider supports it, tool-call fragments).

    One client instance is bound to one model id; the failover router (P1-02)
    holds an ordered list of these.
    """

    @property
    @abstractmethod
    def model(self) -> str:
        """The model id this client is bound to."""

    @abstractmethod
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
        """Run a single chat completion and return the full result.

        Args:
            messages: The conversation so far (system/user/assistant/tool).
            tools: Native tool schemas (JSON-schema function definitions) the model
                may call.  ``None`` disables tool-calling for this call.
            tool_choice: ``"auto"`` / ``"none"`` / ``"required"`` or a specific
                ``{"type": "function", "function": {"name": ...}}`` selector.
            temperature: Sampling temperature; provider default when ``None``.
            max_tokens: Max tokens to generate; provider default when ``None``.
            timeout: Per-call timeout in seconds; the client default when ``None``.

        Raises:
            LLMError: (or a subclass) on timeout, connection, rate-limit, or
                non-success response — never a raw provider SDK exception.
        """

    @abstractmethod
    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion as incremental :class:`StreamChunk` deltas.

        Same arguments and error contract as :meth:`complete`.  The provider SDK
        error is translated to an :class:`LLMError` when the stream is opened *or*
        while it is being consumed (mid-stream failures surface to the caller — the
        router, P1-02, is what resumes them on the secondary model, §6.6).
        """


class HFOpenAICompatibleClient(LLMClient):
    """``LLMClient`` over HF Inference Providers' OpenAI-compatible endpoint.

    Uses the ``openai`` async SDK pointed at the HF base URL so native
    ``tools`` / ``tool_calls`` and SSE token streaming come for free — no ReAct
    text parsing anywhere.
    """

    def __init__(
        self,
        *,
        model: str,
        api_token: str,
        base_url: str,
        default_timeout: float = 30.0,
        max_retries: int = 0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Construct a client bound to one ``model``.

        Args:
            model: The provider model id (e.g. ``"zai-org/GLM-5.2"``).
            api_token: HF API token (from settings / Space secrets — never hard-coded).
            base_url: OpenAI-compatible base URL for HF Inference Providers.
            default_timeout: Default per-call timeout in seconds.
            max_retries: SDK-level retries.  Defaults to ``0`` — retry/backoff and
                failover are the router's job (§6.6), kept out of the single client.
            http_client: Optional injected ``httpx.AsyncClient`` (tests supply a
                mock-transport client so no real network call is made).
        """
        self._model = model
        self._default_timeout = default_timeout
        self._client = AsyncOpenAI(
            api_key=api_token,
            base_url=base_url,
            timeout=default_timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

    @classmethod
    def from_settings(
        cls,
        config: Settings = settings,
        *,
        model: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> HFOpenAICompatibleClient:
        """Build a client from application config (env / HF Space secrets).

        Defaults to the primary model (``LLM_PRIMARY_MODEL``); pass ``model`` to
        bind a different one (the router builds one client per model in its list).
        """
        return cls(
            model=model or config.LLM_PRIMARY_MODEL,
            api_token=config.HF_API_TOKEN,
            base_url=config.LLM_BASE_URL,
            default_timeout=float(config.LLM_TIMEOUT_SECONDS),
            http_client=http_client,
        )

    @property
    def model(self) -> str:
        return self._model

    async def aclose(self) -> None:
        """Close the underlying provider client and its HTTP connections."""
        await self._client.close()

    # -- LLMClient API ------------------------------------------------------

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
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=self._to_message_params(messages),
                tools=self._to_tool_params(tools),
                tool_choice=self._to_tool_choice_param(tool_choice),
                temperature=temperature if temperature is not None else omit,
                max_tokens=max_tokens if max_tokens is not None else omit,
                timeout=timeout if timeout is not None else self._default_timeout,
                stream=False,
            )
        except Exception as exc:  # noqa: BLE001 - re-raised as a translated LLMError
            raise self._translate_error(exc) from exc
        return self._to_result(response)

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
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=self._to_message_params(messages),
                tools=self._to_tool_params(tools),
                tool_choice=self._to_tool_choice_param(tool_choice),
                temperature=temperature if temperature is not None else omit,
                max_tokens=max_tokens if max_tokens is not None else omit,
                timeout=timeout if timeout is not None else self._default_timeout,
                stream=True,
            )
        except Exception as exc:  # noqa: BLE001 - re-raised as a translated LLMError
            raise self._translate_error(exc) from exc

        try:
            async for chunk in stream:
                parsed = self._to_stream_chunk(chunk)
                if parsed is not None:
                    yield parsed
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - mid-stream failure, translated
            raise self._translate_error(exc) from exc

    # -- request payload builders ------------------------------------------

    @staticmethod
    def _to_message_params(
        messages: Sequence[ChatMessage],
    ) -> list[ChatCompletionMessageParam]:
        return cast(
            "list[ChatCompletionMessageParam]",
            [message.to_openai() for message in messages],
        )

    @staticmethod
    def _to_tool_params(
        tools: Sequence[ToolSchema] | None,
    ) -> list[ChatCompletionToolParam] | Any:
        if not tools:
            return omit
        return cast("list[ChatCompletionToolParam]", list(tools))

    @staticmethod
    def _to_tool_choice_param(
        tool_choice: str | dict[str, Any] | None,
    ) -> ChatCompletionToolChoiceOptionParam | Any:
        if tool_choice is None:
            return omit
        return cast("ChatCompletionToolChoiceOptionParam", tool_choice)

    # -- response parsing ---------------------------------------------------

    def _to_result(self, response: Any) -> CompletionResult:
        choice = response.choices[0]
        message = choice.message
        usage = response.usage
        return CompletionResult(
            content=message.content,
            tool_calls=self._parse_tool_calls(message.tool_calls),
            finish_reason=choice.finish_reason,
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage is not None else None,
            completion_tokens=usage.completion_tokens if usage is not None else None,
        )

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: Any) -> list[ToolCall]:
        if not raw_tool_calls:
            return []
        calls: list[ToolCall] = []
        for raw in raw_tool_calls:
            function = raw.function
            calls.append(
                ToolCall(
                    id=raw.id,
                    function=FunctionCall(
                        name=function.name,
                        arguments=function.arguments or "",
                    ),
                )
            )
        return calls

    @staticmethod
    def _to_stream_chunk(chunk: Any) -> StreamChunk | None:
        choices = chunk.choices
        if not choices:
            # Some providers emit a leading/usage-only chunk with no choices.
            return None
        choice = choices[0]
        delta = choice.delta

        tool_call_deltas: list[ToolCallDelta] | None = None
        raw_tool_calls = getattr(delta, "tool_calls", None)
        if raw_tool_calls:
            tool_call_deltas = []
            for raw in raw_tool_calls:
                function = raw.function
                tool_call_deltas.append(
                    ToolCallDelta(
                        index=raw.index,
                        id=raw.id,
                        name=function.name if function is not None else None,
                        arguments=function.arguments if function is not None else None,
                    )
                )

        return StreamChunk(
            content=delta.content,
            tool_call_deltas=tool_call_deltas,
            finish_reason=choice.finish_reason,
        )

    # -- error translation --------------------------------------------------

    @staticmethod
    def _translate_error(exc: Exception) -> LLMError:
        """Map a provider SDK exception onto the first-party hierarchy.

        Order matters: ``APITimeoutError`` subclasses ``APIConnectionError`` and
        ``RateLimitError`` subclasses ``APIStatusError`` in the ``openai`` SDK, so
        the most specific types are checked first.
        """
        if isinstance(exc, LLMError):
            return exc
        if isinstance(exc, APITimeoutError):
            return LLMTimeoutError(str(exc))
        if isinstance(exc, APIConnectionError):
            return LLMConnectionError(str(exc))
        if isinstance(exc, RateLimitError):
            return LLMRateLimitError(str(exc), status_code=exc.status_code)
        if isinstance(exc, APIStatusError):
            return LLMResponseError(str(exc), status_code=exc.status_code)
        if isinstance(exc, OpenAIError):
            return LLMError(str(exc))
        return LLMError(str(exc))
