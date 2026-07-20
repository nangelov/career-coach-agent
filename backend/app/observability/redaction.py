"""PII redaction for exported OpenTelemetry spans (design §7.6 / §7.8, S11).

Traces would otherwise carry the most sensitive data the app holds — full CV text,
every chat message, and contact-detail PII — straight to a third-party OTLP backend.
§7.6 is explicit that "logs & traces otherwise contain full CV text and every message"
and must be **PII-redacted before they leave the process**. This module is that
last-line-of-defense chokepoint.

Two layers protect a span:

1. **At the source** — the app's own instrumentation (:mod:`app.observability.tracing`
   node wrappers, the chat-turn span, Celery task spans) only ever sets *minimal, safe*
   attributes (node name, plan intent, worker/citation counts, booleans) — never raw
   message/CV content. This is the primary guarantee.
2. **Defense in depth (this module)** — a :class:`RedactingSpanExporter` wraps whatever
   real exporter is configured and scrubs **every** span just before export, regardless of
   who set the attribute (FastAPI auto-instrumentation, a future careless call site, a URL
   query param, an exception event). It (a) **drops** any attribute whose key names a
   content/PII field (including request-query keys such as ``url.query``), (b) **strips the
   query string** off request-URL keys (``http.target`` / ``http.url`` / ``url.full`` /
   ``url.path``) — ASGI/FastAPI instrumentation records these as *scheme-less* ``path?query``
   strings, so an OAuth callback like ``/api/auth/callback?code=<authcode>&state=<token>``
   would otherwise slip past a URL-pattern redactor and leak an authorization code / bearer
   token — and (c) runs every remaining string value through the existing deterministic
   contact-detail redactor (:func:`app.llm.redaction.redact_contact_details`, the same one
   used at the LLM egress boundary — reused, not re-implemented, per §7.6).

Deterministic, no I/O, no ML — the same coarse-but-cheap posture as the egress redactor.
Retention is enforced by the OTLP backend's own retention window (free-tier default), not
in-app; see the tracing module docstring.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from app.llm.redaction import redact_contact_details

if TYPE_CHECKING:
    from opentelemetry.util.types import AttributeValue

logger = logging.getLogger(__name__)

__all__ = ["RedactingSpanExporter", "redact_attributes"]

#: Attribute keys whose *value* is content or direct PII and must never be exported at all.
#: Matched as a case-insensitive substring of the key, so ``http.request.body`` /
#: ``llm.prompt`` / ``user_message`` are all caught. Kept deliberately narrow (content-bearing
#: nouns only) so useful structural keys — ``graph.node``, ``plan.intent``, ``http.route`` — are
#: never accidentally dropped; residual PII in *allowed* keys is still scrubbed by value below.
_SENSITIVE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "message",
    "content",
    "prompt",
    "completion",
    "answer",
    "cv",
    "resume",
    "document",
    "user_text",
    "assistant_text",
    "request.body",
    "response.body",
    "payload",
    # A request query string is pure attacker/user-controlled data (OAuth ``code``/``state``,
    # ``?token=`` secrets, search terms) — never structural — so drop it wholesale.
    "query",
)

#: Attribute keys whose *value* is a request URL/target that may **embed** a query string.
#: ASGI/FastAPI instrumentation records these as *scheme-less* ``path?query`` values, which the
#: value-level contact redactor (it requires an ``http(s)://`` / ``www.`` scheme) can't see — so
#: strip everything from the first ``?`` here, dropping OAuth codes / bearer tokens with it while
#: keeping the useful path/route for latency-by-endpoint analysis.
_URL_KEY_SUBSTRINGS: tuple[str, ...] = ("http.target", "http.url", "url.full", "url.path")


def _is_sensitive_key(key: str) -> bool:
    """Whether an attribute key names a content/PII field that must be dropped entirely."""
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_SUBSTRINGS)


def _is_url_key(key: str) -> bool:
    """Whether an attribute key holds a request URL/target whose query string must be stripped."""
    lowered = key.lower()
    return any(marker in lowered for marker in _URL_KEY_SUBSTRINGS)


def _strip_query_string(value: AttributeValue) -> AttributeValue:
    """Drop the ``?query`` (and ``#fragment``) tail off a scheme-less-or-not URL string value."""
    if not isinstance(value, str):
        return value
    for separator in ("?", "#"):
        index = value.find(separator)
        if index != -1:
            value = value[:index]
    return value


def _redact_value(value: AttributeValue) -> AttributeValue:
    """Scrub contact-detail PII from a string (or string-sequence) attribute value.

    Non-string scalars (bool/int/float) and their sequences carry no free-text PII and are
    returned unchanged. String values pass through the deterministic egress redactor so an
    email / phone / (schemed) URL / address / name that slipped into an allowed key is
    neutralised. Note this redactor requires a URL *scheme* to match a URL — scheme-less
    request-URL/query values are handled separately by the key-based drop/strip in
    :func:`redact_attributes`.
    """
    if isinstance(value, str):
        return redact_contact_details(value)
    if isinstance(value, (bytes, bytearray)):
        return value
    # OTel attribute sequences are homogeneous; only a string sequence can carry free-text PII.
    if isinstance(value, Sequence):
        str_items = [item for item in value if isinstance(item, str)]
        if len(str_items) == len(value):
            return [redact_contact_details(item) for item in str_items]
    return value


def redact_attributes(
    attributes: Mapping[str, AttributeValue] | None,
) -> dict[str, AttributeValue]:
    """Return a redacted copy of a span/event attribute mapping.

    Drops sensitive-keyed attributes wholesale and scrubs contact-detail PII from every
    remaining string value. Pure and deterministic.
    """
    if not attributes:
        return {}
    redacted: dict[str, AttributeValue] = {}
    for key, value in attributes.items():
        if _is_sensitive_key(key):
            continue
        clean = _redact_value(value)
        if _is_url_key(key):
            clean = _strip_query_string(clean)
        redacted[key] = clean
    return redacted


def _redact_event(event: Event) -> Event:
    """Return a copy of a span event with its attributes redacted (exception events included)."""
    return Event(
        name=event.name,
        attributes=redact_attributes(event.attributes),
        timestamp=event.timestamp,
    )


def _redact_span(span: ReadableSpan) -> ReadableSpan:
    """Rebuild a :class:`ReadableSpan` with redacted attributes + events.

    Span attributes are immutable once ended, so a fresh read-only span is constructed
    copying every structural field (context/parent/timings/status/kind/scope) verbatim and
    substituting the scrubbed attribute + event sets. The span *name* is left intact — names
    are route templates / node constants the app controls, never user content.
    """
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=redact_attributes(span.attributes),
        events=[_redact_event(event) for event in span.events],
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingSpanExporter(SpanExporter):
    """A :class:`SpanExporter` decorator that redacts PII before delegating export (§7.6).

    Wraps the real exporter (OTLP, console, or a test in-memory exporter) and scrubs every
    span through :func:`_redact_span` on the way out, so no message content, CV text, or
    contact-detail PII ever reaches the wire — the concrete implementation of §7.6's
    "PII-redacted traces" obligation. ``force_flush`` / ``shutdown`` pass straight through.
    """

    def __init__(self, delegate: SpanExporter) -> None:
        self._delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            redacted = [_redact_span(span) for span in spans]
        except Exception:  # noqa: BLE001 - a redaction failure must fail closed (drop), never leak
            logger.warning("span redaction failed; dropping batch to avoid PII leak", exc_info=True)
            return SpanExportResult.FAILURE
        return self._delegate.export(redacted)

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._delegate.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self._delegate.shutdown()
