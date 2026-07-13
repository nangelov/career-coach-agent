"""Unit tests for contact-detail redaction at the LLM egress boundary (§6.16 / §7.6).

Two layers are covered:

* :func:`redact_contact_details` in isolation — every PII category is stripped while
  ordinary CV substance (employers, titles, dates, skills, education) survives verbatim,
  and benign chat is not mangled.
* :class:`~app.llm.router.LLMRouter` — redaction happens **before** the underlying
  ``client`` is called, asserted on the messages the fake client actually receives, on
  both ``complete`` and ``stream``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.llm import (
    ChatMessage,
    CircuitBreaker,
    CompletionResult,
    LLMClient,
    LLMRouter,
    StreamChunk,
    ToolSchema,
    redact_contact_details,
    redact_messages,
)

# --------------------------------------------------------------------------- #
# A representative CV snippet: contact block + real substance to preserve.
# --------------------------------------------------------------------------- #
CV_TEXT = (
    "Jane Doe\n"
    "Email: jane.doe@example.com\n"
    "Phone: +1 (415) 555-0198\n"
    "123 Market Street\n"
    "Springfield, IL 62704\n"
    "https://www.linkedin.com/in/jane-doe\n"
    "\n"
    "Experience\n"
    "Senior Engineer at Acme Corp, 2019-2023\n"
    "Skills: Python, Kubernetes, PostgreSQL\n"
    "Education: BSc Computer Science, MIT, 2015-2019\n"
)


# --------------------------------------------------------------------------- #
# redact_contact_details
# --------------------------------------------------------------------------- #
def test_strips_email() -> None:
    assert "jane.doe@example.com" not in redact_contact_details(CV_TEXT)
    assert "[EMAIL REDACTED]" in redact_contact_details(CV_TEXT)


def test_strips_phone() -> None:
    out = redact_contact_details(CV_TEXT)
    assert "555-0198" not in out
    assert "[PHONE REDACTED]" in out


def test_strips_url() -> None:
    out = redact_contact_details(CV_TEXT)
    assert "linkedin.com/in/jane-doe" not in out
    assert "[URL REDACTED]" in out


def test_strips_postal_address() -> None:
    out = redact_contact_details(CV_TEXT)
    assert "123 Market Street" not in out
    assert "Springfield, IL 62704" not in out
    assert "[ADDRESS REDACTED]" in out


def test_strips_name() -> None:
    out = redact_contact_details(CV_TEXT)
    # Both the header name and the labelled "Email:"/"Name:" line-value are gone.
    assert "Jane Doe" not in out
    assert "[NAME REDACTED]" in out


def test_preserves_cv_substance() -> None:
    """Employers, titles, dates, skills, education must pass through unchanged."""
    out = redact_contact_details(CV_TEXT)
    assert "Senior Engineer at Acme Corp, 2019-2023" in out
    assert "Skills: Python, Kubernetes, PostgreSQL" in out
    assert "Education: BSc Computer Science, MIT, 2015-2019" in out


def test_date_range_not_treated_as_phone() -> None:
    """A bare year range shares digit-shape with a phone but must not be redacted."""
    assert redact_contact_details("Worked there 2019-2023.") == "Worked there 2019-2023."


def test_ordinary_chat_unchanged() -> None:
    """No false-positive mangling of a normal career question."""
    msg = "How do I improve my resume for a senior backend engineer role?"
    assert redact_contact_details(msg) == msg


def test_labelled_name_line() -> None:
    assert "[NAME REDACTED]" in redact_contact_details("Name: John Q. Public")


def test_empty_text_is_noop() -> None:
    assert redact_contact_details("") == ""


# --------------------------------------------------------------------------- #
# redact_messages
# --------------------------------------------------------------------------- #
def test_redact_messages_only_touches_content() -> None:
    messages = [
        ChatMessage(role="system", content="You are a coach."),
        ChatMessage(role="user", content="Email: a@b.com"),
    ]
    out = redact_messages(messages)
    assert out[0].content == "You are a coach."  # unchanged → same object reuse
    assert out[0] is messages[0]
    assert "[EMAIL REDACTED]" in (out[1].content or "")


def test_redact_messages_handles_none_content() -> None:
    messages = [ChatMessage(role="assistant", content=None)]
    assert redact_messages(messages)[0] is messages[0]


# --------------------------------------------------------------------------- #
# Router integration — redaction happens before the client is called
# --------------------------------------------------------------------------- #
class _RecordingClient(LLMClient):
    """Records the messages the router actually forwards to the provider."""

    def __init__(self, model: str) -> None:
        self._model = model
        self.received: list[ChatMessage] = []

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
        self.received = list(messages)
        return CompletionResult(content="ok", model=self._model, finish_reason="stop")

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
        self.received = list(messages)
        yield StreamChunk(content="ok")


class _FakeRedis:
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


def _router(client: LLMClient) -> LLMRouter:
    breaker = CircuitBreaker(_FakeRedis(), fail_threshold=3, cooldown_seconds=30)
    return LLMRouter([client], breaker, first_token_timeout=None)


async def test_complete_redacts_before_client_call() -> None:
    client = _RecordingClient("primary")
    router = _router(client)

    await router.complete([ChatMessage(role="user", content="reach me at a@b.com")])

    forwarded = client.received[0].content or ""
    assert "a@b.com" not in forwarded
    assert "[EMAIL REDACTED]" in forwarded


async def test_stream_redacts_before_client_call() -> None:
    client = _RecordingClient("primary")
    router = _router(client)

    chunks = [
        chunk
        async for chunk in router.stream(
            [ChatMessage(role="user", content="my number is +1 (415) 555-0198")]
        )
    ]

    assert chunks  # stream produced output
    forwarded = client.received[0].content or ""
    assert "555-0198" not in forwarded
    assert "[PHONE REDACTED]" in forwarded
