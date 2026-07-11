"""API tests for the admin-only feedback-read endpoint (P3-05, §7/§9).

Drives the real feedback router (``GET /api/feedback``) with a stand-in authenticated caller
(``require_auth`` override), an in-memory :class:`~app.services.user_store.InMemoryUserStore`
(``get_user_store`` override) that decides admin-ness, and an in-memory
:class:`~app.services.feedback.InMemoryFeedbackReader` (``get_feedback_reader`` override) —
so no Postgres / Redis wiring runs. Asserts the access-control matrix that replaces v1's
``GET /get-feedback?key=<HF_TOKEN>``:

* an admin user can read the feedback list (``200``);
* an ordinary (non-admin) user is denied (``403``);
* a guest is denied (``403``);
* an unauthenticated request is denied (``401``) — and no shared secret in the URL grants access.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from httpx import ASGITransport

from app.api.feedback import get_feedback_reader
from app.main import app
from app.schemas.feedback import FeedbackEntry
from app.security.dependencies import get_user_store, require_auth
from app.services.feedback import InMemoryFeedbackReader
from app.services.user_store import InMemoryUserStore
from tests.fakes import fake_current_user


def _reader_with_two_entries() -> InMemoryFeedbackReader:
    now = datetime.now(UTC)
    return InMemoryFeedbackReader(
        [
            FeedbackEntry(
                id="f1",
                content="older feedback",
                contact=None,
                user_id=None,
                session_id="s-old",
                created_at=now - timedelta(hours=1),
            ),
            FeedbackEntry(
                id="f2",
                content="newer feedback",
                contact="me@example.com",
                user_id="u9",
                session_id="s-new",
                created_at=now,
            ),
        ]
    )


def _admin_user_store(admin_id: str) -> InMemoryUserStore:
    store = InMemoryUserStore()
    store.admin_ids.add(admin_id)
    return store


async def test_admin_can_read_feedback() -> None:
    reader = _reader_with_two_entries()
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "admin-session", role="user", user_id="admin-1"
    )
    app.dependency_overrides[get_user_store] = lambda: _admin_user_store("admin-1")
    app.dependency_overrides[get_feedback_reader] = lambda: reader
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/feedback")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    # Newest first.
    assert [item["id"] for item in body["items"]] == ["f2", "f1"]
    assert body["items"][0]["content"] == "newer feedback"


async def test_non_admin_user_is_denied() -> None:
    reader = _reader_with_two_entries()
    # A logged-in user who is NOT in admin_ids.
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "user-session", role="user", user_id="u1"
    )
    app.dependency_overrides[get_user_store] = InMemoryUserStore
    app.dependency_overrides[get_feedback_reader] = lambda: reader
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/feedback")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_guest_is_denied() -> None:
    reader = _reader_with_two_entries()
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "guest-session", role="guest"
    )
    app.dependency_overrides[get_user_store] = InMemoryUserStore
    app.dependency_overrides[get_feedback_reader] = lambda: reader
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/feedback")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_unauthenticated_is_denied() -> None:
    # No Authorization header, no override, and no query-string secret grants access.
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/feedback")
        # A leftover-style v1 shared-secret query param must not authenticate either.
        response_with_key = await client.get("/api/feedback?key=some-token")

    assert response.status_code == 401
    assert response_with_key.status_code == 401


async def test_limit_is_passed_through_and_validated() -> None:
    reader = _reader_with_two_entries()
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "admin-session", role="user", user_id="admin-1"
    )
    app.dependency_overrides[get_user_store] = lambda: _admin_user_store("admin-1")
    app.dependency_overrides[get_feedback_reader] = lambda: reader
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            limited = await client.get("/api/feedback?limit=1")
            too_big = await client.get("/api/feedback?limit=5000")
    finally:
        app.dependency_overrides.clear()

    assert limited.status_code == 200
    assert limited.json()["count"] == 1
    # Out-of-range limit is rejected by query validation (le=1000).
    assert too_big.status_code == 422
