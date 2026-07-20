# Architecture review — P11-01-otel-tracing · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | code in a sanctioned module | New cross-cutting `app/observability/` (tracing.py, redaction.py) sibling to `net/`, `security/`, `tools/` | §8 doesn't enumerate `observability/`, but it is a cross-cutting concern and follows the blessed precedent for `net/`/`security/`/`tools/`. Accepted, no change. |
| A2 | §7.8 three surfaces | OTel across FastAPI + LangGraph node graph (planner/workers/responder) + Celery | FastAPI auto-instrument (main.py), generic `traced_node` on every `builder.add_node` in `build_graph`, spans on run/plan/stream/responder_stream, CeleryInstrumentor per worker-init | Matches §7.8 topology exactly. |
| A3 | §7.6 / S11 PII redaction | message/CV/contact PII redacted **before** leaving the process | Two layers: source spans set only counts/intent/booleans (`_set_node_result_attributes`); `RedactingSpanExporter` drops content-keyed attrs + scrubs string values via reused `llm.redaction.redact_contact_details`; fails closed on error | Conforms; DRY (reuses egress redactor, not re-implemented). |
| A4 | §6.26 vendor-neutrality | plain OTLP, no vendor SDK lock-in | OTLP/HTTP exporter, lazily imported; no vendor SDK | Conforms. |
| A5 | §6.26 no admin surface | telemetry access via provider's own login, no 2nd password surface | No in-app dashboard; endpoint/headers env-only | Conforms. |
| A6 | §11 budget posture | free / OSS / self-hosted; default no-op | Gated on `OTEL_ENABLED` (default False), console/no-op fallback, opt-in local Collector via `docker-compose.otel.yml`; community OTel packages only | Conforms; live backend never required for CI/tests. |
| A7 | Config (§8 config.py) | env-configured via pydantic-settings | 5 `OTEL_*` settings in `config.py` | Conforms. |
| A8 | §7.6 retention limit | retention-limited traces | Delegated to OTLP backend's own retention window (free-tier default), no in-app plumbing | Architecturally correct — the app cannot purge a third-party store; documented in module docstring. See Notes. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — observability is a cross-cutting utility (like `logging`) wired at the composition root (main.py / celery worker-init); Router→Service→Agent/Repo untouched; graph.py importing it is no inversion.
- [x] Honors locked decisions — LangGraph node topology instrumented as-is; no ReAct/Mongo/paid tier introduced; SSO-only admin posture preserved (no new admin surface).
- [x] Interfaces-before-implementations — `RedactingSpanExporter` decorates any `SpanExporter`; backend swappable via OTLP endpoint; generic `traced_node` seam auto-covers future nodes.
- [x] Budget posture respected (free/OSS/self-hosted, default-off).

## Notes
- Retention (§7.6) for *exported* traces genuinely lives in the OTLP backend, not in-app; the app owns redaction + endpoint only. The §7.6 "30-day Celery purge" applies to app-owned stores (Postgres/Redis) and is out of scope here. Acceptable; flag for the P11 pre-go-live sweep to confirm the chosen backend's free-tier retention is set appropriately.
- Node-span redaction is two-layered (source discipline + exporter chokepoint). The exporter layer's key-substring deny-list is intentionally narrow; the value-level scrub is the backstop. Sound defense-in-depth; no change needed.
- Single-trace HTTP→node→Celery assertion is deferred to P11-05-verify (needs the live Collector) — a reasonable split, not a gap.
