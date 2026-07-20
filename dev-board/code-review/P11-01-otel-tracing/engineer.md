# Engineer report — P11-01-otel-tracing · Revision 2

## Summary
OpenTelemetry tracing across the three §7.8 surfaces (FastAPI, the LangGraph node graph, Celery
tasks), exported via a vendor-neutral OTLP/HTTP exporter, with PII redaction (§7.6, S11) enforced
before any span leaves the process. Default-off and fail-soft: gated on `OTEL_ENABLED` (default
`False`) so CI/tests/local dev run with a no-op tracer and nothing is exported. A local OTel
Collector is wired as an opt-in docker-compose override for end-to-end verification without a
paid/free-tier account.

## Files changed
- `backend/app/observability/tracing.py` — NEW. Setup (`configure_tracing`, `instrument_fastapi`,
  `instrument_celery`, `build_tracer_provider`, `_build_exporter`), `get_tracer`, the generic
  `traced_node` graph-node span wrapper, and `trace_async_iter` for responder token streaming.
  Guarded OTel import → no-op if the SDK is absent.
- `backend/app/observability/redaction.py` — NEW. `RedactingSpanExporter` (decorates the real
  exporter, rebuilds each span with redacted attributes/events) + `redact_attributes`. Reuses
  `app.llm.redaction.redact_contact_details` (S10 egress redactor) rather than re-implementing PII
  detection. Drops content-keyed attributes; scrubs contact-detail PII from remaining string values.
- `backend/app/observability/__init__.py` — NEW. Public surface.
- `backend/app/agents/graph.py` — wrapped every `builder.add_node(...)` via a single generic `_add`
  helper applying `traced_node` (new nodes auto-get a span); added spans to `run_graph` (`graph.run`),
  `GraphTurnStreamer.plan` (`graph.plan`), `stream_response` (`graph.responder_stream`), and
  `stream_graph` (`graph.stream`).
- `backend/app/main.py` — `create_app` installs the global provider + instruments FastAPI and the
  Celery producer (context propagation into enqueued jobs).
- `backend/app/tasks/celery_app.py` — `worker_process_init` signal installs tracing + Celery
  instrumentation per worker process (post-fork).
- `backend/app/config.py` — 5 settings: `OTEL_ENABLED`, `OTEL_SERVICE_NAME`,
  `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_CONSOLE_EXPORT`.
- `backend/pyproject.toml` — added otel deps (api/sdk + instrumentation-fastapi/-celery + exporter-otlp-proto-http).
- `.github/workflows/backend-ci.yml`, `backend/Makefile` — curated `opentelemetry-api opentelemetry-sdk`.
- `backend/scripts/check_curated_deps.py` — allowlisted the 3 lazily-imported otel packages.
- `docker-compose.otel.yml`, `otel-collector-config.yaml` — NEW. Opt-in local Collector (OTLP→debug log).
- `backend/tests/test_observability_tracing.py` — NEW. 14 tests.

## Key decisions
- **PII redaction at the exporter, reusing the egress redactor (§7.6).** `RedactingSpanExporter`
  wraps whatever exporter is configured and scrubs every span on the way out — the concrete
  implementation of §7.6's "traces otherwise contain full CV text and every message". Combined with
  the primary guarantee (node/turn/task instrumentation only sets counts/intent/booleans, never raw
  content), no message text / CV text / contact PII can reach the wire. Fails closed (drops the batch)
  if redaction raises.
- **Generic node-span seam in `build_graph`.** A single `_add` helper applies `traced_node` to every
  node, so a future worker automatically gets a child span with no further edits (task requirement).
  `traced_node` is transparent and preserves sync/async so LangGraph's dispatch is unchanged.
- **Default-off + fail-soft.** All setup no-ops unless `OTEL_ENABLED`; enabling with no endpoint drops
  spans (or console-dumps) so a live backend is never required for tests/CI. OTLP/HTTP (not gRPC) keeps
  the dep light and vendor-neutral; the exporter is imported lazily only when an endpoint is set.
- **Curated-dep posture.** api+sdk are module-scope imports → curated into CI/Makefile; the
  instrumentation + OTLP exporter are lazily imported → on the `INTENTIONAL_EXCLUSIONS` allowlist.
- **Retention (§7.6)** is the OTLP backend's own retention window (free-tier default) — no in-app
  plumbing; the app controls redaction + endpoint only. Documented in the module docstring.

## How to verify
- `cd backend && make lint format-check && uv run --no-sync mypy app/` (or `.venv/bin/...`).
- `.venv/bin/python -m pytest tests/test_observability_tracing.py -q`.
- End-to-end (optional, no account needed):
  `docker compose -f docker-compose.yml -f docker-compose.otel.yml up`, drive a chat turn, then
  `docker compose ... logs -f otel-collector` to see redacted spans. (P11-05-verify exercises this.)

## Tests (final step — mandatory)
- `.venv/bin/python -m pytest -q` → **963 passed, 83 skipped** (skips are pre-existing heavy-dep /
  live-DB skips, unchanged). New `test_observability_tracing.py`: 14 passed.
- `ruff check` / `ruff format --check` (observability + graph + new test) → All checks passed.
- `mypy app/` → Success: no issues found in 153 source files.
- `python scripts/check_curated_deps.py` → OK.
- No failures; nothing weakened or deleted.

## Response to review (revision 2)
- **C1 (major) — scheme-less query-string leak.** `redact_attributes` now (a) drops any key
  containing `query` (adds `"query"` to `_SENSITIVE_KEY_SUBSTRINGS`, so a bare `url.query` /
  `http.request.query_string` attribute is dropped wholesale), and (b) strips the `?query`
  (and `#fragment`) tail off request-URL keys (`http.target` / `http.url` / `url.full` /
  `url.path`) via a new `_strip_query_string` + `_is_url_key`/`_URL_KEY_SUBSTRINGS`. An OAuth
  callback `/api/auth/callback?code=...&state=...` (scheme-less, so the value-level URL redactor
  never matched it) now exports as just `/api/auth/callback`. Corrected the module docstring
  (layer-2 description) and `_redact_value`'s docstring to describe the key-based drop/strip and
  no longer overclaim the value redactor covers scheme-less query params. New tests:
  `test_redact_attributes_strips_scheme_less_query_secrets`,
  `test_redact_attributes_drops_bare_query_attribute`.
- **C2 (minor) — `worker.name` on non-worker spans.** `_set_node_start_attributes` /
  `traced_node` gained an `is_worker` flag; `worker.name` is now stamped **only** on the
  `WorkerName` fan-out nodes. `graph.py`'s `_add` helper passes `is_worker=True` for the five
  worker nodes; guardrail/recall/planner/responder/memory-writer spans carry only `graph.node`.
  New test `test_worker_span_stamps_worker_name_but_planner_does_not`; existing planner-span
  test also asserts `worker.name` absent.
- **C3 (nit) — test count.** Corrected: the suite now has 14 test functions (was 11; +3 this
  revision). Report figures updated (960→963 total, 12→14 in the file).

## Self-check
- [x] Meets acceptance criteria: node spans (planner/worker/responder) under a shared trace; PII-marker
      turn leaks nothing into span attributes (tested); OTLP exporter env-configured via `config.py`,
      no-op default; opt-in local Collector doesn't break default `docker compose up`; unit+integration
      tests cover span creation + redaction.
- [x] No secrets committed (OTLP endpoint/headers are env/Space-Secret only); Router→Service→Agent/Repo
      layering respected (observability is a cross-cutting helper; API/service layers untouched except
      the composition-root wiring in `main.py`).
- [x] Tests/lints pass (pasted above).

## Notes / possible split
- FastAPI/Celery auto-instrumentation is enabled behind `OTEL_ENABLED`; its span *emission* is verified
  by the OTel packages themselves, so my tests focus on the app-owned surfaces (graph nodes + redaction).
  A full HTTP→node→Celery single-trace assertion needs the live Collector — that is P11-05-verify's job.
