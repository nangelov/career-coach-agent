# Task P11-01-otel-tracing — OpenTelemetry instrumentation, OTLP export, PII redaction
- **Phase:** P11   **Status:** ENG   **Tags:** (B) (I)

## Scope
Combines tasks.md P11 items 1–3:
1. **(B)** OpenTelemetry instrumentation: FastAPI auto-instrumentation (requests) + manual spans for the
   **actual** LangGraph node graph assembled in `backend/app/agents/graph.py::build_graph` — the compiled node
   sequence is `input_guardrail → memory_recall → planner → {rag, web_search, market_intel, pdp_resume,
   dashboard} (conditional fan-out) → responder → output_guardrail → memory_writer` (node name constants:
   `INPUT_GUARDRAIL`, `MEMORY_RECALL`, `PLANNER`, `WORKER_NODES` (`WorkerName` values), `RESPONDER`,
   `OUTPUT_GUARDRAIL`, `MEMORY_WRITER`). Wrap each node function (or use a single generic node-wrapping helper
   applied in `build_graph`'s `builder.add_node(...)` calls, so new nodes automatically get a span without
   editing this task's code again) so every node produces one child span under the turn's root span, named
   after the node constant, with the node's wall-clock duration and (redacted, see item 2) minimal attributes
   (e.g. `graph.node`, `plan.intent`, `worker.name`, counts — never raw content). Also add spans/attributes for
   the **streaming** path (`GraphTurnStreamer.plan` / `stream_response` / `stream_graph`), not just `run_graph`,
   since `POST /api/chat` uses the streaming path in production. Celery task spans: wrap task bodies in
   `app/tasks/` (or use the community `opentelemetry-instrumentation-celery` package) so async jobs (PDP
   generation, market mining, memory learn step, retention purge, etc.) also produce spans/traces.
2. **(B) S11 — PII redaction + retention limit on traces/logs** (design §7.6): traces would otherwise contain
   full CV text and every message; redact at the source — i.e. a span-processor / attribute filter that strips
   message content, CV/document text, and any PII fields (reuse existing redaction utilities from S10/S7 where
   possible, e.g. `llm/` egress redaction, memory PII filters) **before** spans/log records leave the process.
   No message content, CV text, or contact-detail PII should ever be an attribute value on an exported span.
3. **(I)** OTLP exporter: env-configured endpoint + API key (headers), targeting a free-tier hosted OTel
   backend of the owner's choice (Grafana Cloud free / Honeycomb free / similar). Must stay vendor-neutral
   (plain OTLP/gRPC or OTLP/HTTP exporter — no vendor SDK lock-in). No bespoke in-app telemetry dashboard.
   Also wire a **local OTel Collector** service into `docker-compose.yml` (or an opt-in override) that can
   receive spans and dump them (e.g. `otlp` receiver → `logging`/`file` exporter) so tracing can be verified
   end-to-end without a live paid/free-tier account — this is what P11-05-verify will exercise.

## Acceptance criteria
- [ ] A full chat turn (`/api/chat`) produces a trace with parent/child spans covering: HTTP request →
      LangGraph nodes (planner, at least one worker, responder) → any Celery task it triggers.
- [ ] Span attributes never contain raw message text, CV/document text, or contact-detail PII — verified by a
      test that runs a chat turn with a message containing an obvious PII marker and greps exported spans for
      it (must NOT be found).
- [ ] OTLP exporter is env-configured (endpoint, headers/API key, service name) via `app/config.py`
      (`pydantic-settings`), defaults to no-op/console exporter if unset (so local dev/CI doesn't require a
      live backend).
- [ ] A local OTel Collector is available via docker-compose (opt-in, doesn't break existing `docker compose up`)
      so a developer can point the app at `http://otel-collector:4317` and see spans logged.
- [ ] Unit/integration tests cover: span creation for the chat flow, and the redaction filter (PII markers not
      leaked).

## Design references
- dev-board/plan.md: P11 §Observability
- dev-board/app-design-and-features.md: §6.26 (Observability → OpenTelemetry), §7.6 (PII redaction & retention)
- Reuse existing redaction code from S7 (`P9-04-memory-pii-gdpr-filter`) and S10 (LLM egress redaction) rather
  than re-implementing PII detection from scratch — check `dev-board/code-review/SEC-08-contact-redaction/` and
  `P9-04-memory-pii-gdpr-filter/` for the existing utilities/patterns.

## Constraints / non-goals
- No bespoke in-app telemetry dashboard (YAGNI) — the OTel backend's own UI is the dashboard.
- Don't touch Sentry (P11-02) or GA4 (P11-04) — separate tasks.
- Don't require a live paid/free-tier account for tests/CI to pass — must be no-op/console/local-collector by
  default.
- Follow the free/OSS/self-hosted posture; use community OTel exporters (`opentelemetry-exporter-otlp`), not a
  vendor-specific SDK.
