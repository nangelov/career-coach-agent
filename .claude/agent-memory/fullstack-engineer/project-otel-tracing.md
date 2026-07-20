---
name: project-otel-tracing
description: P11 OpenTelemetry tracing pattern — default-off, PII-redacting exporter wrapper, generic node-span seam, curated-dep split
metadata:
  type: project
---

P11 OTel tracing lives in `app/observability/` (tracing.py + redaction.py). Reusable rules:

- **Default-off, fail-soft.** Gate ALL setup on `settings.OTEL_ENABLED` (default False) so CI/tests/local run
  with the no-op global tracer (zero overhead). Guard the top-level `from opentelemetry import trace` import so a
  runtime without the SDK degrades to no-op. `get_tracer()` returns `trace.get_tracer(name)` — safe at import time.
- **PII redaction (§7.6) = two layers.** (1) Only ever set *minimal safe* span attributes (node name, counts,
  intent, booleans) — never raw message/CV content. (2) Defense-in-depth: a `RedactingSpanExporter(delegate)`
  wraps the real exporter and, on `export`, rebuilds each `ReadableSpan` (immutable attrs → reconstruct via its
  constructor copying context/parent/timings/status/kind/scope) with content-keyed attrs dropped + string values
  run through the existing `app.llm.redaction.redact_contact_details` (reuse, don't reimplement). Fail closed
  (return FAILURE) if redaction throws.
- **Generic node-span seam.** In `build_graph`, wrap every `builder.add_node(name, fn)` via a local `_add` that
  applies `traced_node(name, fn)` — new workers auto-get a span. `traced_node` must be transparent (return exactly
  what fn returns) AND preserve sync/async (`inspect.iscoroutinefunction` on fn AND its `__call__` for class-based
  nodes like Responder/Planner) or LangGraph's dispatch breaks. Cast around the langgraph `StateNode` union
  (bound TypeVar can't bind it): cast node→`Callable` in, wrapped→`StateNode` out.
- **Curated-dep split.** `opentelemetry-api`+`opentelemetry-sdk` are light/pure-Python and imported at module
  scope (graph.py→observability) → add to the curated CI/Makefile `uv pip install` list. The
  instrumentation-fastapi/-celery + `opentelemetry-exporter-otlp-proto-http` are lazily imported (only when
  enabled/endpoint set) → put on `INTENTIONAL_EXCLUSIONS` in scripts/check_curated_deps.py (use OTLP/HTTP, not
  gRPC, to avoid grpcio). Celery worker tracing via `worker_process_init` signal (post-fork); FastAPI + Celery
  producer instrumented in `create_app`.
- **Test isolation for the global provider.** Install a redacting in-memory provider ONCE (module-scoped fixture,
  `trace.set_tracer_provider` is set-once) + `SimpleSpanProcessor` (synchronous export) and `exporter.clear()`
  per test. Other suites are unaffected because they never enable OTEL.
