"""Observability — OpenTelemetry tracing + Sentry error tracking + PII redaction (P11).

Public surface for the app's instrumentation. See :mod:`app.observability.tracing`
(OTel setup + graph-node/turn/task span helpers, §6.26 / §7.8), :mod:`app.observability.redaction`
(the PII-redacting span exporter, §7.6), and :mod:`app.observability.sentry` (Sentry error
tracking with PII scrubbing, §6.24 / §7.7). Everything is default-off and fail-soft — importing
this package has no side effects and adds no overhead until :func:`configure_tracing` /
:func:`configure_sentry` runs.
"""

from __future__ import annotations

from app.observability.redaction import RedactingSpanExporter, redact_attributes
from app.observability.sentry import configure_sentry, scrub_event
from app.observability.tracing import (
    build_tracer_provider,
    configure_tracing,
    get_tracer,
    instrument_celery,
    instrument_fastapi,
    trace_async_iter,
    traced_node,
)

__all__ = [
    "RedactingSpanExporter",
    "build_tracer_provider",
    "configure_sentry",
    "configure_tracing",
    "get_tracer",
    "instrument_celery",
    "instrument_fastapi",
    "redact_attributes",
    "scrub_event",
    "trace_async_iter",
    "traced_node",
]
