"""API test for the guest→account upgrade flow (P3-03) — no Redis / Postgres / network.

Wires the guest, session-authenticator, upgrade and SSO services over **shared** process-local
stores + a scripted :class:`~tests.fakes.FakeOIDCClient`, so the whole Router → Service path
runs end-to-end. Asserts the acceptance criteria: a guest starts a session and chats, mints an
upgrade ticket, completes SSO, and lands back in the **same** session (same ``session_id``,
record promoted to ``role="user"``) with its prior conversation backfilled to durable storage
— and that only a guest can mint a ticket.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import ASGITransport

from app.api.auth import (
    get_guest_auth_service,
    get_guest_upgrade_service,
    get_sso_auth_service,
)
from app.llm.types import ChatMessage
from app.main import app
from app.security.dependencies import get_session_authenticator
from app.security.tokens import SessionTokenCodec
from app.services.auth import GuestAuthService, SessionAuthenticator, SsoAuthService
from app.services.conversation_store import ConversationStore
from app.services.guest_upgrade import GuestUpgradeService
from app.services.oauth_state_store import InMemoryOAuthStateStore
from app.services.session_memory import InMemorySessionMemory
from app.services.session_store import InMemorySessionStore
from app.services.upgrade_ticket_store import InMemoryUpgradeTicketStore
from app.services.user_store import InMemoryUserStore
from tests.fakes import FakeOIDCClient

_SECRET = "guest-upgrade-api-test-secret"


class _RecordingConversationStore(ConversationStore):
    """Captures durable persist calls so the API test can assert the backfill happened."""

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


class _Wiring:
    """The shared stores + services backing one test's overrides."""

    def __init__(self) -> None:
        self.sessions = InMemorySessionStore()
        self.memory = InMemorySessionMemory()
        self.conversations = _RecordingConversationStore()
        self.codec = SessionTokenCodec(secret=_SECRET, expire_minutes=60)
        self.upgrades = GuestUpgradeService(
            InMemoryUpgradeTicketStore(),
            self.sessions,
            self.memory,
            self.conversations,
            ticket_ttl_seconds=300,
        )
        self.guest = GuestAuthService(
            self.sessions,
            self.codec,
            session_ttl_seconds=3600,
            consent_policy_version="2026-07-13",
        )
        self.authenticator = SessionAuthenticator(self.codec, self.sessions)
        self.sso = SsoAuthService(
            FakeOIDCClient(),
            InMemoryOAuthStateStore(),
            InMemoryUserStore(),
            self.sessions,
            self.codec,
            redirect_base_url="https://app.example",
            state_ttl_seconds=600,
            session_ttl_seconds=3600,
            providers=frozenset({"google", "linkedin"}),
            consent_policy_version="2026-07-13",
            upgrades=self.upgrades,
        )


@pytest.fixture
async def wiring() -> AsyncIterator[_Wiring]:
    w = _Wiring()
    app.dependency_overrides[get_guest_auth_service] = lambda: w.guest
    app.dependency_overrides[get_session_authenticator] = lambda: w.authenticator
    app.dependency_overrides[get_guest_upgrade_service] = lambda: w.upgrades
    app.dependency_overrides[get_sso_auth_service] = lambda: w.sso
    try:
        yield w
    finally:
        for dep in (
            get_guest_auth_service,
            get_session_authenticator,
            get_guest_upgrade_service,
            get_sso_auth_service,
        ):
            app.dependency_overrides.pop(dep, None)


@pytest.fixture
async def client(wiring: _Wiring) -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _fragment(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).fragment).items()}


async def test_guest_upgrade_preserves_session_and_persists(
    client: httpx.AsyncClient, wiring: _Wiring
) -> None:
    # 1. Start a guest session.
    guest = (await client.post("/api/auth/guest", json={"consent": True})).json()
    guest_session_id = guest["session_id"]
    guest_headers = {"Authorization": f"Bearer {guest['access_token']}"}

    # 2. The guest has been chatting — seed the shared working memory for that session.
    await wiring.memory.append(
        guest_session_id,
        [
            ChatMessage(role="user", content="how do I switch to product?"),
            ChatMessage(role="assistant", content="Start by...", message_id="m1"),
        ],
    )

    # 3. Mint an upgrade ticket (requires the guest bearer token).
    upgrade = await client.post("/api/auth/upgrade", headers=guest_headers)
    assert upgrade.status_code == 201
    ticket = upgrade.json()["upgrade_ticket"]

    # 4. Begin SSO carrying the ticket → 302 to the provider consent screen.
    login = await client.get(f"/api/auth/login/google?upgrade_ticket={ticket}&consent=1")
    assert login.status_code == 302

    # 5. Provider redirects back to the callback → 302 to the frontend with the token.
    callback = await client.get(
        "/api/auth/callback/google", params={"code": "auth-code", "state": "state-1"}
    )
    assert callback.status_code == 302
    token = _fragment(callback.headers["location"])

    # The user lands back in the SAME session, now as a logged-in user.
    assert token["role"] == "user"
    assert token["session_id"] == guest_session_id
    claims = SessionTokenCodec(secret=_SECRET).decode(token["access_token"])
    assert claims.sid == guest_session_id

    # The session record was promoted in place (guest → user).
    record = await wiring.sessions.get(guest_session_id)
    assert record is not None
    assert record.role == "user"
    assert record.user_id is not None

    # The prior conversation was backfilled to durable storage under the new user.
    assert len(wiring.conversations.persisted) == 1
    uid, sid, user_msg, assistant_msg = wiring.conversations.persisted[0]
    assert (sid, uid) == (guest_session_id, record.user_id)
    assert user_msg.content == "how do I switch to product?"
    assert assistant_msg is not None and assistant_msg.message_id == "m1"


async def test_upgrade_requires_bearer_token(client: httpx.AsyncClient) -> None:
    # No Authorization header → 401 (an upgrade must be tied to a verified guest session).
    response = await client.post("/api/auth/upgrade")
    assert response.status_code == 401


async def test_logged_in_user_cannot_upgrade(client: httpx.AsyncClient, wiring: _Wiring) -> None:
    # A user token (not a guest) has nothing to upgrade → 409 Conflict.
    await client.get("/api/auth/login/google", params={"consent": "1"})
    callback = await client.get(
        "/api/auth/callback/google", params={"code": "c", "state": "state-1"}
    )
    user_token = _fragment(callback.headers["location"])["access_token"]

    response = await client.post(
        "/api/auth/upgrade", headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 409


async def test_plain_login_without_ticket_mints_fresh_session(
    client: httpx.AsyncClient, wiring: _Wiring
) -> None:
    # A normal login (no upgrade ticket) is unaffected: a fresh session id, nothing backfilled.
    await client.get("/api/auth/login/google", params={"consent": "1"})
    callback = await client.get(
        "/api/auth/callback/google", params={"code": "c", "state": "state-1"}
    )
    token = _fragment(callback.headers["location"])
    assert token["role"] == "user"
    assert token["session_id"]
    assert wiring.conversations.persisted == []
