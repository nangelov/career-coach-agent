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
from dataclasses import replace
from typing import Any

from app.llm.types import ChatMessage, StreamChunk, ToolCall
from app.schemas.auth import CurrentUser, SessionRole
from app.security.oidc import AuthorizationRequest, OIDCClient, OIDCUserInfo
from app.services.rate_limiting import InMemoryRateLimiter, RateLimitService

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


def fake_current_user(
    session_id: str, *, role: SessionRole = "guest", user_id: str | None = None
) -> CurrentUser:
    """Build a :class:`CurrentUser` for overriding ``require_auth`` in API tests.

    Mirrors what the real :class:`~app.services.auth.SessionAuthenticator` resolves from a
    verified token, so a test can stand in an authenticated caller without minting a JWT or
    seeding a session record.
    """
    return CurrentUser(session_id=session_id, role=role, user_id=user_id)


def unlimited_rate_limit_service() -> RateLimitService:
    """A :class:`RateLimitService` over an in-memory limiter with effectively no cap.

    For API tests that exercise a route *other* than the rate limit itself: overriding
    ``get_rate_limit_service`` with this keeps the real Redis wiring out of the test while
    never tripping the limit. Tests that assert limiting build a service with real caps.
    """
    huge = 10**9
    return RateLimitService(
        InMemoryRateLimiter(),
        guest_message_limit=huge,
        guest_upload_limit=huge,
        guest_window_seconds=3600,
        user_message_limit=huge,
        user_upload_limit=huge,
        user_window_seconds=3600,
    )


class FakeOIDCClient(OIDCClient):
    """A scripted :class:`~app.security.oidc.OIDCClient` stand-in (no network).

    :meth:`create_authorization_request` returns a deterministic request with a per-call
    distinct ``state`` (so multiple begins don't collide) and records what it was asked for;
    :meth:`exchange_code` returns the canned :class:`OIDCUserInfo` (with ``provider`` set to
    the exchanging provider) or raises the configured error. Both record their calls so
    tests can assert PKCE/state wiring.
    """

    def __init__(
        self,
        userinfo: OIDCUserInfo | None = None,
        *,
        exchange_error: Exception | None = None,
    ) -> None:
        self._userinfo = userinfo or OIDCUserInfo(
            provider="google", sub="sub-123", email="user@example.com", display_name="Test User"
        )
        self._exchange_error = exchange_error
        self._counter = 0
        self.authorization_requests: list[tuple[str, str]] = []
        self.exchanges: list[dict[str, str]] = []

    async def create_authorization_request(
        self, *, provider: str, redirect_uri: str
    ) -> AuthorizationRequest:
        self.authorization_requests.append((provider, redirect_uri))
        self._counter += 1
        state = f"state-{self._counter}"
        return AuthorizationRequest(
            url=f"https://provider.example/consent?provider={provider}&state={state}",
            state=state,
            code_verifier=f"verifier-{self._counter}",
            nonce=f"nonce-{self._counter}",
        )

    async def exchange_code(
        self, *, provider: str, redirect_uri: str, code: str, code_verifier: str
    ) -> OIDCUserInfo:
        self.exchanges.append(
            {
                "provider": provider,
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            }
        )
        if self._exchange_error is not None:
            raise self._exchange_error
        return replace(self._userinfo, provider=provider)
