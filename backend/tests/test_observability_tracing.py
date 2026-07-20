"""Tests for OpenTelemetry tracing + span PII redaction (P11-01, design §6.26 / §7.6 / §7.8).

Covers the two acceptance-critical behaviours:

* **Span creation for the chat flow** — a full turn through the compiled multi-agent graph
  produces child spans for the planner, at least one worker, and the responder, all under the
  turn's ``graph.*`` root span (same trace).
* **PII redaction** — the :class:`RedactingSpanExporter` drops content-keyed attributes and
  scrubs contact-detail PII from every exported span, and a chat turn whose message carries an
  obvious PII marker never leaks that marker into any exported span attribute.

Tracing is default-off (``OTEL_ENABLED=False``) so the rest of the suite runs with a no-op
tracer; these tests install their own in-memory provider once (module-scoped) and clear the
exporter between tests.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanContext, TraceFlags

from app.agents.graph import build_graph, run_graph, stream_graph
from app.agents.state import AgentState, Intent, PlannerDecision, WorkerName
from app.observability import build_tracer_provider, get_tracer, redact_attributes
from app.observability.redaction import RedactingSpanExporter
from tests.fakes import FakeResponderRouter

PII_EMAIL = "leak@secret-domain.example"


def _planner_selecting(*workers: WorkerName) -> object:
    """A sync stub planner node routing to exactly ``workers`` (test seam)."""

    def planner(state: AgentState) -> dict[str, object]:
        return {"plan": PlannerDecision(intent=Intent.CHAT, workers=list(workers))}

    return planner


# --------------------------------------------------------------------------- #
# In-memory tracing provider (installed once for the module).                  #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    """Install a redacting, in-memory tracer provider as the global provider (once)."""
    exporter = InMemorySpanExporter()
    provider = build_tracer_provider(service_name="test", exporter=exporter, simple=True)
    # First real provider set in the session wins (OTel forbids overriding); the rest of the
    # suite never installs one because OTEL_ENABLED defaults False.
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture(autouse=True)
def _clear_spans(span_exporter: InMemorySpanExporter) -> None:
    span_exporter.clear()


def _span_names(exporter: InMemorySpanExporter) -> set[str]:
    return {span.name for span in exporter.get_finished_spans()}


def _all_attribute_values(exporter: InMemorySpanExporter) -> list[str]:
    values: list[str] = []
    for span in exporter.get_finished_spans():
        for value in (span.attributes or {}).values():
            values.append(str(value))
    return values


# --------------------------------------------------------------------------- #
# redact_attributes (pure function)                                            #
# --------------------------------------------------------------------------- #
def test_redact_attributes_drops_content_keys() -> None:
    """Content/PII-keyed attributes are dropped wholesale."""
    out = redact_attributes(
        {
            "graph.node": "planner",
            "user_message": "my secret question",
            "llm.prompt": "system prompt text",
            "http.request.body": "cv text",
        }
    )
    assert out == {"graph.node": "planner"}


def test_redact_attributes_scrubs_pii_in_allowed_keys() -> None:
    """Contact-detail PII in an allowed key's value is scrubbed, not dropped."""
    out = redact_attributes({"http.url": f"https://x/api?email={PII_EMAIL}"})
    assert "http.url" in out
    assert PII_EMAIL not in str(out["http.url"])
    # A *schemed* URL is caught by the value-level URL redactor before the query-strip runs.
    assert "REDACTED" in str(out["http.url"])


def test_redact_attributes_strips_scheme_less_query_secrets() -> None:
    """A scheme-less ``http.target`` OAuth callback never leaks its ``code``/``state`` secret."""
    out = redact_attributes(
        {"http.target": "/api/auth/callback?code=SECRET_AUTHCODE&state=SECRET_STATE"}
    )
    assert out["http.target"] == "/api/auth/callback"
    assert "SECRET_AUTHCODE" not in str(out["http.target"])
    assert "SECRET_STATE" not in str(out["http.target"])


def test_redact_attributes_drops_bare_query_attribute() -> None:
    """The ``url.query`` attribute (pure query string) is dropped wholesale."""
    out = redact_attributes({"url.path": "/api/auth/callback", "url.query": "code=SECRET&state=X"})
    assert out == {"url.path": "/api/auth/callback"}


# --------------------------------------------------------------------------- #
# RedactingSpanExporter (direct)                                               #
# --------------------------------------------------------------------------- #
def _make_span(attributes: dict[str, object]) -> ReadableSpan:
    ctx = SpanContext(
        trace_id=0x1,
        span_id=0x1,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return ReadableSpan(name="probe", context=ctx, attributes=attributes)


def test_redacting_exporter_scrubs_before_delegating() -> None:
    """The exporter redacts spans before the wrapped exporter ever sees them."""
    delegate = InMemorySpanExporter()
    exporter = RedactingSpanExporter(delegate)

    result = exporter.export(
        [_make_span({"graph.node": "responder", "answer": "sensitive", "http.target": PII_EMAIL})]
    )

    assert result is SpanExportResult.SUCCESS
    (exported,) = delegate.get_finished_spans()
    attrs = dict(exported.attributes or {})
    assert "answer" not in attrs  # content key dropped
    assert attrs["graph.node"] == "responder"  # structural key kept
    assert PII_EMAIL not in str(attrs["http.target"])  # PII value scrubbed


def test_redacting_exporter_passes_through_flush_and_shutdown() -> None:
    delegate = InMemorySpanExporter()
    exporter = RedactingSpanExporter(delegate)
    assert exporter.force_flush() is True
    exporter.shutdown()  # must not raise


# --------------------------------------------------------------------------- #
# Graph node span creation                                                     #
# --------------------------------------------------------------------------- #
async def test_graph_turn_produces_planner_worker_responder_spans(
    span_exporter: InMemorySpanExporter,
) -> None:
    """A full turn emits child spans for planner, a worker, and the responder."""
    compiled = build_graph(planner=_planner_selecting(WorkerName.PDP_RESUME))

    await compiled.ainvoke(AgentState(session_id="s", user_message="help me grow"))

    names = _span_names(span_exporter)
    assert "graph.node.planner" in names
    assert f"graph.node.{WorkerName.PDP_RESUME.value}" in names
    assert "graph.node.responder" in names


async def test_run_graph_roots_node_spans_in_one_trace(
    span_exporter: InMemorySpanExporter,
) -> None:
    """``run_graph`` opens a ``graph.run`` root and node spans share its trace id."""
    await run_graph(AgentState(session_id="s", user_message="hello"))

    spans = span_exporter.get_finished_spans()
    run_spans = [s for s in spans if s.name == "graph.run"]
    node_spans = [s for s in spans if s.name.startswith("graph.node.")]
    assert run_spans and node_spans
    trace_ids = {s.context.trace_id for s in spans if s.context is not None}
    assert len(trace_ids) == 1  # request → nodes all in one trace


async def test_node_span_carries_only_safe_attributes(
    span_exporter: InMemorySpanExporter,
) -> None:
    """The planner span records intent + worker count — never message content."""
    compiled = build_graph(planner=_planner_selecting(WorkerName.PDP_RESUME))

    await compiled.ainvoke(AgentState(session_id="s", user_message="grow my career"))

    planner_spans = [
        s for s in span_exporter.get_finished_spans() if s.name == "graph.node.planner"
    ]
    assert planner_spans
    attrs = dict(planner_spans[0].attributes or {})
    assert attrs.get("graph.node") == "planner"
    assert attrs.get("plan.intent") == Intent.CHAT.value
    assert attrs.get("plan.worker_count") == 1
    # ``worker.name`` is a worker-only attribute — it must not appear on the planner span.
    assert "worker.name" not in attrs


async def test_worker_span_stamps_worker_name_but_planner_does_not(
    span_exporter: InMemorySpanExporter,
) -> None:
    """Only ``WorkerName`` fan-out nodes carry ``worker.name``; others carry only graph.node."""
    compiled = build_graph(planner=_planner_selecting(WorkerName.PDP_RESUME))

    await compiled.ainvoke(AgentState(session_id="s", user_message="grow my career"))

    spans = {s.name: dict(s.attributes or {}) for s in span_exporter.get_finished_spans()}
    worker = spans[f"graph.node.{WorkerName.PDP_RESUME.value}"]
    assert worker.get("worker.name") == WorkerName.PDP_RESUME.value
    for non_worker in ("graph.node.responder", "graph.node.output_guardrail"):
        assert "worker.name" not in spans[non_worker]


# --------------------------------------------------------------------------- #
# Streaming path spans                                                         #
# --------------------------------------------------------------------------- #
async def test_stream_graph_produces_plan_and_responder_spans(
    span_exporter: InMemorySpanExporter,
) -> None:
    """The streaming path emits ``graph.stream`` / ``graph.plan`` / responder-stream spans."""
    responder = FakeResponderRouter(content="a grounded answer")
    state = AgentState(session_id="s", user_message="hi there")

    chunks = [item async for item in stream_graph(state, responder_router=responder)]
    assert chunks  # produced token chunks + terminal state

    names = _span_names(span_exporter)
    assert "graph.stream" in names
    assert "graph.plan" in names
    assert "graph.responder_stream" in names


# --------------------------------------------------------------------------- #
# End-to-end PII non-leak (acceptance criterion)                              #
# --------------------------------------------------------------------------- #
async def test_chat_turn_never_leaks_pii_marker_into_spans(
    span_exporter: InMemorySpanExporter,
) -> None:
    """A turn whose message contains a PII marker leaks it into no exported span attribute."""
    compiled = build_graph(planner=_planner_selecting(WorkerName.PDP_RESUME))

    await compiled.ainvoke(
        AgentState(session_id="s", user_message=f"reach me at {PII_EMAIL} please")
    )

    assert span_exporter.get_finished_spans()  # spans were produced
    for value in _all_attribute_values(span_exporter):
        assert PII_EMAIL not in value


async def test_stream_turn_never_leaks_pii_marker_into_spans(
    span_exporter: InMemorySpanExporter,
) -> None:
    """The streaming path likewise never records the PII marker on a span."""
    responder = FakeResponderRouter(content="ok")
    state = AgentState(session_id="s", user_message=f"my email is {PII_EMAIL}")

    async for _ in stream_graph(state, responder_router=responder):
        pass

    for value in _all_attribute_values(span_exporter):
        assert PII_EMAIL not in value


def test_get_tracer_is_safe_without_configuration() -> None:
    """``get_tracer`` always returns a usable tracer (no-op friendly)."""
    with get_tracer().start_as_current_span("probe"):
        pass  # must not raise
