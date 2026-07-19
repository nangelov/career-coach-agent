"""API tests for the per-message feedback endpoint (P9-01, §5.5 / §9).

Drives the real router (``POST /api/messages/{message_id}/feedback``) with a stand-in
authenticated caller (``require_auth`` override) and an in-memory
:class:`~app.services.message_feedback.InMemoryMessageFeedbackStore`
(``get_message_feedback_store`` override) seeded with message ownership — so no Postgres /
Redis wiring runs. Asserts the capture contract:

* a user can thumbs-up **and** thumbs-down their own message (``200``);
* resubmitting flips the rating on the *same* row (idempotent — no duplicate);
* feedback on an unknown message is a ``404``;
* feedback on a message the caller does not own is a ``404`` (never distinguished from unknown);
* a guest can rate a message owned by their session (``200``);
* an unauthenticated request is a ``401``;
* an invalid rating is rejected by body validation (``422``).
"""

from __future__ import annotations

import httpx
from httpx import ASGITransport

from app.api.message_feedback import get_message_feedback_store
from app.main import app
from app.security.dependencies import require_auth
from app.services.message_feedback import InMemoryMessageFeedbackStore, MessageOwner
from tests.fakes import fake_current_user

_USER_ID = "11111111-1111-1111-1111-111111111111"
_USER_SESSION = "user-session"
_USER_MESSAGE = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_GUEST_SESSION = "guest-session"
_GUEST_MESSAGE = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _seeded_store() -> InMemoryMessageFeedbackStore:
    """A store: ``_USER_MESSAGE`` owned by the logged-in user, ``_GUEST_MESSAGE`` by a guest."""
    return InMemoryMessageFeedbackStore(
        {
            _USER_MESSAGE: MessageOwner(user_id=_USER_ID, session_id=_USER_SESSION),
            _GUEST_MESSAGE: MessageOwner(user_id=None, session_id=_GUEST_SESSION),
        }
    )


async def _post(message_id: str, body: dict[str, object]) -> httpx.Response:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/api/messages/{message_id}/feedback", json=body)


async def test_user_can_thumbs_up_and_down_own_message() -> None:
    store = _seeded_store()
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        _USER_SESSION, role="user", user_id=_USER_ID
    )
    app.dependency_overrides[get_message_feedback_store] = lambda: store
    try:
        up = await _post(_USER_MESSAGE, {"rating": "up"})
        down = await _post(_USER_MESSAGE, {"rating": "down", "reason": "off topic"})
    finally:
        app.dependency_overrides.clear()

    assert up.status_code == 200
    assert up.json()["rating"] == "up"
    assert up.json()["message_id"] == _USER_MESSAGE

    # Resubmission flips the same row (idempotent), and the reason is stored.
    assert down.status_code == 200
    assert down.json()["rating"] == "down"
    assert down.json()["reason"] == "off topic"
    stored = await store.get_for_message(_USER_MESSAGE)
    assert stored is not None and stored.rating == "down"
    # Exactly one down-vote for the user — the up-vote was replaced, not duplicated.
    downvotes = await store.list_recent_downvotes(_USER_ID, limit=10)
    assert [d.message_id for d in downvotes] == [_USER_MESSAGE]


async def test_feedback_on_unknown_message_is_404() -> None:
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        _USER_SESSION, role="user", user_id=_USER_ID
    )
    app.dependency_overrides[get_message_feedback_store] = _seeded_store
    try:
        response = await _post("ffffffffffffffffffffffffffffffff", {"rating": "up"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


async def test_feedback_on_other_users_message_is_404() -> None:
    # A different logged-in user tries to rate _USER_MESSAGE (owned by _USER_ID).
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "other-session", role="user", user_id="22222222-2222-2222-2222-222222222222"
    )
    app.dependency_overrides[get_message_feedback_store] = _seeded_store
    try:
        response = await _post(_USER_MESSAGE, {"rating": "down", "reason": "not mine"})
    finally:
        app.dependency_overrides.clear()
    # Not-owned is indistinguishable from unknown — no ownership leak.
    assert response.status_code == 404


async def test_guest_can_rate_own_session_message() -> None:
    app.dependency_overrides[require_auth] = lambda: fake_current_user(_GUEST_SESSION, role="guest")
    app.dependency_overrides[get_message_feedback_store] = _seeded_store
    try:
        response = await _post(_GUEST_MESSAGE, {"rating": "up"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["rating"] == "up"


async def test_guest_cannot_rate_other_sessions_message() -> None:
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "some-other-guest", role="guest"
    )
    app.dependency_overrides[get_message_feedback_store] = _seeded_store
    try:
        response = await _post(_GUEST_MESSAGE, {"rating": "up"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


async def test_unauthenticated_is_denied() -> None:
    response = await _post(_USER_MESSAGE, {"rating": "up"})
    assert response.status_code == 401


async def test_invalid_rating_is_rejected() -> None:
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        _USER_SESSION, role="user", user_id=_USER_ID
    )
    app.dependency_overrides[get_message_feedback_store] = _seeded_store
    try:
        response = await _post(_USER_MESSAGE, {"rating": "sideways"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
