"""Tests for Sentry error tracking + PII scrubbing (P11-02, design §6.24 / §7.6 / §7.7).

Covers the acceptance-critical behaviours without ever hitting a live Sentry DSN:

* **Default-off** — with ``SENTRY_DSN`` unset, :func:`configure_sentry` is a complete no-op
  (returns ``False``, never calls ``sentry_sdk.init``).
* **Init contract** — with a DSN set it initialises the SDK with ``send_default_pii=False``,
  the scrubbing ``before_send`` / ``before_send_transaction`` hooks, and the configured
  (default-0) traces sample rate. The transport is mocked (``sentry_sdk.init`` patched).
* **PII scrubbing** — :func:`scrub_event` (the ``before_send`` body) drops the request body /
  query string / cookies and sensitive headers, drops user-identifying fields, and redacts
  residual contact PII (email / phone / URL) from every remaining string, so known PII markers
  never survive into an event. The hook **fails closed** (drops the event) if scrubbing raises.
* **Debug endpoint** — ``GET /api/_debug/sentry-test`` is admin-gated (``401`` / ``403`` /
  ``500`` matrix) so an operator can verify delivery without a public error-spam vector.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from app.api.debug import SentryTestError
from app.main import app
from app.observability import configure_sentry, scrub_event
from app.observability import sentry as sentry_module
from app.schemas.auth import CurrentUser
from app.security.dependencies import get_user_store, require_auth
from app.services.user_store import InMemoryUserStore
from tests.fakes import fake_current_user


def _settings(dsn: str = "", environment: str = "", sample_rate: float = 0.0) -> Any:
    """A minimal settings stand-in with only the Sentry fields configure_sentry reads."""
    return SimpleNamespace(
        SENTRY_DSN=dsn,
        SENTRY_ENVIRONMENT=environment,
        SENTRY_TRACES_SAMPLE_RATE=sample_rate,
    )


# --------------------------------------------------------------------------- #
# configure_sentry — default-off + init contract.                             #
# --------------------------------------------------------------------------- #
def test_configure_sentry_noop_when_dsn_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_module, "_SENTRY_AVAILABLE", True)
    monkeypatch.setattr(sentry_module.sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    enabled = configure_sentry(_settings(dsn=""))

    assert enabled is False
    assert calls == []  # zero Sentry calls when no DSN is configured


def test_configure_sentry_noop_when_sdk_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sentry_module, "_SENTRY_AVAILABLE", False)
    # Even with a DSN, an unavailable SDK degrades to a no-op (no import error / crash).
    assert configure_sentry(_settings(dsn="https://k@o.ingest.sentry.io/1")) is False


def test_configure_sentry_sets_pii_off_and_scrub_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(sentry_module, "_SENTRY_AVAILABLE", True)
    monkeypatch.setattr(sentry_module.sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))

    enabled = configure_sentry(
        _settings(dsn="https://k@o.ingest.sentry.io/1", environment="production", sample_rate=0.0)
    )

    assert enabled is True
    # send_default_pii MUST be explicitly False (§6.24 acceptance criterion).
    assert captured["send_default_pii"] is False
    # Stack-frame locals hold chat/CV free text the contact-only redactor can't scrub: never attach.
    assert captured["include_local_variables"] is False
    # Defence-in-depth: request body (chat/CV text, OAuth codes) is never captured.
    assert captured["max_request_body_size"] == "never"
    # Scrubbing hooks wired for both errors and (sampled) transactions.
    assert captured["before_send"] is sentry_module._before_send
    assert captured["before_send_transaction"] is sentry_module._before_send_transaction
    # Errors, not APM: default sample rate is 0 so we don't double-pay for Sentry traces.
    assert captured["traces_sample_rate"] == 0.0
    assert captured["environment"] == "production"
    assert captured["dsn"] == "https://k@o.ingest.sentry.io/1"


# --------------------------------------------------------------------------- #
# scrub_event — PII scrubbing.                                                 #
# --------------------------------------------------------------------------- #
def _pii_event() -> dict[str, Any]:
    """A synthetic Sentry event loaded with every PII shape scrubbing must remove."""
    return {
        "level": "error",
        "request": {
            "url": "http://test/api/chat",
            "method": "POST",
            "data": "chat message: please review my CV, I am reachable at me@secret.example",
            "query_string": "code=oauth_secret_code&state=csrf_token",
            "cookies": {"session": "sess-abc123"},
            "headers": {
                "Authorization": "Bearer super-secret-token",
                "Cookie": "session=sess-abc123",
                "User-Agent": "pytest",
                "Referer": "http://example.com/profile",
            },
        },
        "user": {
            "id": "u-opaque-1",
            "email": "victim@example.com",
            "username": "victim",
            "ip_address": "203.0.113.7",
        },
        "message": "Turn failed for victim@example.com — call +1 (555) 123-4567",
        "exception": {
            "values": [
                {"type": "ValueError", "value": "leaked CV text; contact jane.doe@corp.example"}
            ]
        },
        "extra": {"note": "user email john@doe.example in extra context"},
        "breadcrumbs": {"values": [{"message": "emailed a.b@c.example"}]},
    }


def test_scrub_event_drops_body_cookies_query_and_sensitive_headers() -> None:
    event = scrub_event(_pii_event())

    request = event["request"]
    # Raw body / query string / cookies removed wholesale (chat/CV text, OAuth code, session).
    assert "data" not in request
    assert "query_string" not in request
    assert "cookies" not in request
    # Sensitive headers stripped; benign headers survive (Referer value later redacted).
    headers = request["headers"]
    assert "Authorization" not in headers
    assert "Cookie" not in headers
    assert headers["User-Agent"] == "pytest"


def test_scrub_event_drops_user_pii_but_keeps_opaque_id() -> None:
    event = scrub_event(_pii_event())

    user = event["user"]
    assert user["id"] == "u-opaque-1"  # opaque correlation id may remain
    assert "email" not in user
    assert "username" not in user
    assert "ip_address" not in user


def test_scrub_event_redacts_residual_contact_pii_everywhere() -> None:
    event = scrub_event(_pii_event())
    blob = json.dumps(event)

    # No email / phone / secret / raw referer host survives anywhere in the event.
    for leaked in (
        "victim@example.com",
        "jane.doe@corp.example",
        "john@doe.example",
        "a.b@c.example",
        "me@secret.example",
        "super-secret-token",
        "oauth_secret_code",
        "sess-abc123",
        "203.0.113.7",
    ):
        assert leaked not in blob, f"PII marker leaked into event: {leaked}"
    # Redaction markers prove the reused egress redactor ran on free text.
    assert "[EMAIL REDACTED]" in event["message"]
    assert "[PHONE REDACTED]" in event["message"]
    assert "[EMAIL REDACTED]" in event["exception"]["values"][0]["value"]


def test_scrub_event_tolerates_minimal_event() -> None:
    # No request / user keys — must not raise and must return the (redacted) event.
    event = scrub_event({"level": "error", "message": "boom, reach me@x.example"})
    assert "[EMAIL REDACTED]" in event["message"]


def test_before_send_fails_closed_on_scrub_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_event: dict[str, Any], _hint: Any = None) -> dict[str, Any]:
        raise RuntimeError("scrub blew up")

    monkeypatch.setattr(sentry_module, "scrub_event", _boom)
    # A scrub failure must DROP the event (return None), never send it un-scrubbed.
    assert sentry_module._before_send({"message": "x"}, {}) is None
    assert sentry_module._before_send_transaction({"message": "x"}, {}) is None


# --------------------------------------------------------------------------- #
# Debug endpoint — admin-gated Sentry-test trigger.                           #
# --------------------------------------------------------------------------- #
def _admin_store(admin_id: str) -> InMemoryUserStore:
    store = InMemoryUserStore()
    store.admin_ids.add(admin_id)
    return store


async def test_sentry_test_endpoint_admin_raises_unhandled_error() -> None:
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "admin-session", role="user", user_id="admin-1"
    )
    app.dependency_overrides[get_user_store] = lambda: _admin_store("admin-1")
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # The admin path raises an UNHANDLED exception — exactly what the Sentry FastAPI
            # integration captures. httpx's ASGITransport re-propagates it (Starlette's
            # ServerErrorMiddleware emits the 500 and re-raises), so we assert the raise itself.
            with pytest.raises(SentryTestError):
                await client.get("/api/_debug/sentry-test")
    finally:
        app.dependency_overrides.clear()


async def test_sentry_test_endpoint_non_admin_is_denied() -> None:
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "user-session", role="user", user_id="u1"
    )
    app.dependency_overrides[get_user_store] = InMemoryUserStore
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/_debug/sentry-test")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_sentry_test_endpoint_unauthenticated_is_denied() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/_debug/sentry-test")

    assert response.status_code == 401


def test_sentry_test_error_is_a_runtime_error() -> None:
    # The deliberate error type is a plain RuntimeError subclass (benign, greppable in Sentry).
    assert issubclass(SentryTestError, RuntimeError)


def test_current_user_type_importable() -> None:
    # Guard the debug router's schema import stays wired (Router→Service layering).
    assert CurrentUser is not None
