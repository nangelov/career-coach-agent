---
name: check-otel-tracing-tasks
description: Reviewing P11 OpenTelemetry tracing + span PII-redaction tasks (app/observability/) — the URL-query secret-leak gap in the redaction chokepoint
metadata:
  type: project
---

Reviewing P11-01-style OTel tracing: `backend/app/observability/tracing.py` (setup + `traced_node` graph-node span seam + `trace_async_iter`) + `redaction.py` (`RedactingSpanExporter` decorating the real exporter, reusing `app.llm.redaction.redact_contact_details`). Default-off via `OTEL_ENABLED` (config.py), no-op/console/local-collector fallbacks, opt-in `docker-compose.otel.yml`.

**The load-bearing finding — FastAPI auto-instrumentation query-string secret leak.** The redaction module docstring claims "a URL query param captured by HTTP auto-instrumentation is neutralised", but `redact_contact_details` only redacts **contact PII** (email/phone/URL-with-scheme/address/name). FastAPI/ASGI instrumentation sets `http.target` / `url.query` = path+query **without a scheme** (e.g. `/api/auth/callback?code=...&state=...`), so the URL regex (which requires `https?://` or `www.`) does NOT match it, and those key names don't hit the `_SENSITIVE_KEY_SUBSTRINGS` drop-list either. => OAuth authorization codes / `state` / any `?token=` leak to the third-party traces backend when `OTEL_ENABLED`. For HTTP spans the redactor is the ONLY line of defense (the "primary guarantee" that instrumentation sets only-safe-attrs applies to app-owned spans, not auto-instrumentation). Fix options: add `target`/`query`/`http.url`/`url.full` to the drop-or-scrub set, or disable query capture. Major (secret leakage), gate — even though default-off + single-use codes.

**Other checks that held up (don't re-litigate):** redaction wraps exporter for BOTH simple+batch processors (chokepoint proven via InMemorySpanExporter test); fails-closed (drops batch) on redaction exception; content-key drop-list is substring match; `traced_node` is a transparent sync/async-preserving seam applied via a single `_add` helper in `build_graph` (new workers auto-get spans); curated-dep posture correct (api+sdk curated into CI/Makefile, instrumentation+OTLP exporter lazily imported → on `check_curated_deps` allowlist). Tests: `HF_API_TOKEN=x DATABASE_URL=postgresql://x JWT_SECRET_KEY=x backend/.venv/bin/python -m pytest tests/test_observability_tracing.py` → 11 passed (engineer.md said 12 — trivial miscount).

Minor: `_set_node_start_attributes` stamps `worker.name=<node>` on EVERY node (incl. input_guardrail/planner/responder), not just workers — misleading attribute. HTTP→node→Celery single-trace assertion is legitimately deferred to P11-05-verify.
