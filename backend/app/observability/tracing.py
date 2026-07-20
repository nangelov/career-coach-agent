"""OpenTelemetry tracing setup + graph-node instrumentation (design §6.26 / §7.8, P11).

Vendor-neutral OTel traces across the three surfaces §7.8 names — FastAPI (auto), the
LangGraph node graph (planner / workers / responder), and Celery tasks — exported via a
plain **OTLP/HTTP** exporter to a free-tier hosted backend of the owner's choice (Grafana
Cloud / Honeycomb / a local Collector). No vendor SDK: the backend is swappable and no
bespoke in-app dashboard is built (YAGNI — the OTLP backend's own UI is the dashboard).

**Default-off, fail-soft.** All setup is gated on ``settings.OTEL_ENABLED`` (default
``False``), so local dev, CI and unit tests run with a no-op global tracer — every
``get_tracer().start_as_current_span(...)`` becomes a cheap no-op and nothing is exported.
When enabled, an unset OTLP endpoint falls back to an opt-in console exporter or a pure
no-op, so a misconfigured deploy degrades rather than crashes. The whole OTel import is
additionally guarded so a runtime missing the SDK degrades to no-op instead of failing.

**PII redaction (§7.6, S11).** Every exporter is wrapped in a
:class:`~app.observability.redaction.RedactingSpanExporter`, and the node/turn/task
instrumentation here only ever sets *minimal, safe* attributes — never raw content. See
that module for the two-layer guarantee.

**Retention.** The retention limit §7.6 requires is the OTLP backend's own retention
window (free-tier default, no in-app plumbing) — this app only controls what leaves the
process (redaction) and where it goes (the exporter endpoint).
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace

    _OTEL_AVAILABLE = True
except Exception:  # noqa: BLE001 - a runtime without the OTel SDK degrades to a no-op
    _OTEL_AVAILABLE = False

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter
    from opentelemetry.trace import Span, Tracer

    from app.config import Settings

__all__ = [
    "build_tracer_provider",
    "configure_tracing",
    "get_tracer",
    "instrument_celery",
    "instrument_fastapi",
    "traced_node",
]

#: The tracer name every span in this app is created under (the instrumentation scope).
_TRACER_NAME = "career-coach-agent"

F = TypeVar("F", bound=Callable[..., Any])
T = TypeVar("T")


def get_tracer() -> Tracer:
    """Return the app tracer (a no-op tracer until :func:`configure_tracing` runs / if unset).

    Safe to call at import time and on the hot path: before a provider is installed OTel's
    global default is a proxy whose spans are no-ops, so instrumentation costs ~nothing when
    tracing is disabled.
    """
    return trace.get_tracer(_TRACER_NAME)


# --------------------------------------------------------------------------- #
# Provider / exporter construction.                                           #
# --------------------------------------------------------------------------- #
def build_tracer_provider(
    *,
    service_name: str,
    exporter: SpanExporter | None,
    simple: bool = False,
) -> TracerProvider:
    """Build a :class:`TracerProvider` whose exporter is PII-redacted (§7.6).

    ``exporter`` is wrapped in a :class:`~app.observability.redaction.RedactingSpanExporter`
    so nothing PII-bearing leaves the process. ``simple=True`` uses a synchronous
    ``SimpleSpanProcessor`` (spans exported inline — used by tests so an assertion sees them
    immediately); production uses a batched processor. A ``None`` exporter yields a provider
    with no export pipeline (spans are created but dropped) — the enabled-but-no-endpoint case.
    """
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    from app.observability.redaction import RedactingSpanExporter

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    if exporter is not None:
        redacting = RedactingSpanExporter(exporter)
        processor = SimpleSpanProcessor(redacting) if simple else BatchSpanProcessor(redacting)
        provider.add_span_processor(processor)
    return provider


def _parse_headers(raw: str) -> dict[str, str]:
    """Parse an OTLP header string ``"k1=v1,k2=v2"`` (the OTEL_EXPORTER_OTLP_HEADERS format)."""
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip()
        if key:
            headers[key] = value.strip()
    return headers


def _build_exporter(settings: Settings) -> SpanExporter | None:
    """Build the configured OTLP/HTTP exporter, or a console/no-op fallback.

    An OTLP endpoint (Grafana Cloud / Honeycomb / a local Collector) wins; the exporter is
    imported lazily here so its (heavier) transitive stack is pulled only when actually
    exporting. With no endpoint, ``OTEL_CONSOLE_EXPORT`` opts into a console dump (handy for
    local verification without any backend); otherwise ``None`` — spans are dropped.
    """
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT.strip()
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except Exception:  # noqa: BLE001 - missing OTLP extra degrades to no export, not a crash
            logger.warning("OTLP HTTP exporter unavailable; traces will not be exported")
            return None
        url = endpoint if endpoint.endswith("/v1/traces") else endpoint.rstrip("/") + "/v1/traces"
        headers = _parse_headers(settings.OTEL_EXPORTER_OTLP_HEADERS)
        return OTLPSpanExporter(endpoint=url, headers=headers or None)
    if settings.OTEL_CONSOLE_EXPORT:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    return None


def configure_tracing(settings: Settings) -> TracerProvider | None:
    """Install the global tracer provider from settings (idempotent-ish, default no-op).

    A no-op unless ``settings.OTEL_ENABLED`` — so CI/tests/local dev are untouched. When
    enabled it builds the redacting export pipeline and sets it as the OTel global provider
    (OTel ignores a second set, so the first caller — the FastAPI app factory or a Celery
    worker init — wins). Returns the provider (or ``None`` when disabled/unavailable) so a
    caller can register it for shutdown flushing.
    """
    if not _OTEL_AVAILABLE or not settings.OTEL_ENABLED:
        return None
    provider = build_tracer_provider(
        service_name=settings.OTEL_SERVICE_NAME,
        exporter=_build_exporter(settings),
    )
    trace.set_tracer_provider(provider)
    logger.info("OpenTelemetry tracing enabled (service=%s)", settings.OTEL_SERVICE_NAME)
    return provider


def instrument_fastapi(app: FastAPI, settings: Settings) -> None:
    """Auto-instrument a FastAPI app (HTTP request spans), gated + fail-soft."""
    if not _OTEL_AVAILABLE or not settings.OTEL_ENABLED:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:  # noqa: BLE001 - instrumentation must never block app startup
        logger.warning("FastAPI OTel instrumentation failed", exc_info=True)


def instrument_celery(settings: Settings) -> None:
    """Auto-instrument Celery (per-task spans + trace-context propagation), gated + fail-soft."""
    if not _OTEL_AVAILABLE or not settings.OTEL_ENABLED:
        return
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
    except Exception:  # noqa: BLE001 - instrumentation must never block worker startup
        logger.warning("Celery OTel instrumentation failed", exc_info=True)


# --------------------------------------------------------------------------- #
# Graph-node instrumentation.                                                 #
# --------------------------------------------------------------------------- #
def _set_node_start_attributes(span: Span, node: str, *, is_worker: bool) -> None:
    """Stamp the node identity on the span before it runs (safe even if the node raises).

    ``graph.node`` carries every node's identity; ``worker.name`` is set **only** for actual
    worker nodes (the ``WorkerName`` fan-out) so it isn't a misleading duplicate on the
    guardrail / recall / planner / responder / memory-writer spans.
    """
    span.set_attribute("graph.node", node)
    if is_worker:
        span.set_attribute("worker.name", node)


def _set_node_result_attributes(span: Span, result: Any) -> None:
    """Stamp *minimal, non-content* result signals — counts / intent / booleans only (§7.6).

    Deliberately never records message text, worker content, citation text, or memory: only
    the shape of the update (which intent, how many workers/citations, whether a worker
    errored) so a trace is useful for latency/flow debugging without becoming a PII sink.
    """
    if not isinstance(result, Mapping):
        return
    plan = result.get("plan")
    if plan is not None:
        intent = getattr(plan, "intent", None)
        if intent is not None:
            span.set_attribute("plan.intent", getattr(intent, "value", str(intent)))
        workers = getattr(plan, "workers", None)
        if workers is not None:
            span.set_attribute("plan.worker_count", len(workers))
    worker_results = result.get("worker_results")
    if isinstance(worker_results, Mapping):
        span.set_attribute("worker.result_count", len(worker_results))
        if any(getattr(wr, "error", None) for wr in worker_results.values()):
            span.set_attribute("worker.error", True)
    citations = result.get("citations")
    if isinstance(citations, list):
        span.set_attribute("citation.count", len(citations))


def _is_async_callable(fn: Callable[..., Any]) -> bool:
    """Whether ``fn`` (a plain function or a callable instance) runs asynchronously."""
    if inspect.iscoroutinefunction(fn):
        return True
    call = getattr(fn, "__call__", None)  # noqa: B004 - intentional __call__ probe for instances
    return inspect.iscoroutinefunction(call)


def traced_node(node: str, fn: F, *, is_worker: bool = False) -> F:
    """Wrap a LangGraph node callable so each invocation emits one child span (§7.8).

    The single generic helper ``build_graph`` applies to *every* ``add_node`` call, so a new
    worker automatically gets a span without touching this code again. Transparent: the
    wrapper returns exactly what the node returns and preserves its sync/async nature (so
    LangGraph's own ``iscoroutinefunction`` dispatch still sees the right shape). Spans are
    named ``graph.node.<name>`` and carry only minimal, redacted-safe attributes. ``is_worker``
    marks the ``WorkerName`` fan-out nodes so only they stamp ``worker.name``. When the OTel
    SDK is unavailable the node is returned unwrapped (zero overhead).
    """
    if not _OTEL_AVAILABLE:
        return fn

    span_name = f"graph.node.{node}"

    if _is_async_callable(fn):

        async def _async_wrapper(state: Any) -> Any:
            with get_tracer().start_as_current_span(span_name) as span:
                _set_node_start_attributes(span, node, is_worker=is_worker)
                result = await fn(state)
                _set_node_result_attributes(span, result)
                return result

        _copy_meta(_async_wrapper, fn)
        return cast(F, _async_wrapper)

    def _sync_wrapper(state: Any) -> Any:
        with get_tracer().start_as_current_span(span_name) as span:
            _set_node_start_attributes(span, node, is_worker=is_worker)
            result = fn(state)
            _set_node_result_attributes(span, result)
            return result

    _copy_meta(_sync_wrapper, fn)
    return cast(F, _sync_wrapper)


def _copy_meta(wrapper: Callable[..., Any], fn: Callable[..., Any]) -> None:
    """Best-effort copy of ``__name__``/``__doc__`` (skipped cleanly for callable instances)."""
    try:
        functools.update_wrapper(wrapper, fn)
    except (AttributeError, TypeError):  # callable instances have no __name__/__dict__ to copy
        pass


async def trace_async_iter(name: str, inner: AsyncIterator[T]) -> AsyncIterator[T]:
    """Yield from an async iterator inside a span (used to time responder token streaming).

    Kept a thin generator wrapper so the caller's ``aclose``/cancel semantics are preserved:
    closing the returned generator closes ``inner`` and ends the span.
    """
    with get_tracer().start_as_current_span(name):
        async for item in inner:
            yield item
