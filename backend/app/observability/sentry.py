"""Sentry error tracking + PII scrubbing (design §6.24 / §7.7, S15).

A **free-tier, low-noise error-alerting channel** — nothing more. Sentry is the app's
"something threw an unhandled exception in production" notifier (§7.7); it is deliberately
**not** an APM/tracing tool (that is OTel's job, §7.8 / :mod:`app.observability.tracing`) and
**not** an on-call/incident-response programme (§7.7 rules that out for a free-tier project).

**Default-off, fail-soft** — mirrors the OTel posture. Sentry is a complete no-op unless a
``SENTRY_DSN`` is configured, so local dev, CI and unit tests never talk to Sentry and need no
DSN. The whole ``sentry_sdk`` import is additionally guarded, so a runtime missing the SDK
degrades to a no-op instead of failing. ``SENTRY_TRACES_SAMPLE_RATE`` defaults to ``0`` — this
is an *error* tool; we do not double-pay for APM spans Sentry-side.

**PII scrubbing is ON (§6.24 / §7.6 / §7.7).** ``send_default_pii=False`` is set explicitly (so
the SDK never attaches the client IP, cookies, or request body by default), and every event is
additionally run through :func:`scrub_event` via the ``before_send`` /
``before_send_transaction`` hooks — the two-layer guarantee mirroring the OTel
:class:`~app.observability.redaction.RedactingSpanExporter`:

1. **Drop raw content wholesale** — the request **body** (``request.data``), **query string**
   and **cookies** are removed entirely (a POST body is exactly where chat message content / CV
   text would leak), sensitive **headers** (``Authorization`` / ``Cookie`` / API-key / CSRF /
   auth-token) are stripped, and user-identifying fields (``email`` / ``username`` /
   ``ip_address`` / ``name``) are dropped from ``event.user`` (only an opaque ``id`` may remain).
2. **Redact residual contact PII** — every remaining string value in the event is passed through
   the **same** deterministic egress redactor used at the LLM boundary
   (:func:`app.llm.redaction.redact_contact_details`, reused — not re-implemented — per the task
   / §7.6), so an email / phone / URL / address / name that slipped into an exception message,
   breadcrumb, or ``extra`` value is neutralised before the event leaves the process.

If scrubbing ever raises, the hook **fails closed** — the event is dropped rather than risk
sending un-scrubbed PII.

**Low-noise alert rule.** Sentry's out-of-the-box behaviour is "email on every new issue", which
floods a free-tier inbox. That is dashboard config (not app-enforceable code) — see the
``docs/sentry-alerting.md`` runbook for the exact issue-alert settings to configure once against
the real project (e.g. "only unhandled errors, seen ≥N times in M minutes").
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from app.llm.redaction import redact_contact_details

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard; a runtime without the SDK degrades to a no-op
    import sentry_sdk

    _SENTRY_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure degrades Sentry to a no-op
    _SENTRY_AVAILABLE = False

if TYPE_CHECKING:
    from sentry_sdk.types import Event as SentryEvent
    from sentry_sdk.types import Hint as SentryHint

    from app.config import Settings

__all__ = ["configure_sentry", "scrub_event"]

#: A Sentry event / hint are loosely-typed JSON-ish dicts. :func:`scrub_event` is kept
#: framework-agnostic (plain ``dict``) so it is unit-testable without the SDK's TypedDicts;
#: the two thin ``before_send*`` hooks bridge to Sentry's own ``Event``/``Hint`` types.
Event = dict[str, Any]
Hint = dict[str, Any]

#: Header / mapping keys whose **value** is a credential or session token — dropped wholesale
#: (replaced with a marker) wherever they appear in an event. Matched case-insensitively against
#: the exact key name. Kept narrow (credential nouns only) so useful structural keys survive.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "cookies",
        "set-cookie",
        "x-api-key",
        "api-key",
        "apikey",
        "x-auth-token",
        "x-csrf-token",
        "csrftoken",
        "password",
        "token",
        "secret",
        "access_token",
        "refresh_token",
        "session",
        "sessionid",
    }
)

#: ``event.request`` sub-keys removed entirely: the body (``data``) is where chat message / CV
#: text would leak; ``query_string`` can carry OAuth codes / ``?token=`` secrets; ``cookies``
#: carries the session. None are needed to triage an error, so drop them wholesale.
_DROP_REQUEST_KEYS: tuple[str, ...] = ("data", "query_string", "cookies")

#: ``event.user`` fields dropped (``send_default_pii=False`` already suppresses most, but a
#: call site could set them explicitly). An opaque ``id`` may remain to correlate issues.
_USER_PII_KEYS: tuple[str, ...] = ("email", "username", "ip_address", "name")

#: Marker left in place of a dropped credential value (auditable, mirrors the egress redactor).
_REDACTED = "[REDACTED]"


def _scrub_request(request: dict[str, Any]) -> None:
    """Strip the request body / query string / cookies and sensitive headers, in place."""
    for key in _DROP_REQUEST_KEYS:
        request.pop(key, None)
    headers = request.get("headers")
    if isinstance(headers, dict):
        request["headers"] = {
            key: value for key, value in headers.items() if key.lower() not in _SENSITIVE_KEYS
        }


def _redact_in_place(obj: Any) -> Any:
    """Recursively drop credential-keyed values and redact contact PII from every string.

    Walks the event's nested dict/list structure: a key naming a credential is replaced with
    ``[REDACTED]``; any other string value is passed through the deterministic egress redactor
    so residual email / phone / URL / address / name PII is neutralised. Non-string scalars
    (bool/int/float/None) carry no free-text PII and are returned unchanged.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                obj[key] = _REDACTED
            else:
                obj[key] = _redact_in_place(value)
        return obj
    if isinstance(obj, list):
        return [_redact_in_place(item) for item in obj]
    if isinstance(obj, str):
        return redact_contact_details(obj)
    return obj


def scrub_event(event: Event, hint: Hint | None = None) -> Event:
    """Return ``event`` with body / credentials / user PII stripped and contact PII redacted.

    The concrete implementation of §6.24's "PII scrubbing on": drops the raw request body /
    query string / cookies and sensitive headers, drops user-identifying fields, then redacts
    residual contact-detail PII from every remaining string (reusing the LLM egress redactor).
    Mutates and returns the same event dict (the ``before_send`` contract). ``hint`` is unused
    but part of the SDK signature.
    """
    request = event.get("request")
    if isinstance(request, dict):
        _scrub_request(request)
    user = event.get("user")
    if isinstance(user, dict):
        for key in _USER_PII_KEYS:
            user.pop(key, None)
    _redact_in_place(event)
    return event


def _before_send(event: SentryEvent, hint: SentryHint) -> SentryEvent | None:
    """``before_send`` hook: scrub every error event, failing closed (drop) on error."""
    try:
        scrubbed = scrub_event(cast(Event, event), hint)
    except Exception:  # noqa: BLE001 - a scrub failure must drop the event, never leak un-scrubbed PII
        logger.warning("sentry event scrub failed; dropping event to avoid PII leak", exc_info=True)
        return None
    return cast("SentryEvent", scrubbed)


def _before_send_transaction(event: SentryEvent, hint: SentryHint) -> SentryEvent | None:
    """``before_send_transaction`` hook: same scrubbing for sampled traces (fails closed)."""
    try:
        scrubbed = scrub_event(cast(Event, event), hint)
    except Exception:  # noqa: BLE001 - fail closed on a scrub failure
        logger.warning(
            "sentry transaction scrub failed; dropping event to avoid PII leak", exc_info=True
        )
        return None
    return cast("SentryEvent", scrubbed)


def _build_integrations() -> list[Any]:
    """Build the FastAPI + (optional) Celery integrations, each guarded/fail-soft.

    Both integration classes ship inside ``sentry_sdk`` itself (no extra package). They are
    imported lazily here so a partial install still initialises Sentry with whatever is present.
    """
    integrations: list[Any] = []
    try:
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        integrations.append(FastApiIntegration())
    except Exception:  # noqa: BLE001 - missing FastAPI integration must not block Sentry init
        logger.warning("Sentry FastAPI integration unavailable", exc_info=True)
    try:
        from sentry_sdk.integrations.celery import CeleryIntegration

        integrations.append(CeleryIntegration())
    except Exception:  # noqa: BLE001 - Celery integration is optional (web dyno has no Celery)
        logger.debug("Sentry Celery integration unavailable", exc_info=True)
    return integrations


def configure_sentry(settings: Settings) -> bool:
    """Initialise the Sentry SDK from settings (default no-op). Returns whether it was enabled.

    A complete no-op unless a ``SENTRY_DSN`` is configured (and the SDK is importable) — so
    CI / tests / local dev never touch Sentry. When a DSN is set it initialises the SDK with
    ``send_default_pii=False`` and the scrubbing ``before_send`` / ``before_send_transaction``
    hooks (§6.24 / §7.6), a low/zero ``traces_sample_rate`` (errors, not APM), and the FastAPI +
    Celery integrations. Safe to call from both the FastAPI app factory and each Celery worker's
    post-fork init.
    """
    if not _SENTRY_AVAILABLE or not settings.SENTRY_DSN.strip():
        return False
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT or None,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        # Never let the SDK attach the client IP, cookies, or request body automatically —
        # our before_send additionally scrubs, but this is the primary switch (§6.24 / §7.6).
        send_default_pii=False,
        # Stack-frame locals routinely hold chat/CV free text (e.g. `messages`, `content`, CV
        # strings) the contact-only redactor can't recognise — never attach them (§6.24 / §7.6).
        include_local_variables=False,
        # Defence-in-depth: the request body is where chat/CV text and OAuth codes live.
        max_request_body_size="never",
        before_send=_before_send,
        before_send_transaction=_before_send_transaction,
        integrations=_build_integrations(),
    )
    logger.info("Sentry error tracking enabled (environment=%s)", settings.SENTRY_ENVIRONMENT)
    return True
