"""P3 phase-exit verification (P3-07) — the guest/SSO/upgrade/access-control criteria end to end.

This is a **verification-only** module (no product code changed): it ties the already-built
P3 building blocks (P3-01 guest session, P3-02 SSO OIDC, P3-03 guest→account upgrade,
P3-04 authZ + rate limits) together and drives them through the **real** HTTP router stack
with **real, minted bearer tokens**, proving the four plan.md P3 exit criteria as one story:

1. **Guest flow** — ``POST /api/auth/guest`` mints a real guest JWT; the guest chats up to the
   Redis-backed cap (10 messages) and the 11th is denied ``429`` with an upgrade prompt.
2. **SSO flow** (mocked provider, no network) — ``login`` → ``callback`` issues a real user
   session JWT; that token authenticates a protected route (``POST /api/chat`` → ``200``).
3. **Upgrade-preserves-session** — a guest chats, mints an upgrade ticket, completes SSO, and
   lands back in the **same** ``session_id`` (record promoted guest→user, prior transcript
   backfilled to durable storage); the promoted user token then chats on that same session.
4. **Cross-user access denied** — user A's token cannot chat into / cancel user B's session
   (own-data-only ``403``), while A's own session still works.

Unlike the per-task API suites (which override ``require_auth`` with a stand-in ``CurrentUser``
or stub a single service), this harness wires **one** shared session store behind a **real**
:class:`~app.services.auth.SessionAuthenticator`, so ``require_auth`` verifies the actual JWTs
minted by the guest/SSO services against live session records — exercising the full
authN → authZ → rate-limit → route path with nothing stubbed but the LLM/tool work and the
datastore drivers (in-memory ports, no Redis/Postgres/HF/network).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import ASGITransport

from app.api.auth import (
    get_guest_auth_service,
    get_guest_upgrade_service,
    get_sso_auth_service,
)
from app.api.chat import get_chat_service
from app.llm.types import ChatMessage
from app.main import app
from app.schemas.chat import ChatEvent, DoneEvent, StartEvent, TokenEvent
from app.security.dependencies import (
    get_rate_limit_service,
    get_session_authenticator,
    require_auth,
)
from app.security.oidc import AuthorizationRequest, OIDCClient, OIDCUserInfo
from app.security.tokens import SessionTokenCodec
from app.services.auth import GuestAuthService, SessionAuthenticator, SsoAuthService
from app.services.conversation_store import ConversationStore
from app.services.guest_upgrade import GuestUpgradeService
from app.services.oauth_state_store import InMemoryOAuthStateStore
from app.services.rate_limiting import InMemoryRateLimiter, RateLimitService
from app.services.session_memory import InMemorySessionMemory
from app.services.session_store import InMemorySessionStore
from app.services.upgrade_ticket_store import InMemoryUpgradeTicketStore
from app.services.user_store import InMemoryUserStore

_SECRET = "p3-exit-verification-secret"


# --------------------------------------------------------------------------- fakes


class _FakeChatService:
    """A canned :class:`~app.services.chat.ChatService` stand-in (no LLM / tools / DB).

    The P3 exit criteria are about the **auth/session boundary**, not the model loop (that is
    P1/P2 territory, already verified), so the service just emits a minimal well-formed SSE
    stream. It records the ``(session_id, user_id)`` it was invoked with so a test can assert
    the router handed the turn the **token-derived** identity, never a client-sent one.
    """

    def __init__(self) -> None:
        self.invocations: list[tuple[str, str | None]] = []

    async def stream_turn(
        self,
        session_id: str,
        message: str,
        *,
        history: Sequence[ChatMessage] | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        self.invocations.append((session_id, user_id))
        yield StartEvent(message_id="m1")
        yield TokenEvent(content="ok")
        yield DoneEvent(message_id="m1", finish_reason="stop")

    async def request_cancel(self, session_id: str) -> None:  # pragma: no cover - unused here
        return None


class _RecordingConversationStore(ConversationStore):
    """Captures durable persist calls so the upgrade test can assert the backfill happened."""

    def __init__(self) -> None:
        self.persisted: list[tuple[str, str, ChatMessage, ChatMessage | None]] = []

    async def persist_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        conversation_id: str | None,
        user_message: ChatMessage,
        assistant_message: ChatMessage | None,
    ) -> str:
        self.persisted.append((user_id, session_id, user_message, assistant_message))
        return "conv-1"

    async def load_history(self, *, user_id: str, session_id: str) -> list[ChatMessage]:
        return []


class _MultiUserOIDCClient(OIDCClient):
    """A no-network OIDC client that resolves a **distinct** user per authorization code.

    ``create_authorization_request`` mints a per-call ``state`` (so concurrent logins do not
    collide); ``exchange_code`` maps the ``code`` to a distinct ``(sub, email)`` so the SSO
    flow can produce two different accounts (needed for the cross-user access-control test).
    An unknown code falls back to a default identity (a plain single-user login).
    """

    def __init__(self) -> None:
        self._counter = 0
        self._by_code: dict[str, OIDCUserInfo] = {
            "code-A": OIDCUserInfo(
                provider="google", sub="user-a", email="a@example.com", display_name="User A"
            ),
            "code-B": OIDCUserInfo(
                provider="google", sub="user-b", email="b@example.com", display_name="User B"
            ),
        }

    async def create_authorization_request(
        self, *, provider: str, redirect_uri: str
    ) -> AuthorizationRequest:
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
        info = self._by_code.get(
            code,
            OIDCUserInfo(
                provider=provider, sub="sub-default", email="d@example.com", display_name="Default"
            ),
        )
        return replace(info, provider=provider)


# --------------------------------------------------------------------------- harness


@dataclass
class _Harness:
    """One test's shared stores + real services, plus the fake chat service.

    A **single** :class:`InMemorySessionStore` is shared by the guest, SSO, upgrade and
    authenticator services, so a token minted by any of them resolves through the real
    :class:`SessionAuthenticator` that ``require_auth`` uses.
    """

    guest_message_limit: int = 10

    def __post_init__(self) -> None:
        self.sessions = InMemorySessionStore()
        self.memory = InMemorySessionMemory()
        self.conversations = _RecordingConversationStore()
        self.codec = SessionTokenCodec(secret=_SECRET, expire_minutes=60)
        self.chat = _FakeChatService()
        self.upgrades = GuestUpgradeService(
            InMemoryUpgradeTicketStore(),
            self.sessions,
            self.memory,
            self.conversations,
            ticket_ttl_seconds=300,
        )
        self.guest = GuestAuthService(self.sessions, self.codec, session_ttl_seconds=3600)
        self.authenticator = SessionAuthenticator(self.codec, self.sessions)
        self.sso = SsoAuthService(
            _MultiUserOIDCClient(),
            InMemoryOAuthStateStore(),
            InMemoryUserStore(),
            self.sessions,
            self.codec,
            redirect_base_url="https://app.example",
            state_ttl_seconds=600,
            session_ttl_seconds=3600,
            providers=frozenset({"google", "linkedin"}),
            upgrades=self.upgrades,
        )
        self.rate_limits = RateLimitService(
            InMemoryRateLimiter(),
            guest_message_limit=self.guest_message_limit,
            guest_upload_limit=1,
            guest_window_seconds=86_400,
            user_message_limit=10**9,
            user_upload_limit=10**9,
            user_window_seconds=3600,
        )

    def overrides(self) -> dict[Callable[..., Any], Callable[..., Any]]:
        return {
            get_guest_auth_service: lambda: self.guest,
            get_sso_auth_service: lambda: self.sso,
            get_guest_upgrade_service: lambda: self.upgrades,
            get_session_authenticator: lambda: self.authenticator,
            get_rate_limit_service: lambda: self.rate_limits,
            get_chat_service: lambda: self.chat,
        }


@pytest.fixture
async def harness() -> AsyncIterator[_Harness]:
    h = _Harness()
    app.dependency_overrides.update(h.overrides())
    try:
        yield h
    finally:
        for dep in h.overrides():
            app.dependency_overrides.pop(dep, None)
        # Defensive: ensure no cross-test leakage even if require_auth was overridden.
        app.dependency_overrides.pop(require_auth, None)


@pytest.fixture
async def client(harness: _Harness) -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _fragment(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).fragment).items()}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login_user(client: httpx.AsyncClient, *, code: str, state: str) -> dict[str, str]:
    """Drive a full mocked-SSO login and return the token fragment (real user session JWT)."""
    login = await client.get("/api/auth/login/google")
    assert login.status_code == 302
    callback = await client.get("/api/auth/callback/google", params={"code": code, "state": state})
    assert callback.status_code == 302
    return _fragment(callback.headers["location"])


# --------------------------------------------------------------------------- 1. guest flow


async def test_guest_flow_chats_to_limit_then_upgrade_prompt(client: httpx.AsyncClient) -> None:
    """Guest session → 10 messages OK → 11th denied 429 with an upgrade prompt (P3-01 + P3-04)."""
    guest = (await client.post("/api/auth/guest")).json()
    assert guest["role"] == "guest"
    headers = _bearer(guest["access_token"])
    session_id = guest["session_id"]
    body = {"session_id": session_id, "message": "hi"}

    # The real guest JWT authenticates the protected chat route for the first 10 messages.
    for _ in range(10):
        ok = await client.post("/api/chat", json=body, headers=headers)
        assert ok.status_code == 200

    # The 11th is stopped at the boundary before any stream opens.
    denied = await client.post("/api/chat", json=body, headers=headers)
    assert denied.status_code == 429
    assert "Sign in" in denied.json()["detail"]
    assert "Retry-After" in denied.headers


async def test_guest_without_token_is_unauthenticated(client: httpx.AsyncClient) -> None:
    """A chat call with no bearer token is 401 (the route is auth-gated, P3-04)."""
    response = await client.post("/api/chat", json={"session_id": "x", "message": "hi"})
    assert response.status_code == 401


# --------------------------------------------------------------------------- 2. SSO flow


async def test_sso_flow_issues_token_that_authenticates_a_protected_route(
    client: httpx.AsyncClient, harness: _Harness
) -> None:
    """Mocked SSO login → callback issues a real user JWT usable on a protected route (P3-02)."""
    token = await _login_user(client, code="code-A", state="state-1")
    assert token["role"] == "user"
    session_id = token["session_id"]

    # The delivered token is a valid, decodable user session JWT bound to that session.
    claims = SessionTokenCodec(secret=_SECRET).decode(token["access_token"])
    assert claims.role == "user"
    assert claims.sid == session_id

    # And it actually authenticates a protected route end-to-end (real require_auth path).
    chat = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "hello"},
        headers=_bearer(token["access_token"]),
    )
    assert chat.status_code == 200

    # The turn was handed the token-derived user identity, never a client-sent field (§7 AuthZ).
    assert harness.chat.invocations[-1][0] == session_id
    assert harness.chat.invocations[-1][1] == claims.sub  # user_id == users.id


async def test_logout_revokes_the_sso_session(client: httpx.AsyncClient) -> None:
    """After logout the still-unexpired JWT stops resolving (record deleted → 401, P3-02)."""
    token = await _login_user(client, code="code-A", state="state-1")
    headers = _bearer(token["access_token"])

    assert (await client.post("/api/auth/logout", headers=headers)).status_code == 204
    # Same token, now revoked → the protected route rejects it.
    after = await client.post(
        "/api/chat",
        json={"session_id": token["session_id"], "message": "hi"},
        headers=headers,
    )
    assert after.status_code == 401


# --------------------------------------------------------------------------- 3. upgrade


async def test_upgrade_preserves_session_and_begins_persisting(
    client: httpx.AsyncClient, harness: _Harness
) -> None:
    """Guest chats → upgrades via SSO → same session continues, now persisted (P3-03)."""
    # 1. Guest starts and has been chatting (seed the shared working memory for the session).
    guest = (await client.post("/api/auth/guest")).json()
    guest_session_id = guest["session_id"]
    await harness.memory.append(
        guest_session_id,
        [
            ChatMessage(role="user", content="how do I switch to product?"),
            ChatMessage(role="assistant", content="Start by...", message_id="m1"),
        ],
    )

    # 2. Mint an upgrade ticket (requires the guest bearer token) and complete SSO with it.
    upgrade = await client.post("/api/auth/upgrade", headers=_bearer(guest["access_token"]))
    assert upgrade.status_code == 201
    ticket = upgrade.json()["upgrade_ticket"]

    login = await client.get(f"/api/auth/login/google?upgrade_ticket={ticket}")
    assert login.status_code == 302
    callback = await client.get(
        "/api/auth/callback/google", params={"code": "code-A", "state": "state-1"}
    )
    assert callback.status_code == 302
    token = _fragment(callback.headers["location"])

    # The user lands back in the SAME session, now logged in.
    assert token["role"] == "user"
    assert token["session_id"] == guest_session_id

    # The session record was promoted in place (guest → user)...
    record = await harness.sessions.get(guest_session_id)
    assert record is not None and record.role == "user" and record.user_id is not None

    # ...the prior conversation was backfilled to durable storage (now persisting)...
    assert len(harness.conversations.persisted) == 1
    uid, sid, user_msg, assistant_msg = harness.conversations.persisted[0]
    assert (sid, uid) == (guest_session_id, record.user_id)
    assert user_msg.content == "how do I switch to product?"

    # ...and the promoted user token continues the SAME conversation on the SAME session_id.
    chat = await client.post(
        "/api/chat",
        json={"session_id": guest_session_id, "message": "and then?"},
        headers=_bearer(token["access_token"]),
    )
    assert chat.status_code == 200
    assert harness.chat.invocations[-1] == (guest_session_id, record.user_id)


# --------------------------------------------------------------------------- 4. cross-user


async def test_cross_user_access_is_denied(client: httpx.AsyncClient, harness: _Harness) -> None:
    """User A cannot chat into / cancel user B's session; A's own session still works (P3-04)."""
    a = await _login_user(client, code="code-A", state="state-1")
    b = await _login_user(client, code="code-B", state="state-2")

    # Distinct users, distinct sessions.
    assert a["session_id"] != b["session_id"]
    a_headers = _bearer(a["access_token"])

    # A names B's session on chat → own-data-only → 403.
    forbidden_chat = await client.post(
        "/api/chat",
        json={"session_id": b["session_id"], "message": "peeking"},
        headers=a_headers,
    )
    assert forbidden_chat.status_code == 403

    # A tries to cancel B's in-flight stream → 403 (closes the P1 "anyone can cancel" gap).
    forbidden_cancel = await client.post(f"/api/chat/{b['session_id']}/cancel", headers=a_headers)
    assert forbidden_cancel.status_code == 403

    # A's own session is unaffected.
    own = await client.post(
        "/api/chat",
        json={"session_id": a["session_id"], "message": "mine"},
        headers=a_headers,
    )
    assert own.status_code == 200

    # The cross-user attempts never reached the service (rejected at the authZ boundary).
    assert [inv[0] for inv in harness.chat.invocations] == [a["session_id"]]
