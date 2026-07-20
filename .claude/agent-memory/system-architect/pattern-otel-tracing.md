---
name: pattern-otel-tracing
description: P11-01 blessed OTel tracing pattern — observability/ cross-cutting pkg, two-layer PII redaction reusing egress redactor, default-off no-op, backend-owned retention
metadata:
  type: project
---

P11-01-otel-tracing APPROVED (rev 1). Blessed design pattern for OTel (§6.26/§7.6/§7.8):

- **Placement:** new `app/observability/` cross-cutting package (tracing.py + redaction.py). Not in §8's enumerated list, but accepted via the [[project-ssrf-guard]] `net/` / `security/` / `tools/` precedent — §8 is a target, cross-cutting pkgs are allowed. Importing it from any layer (incl. agents/graph.py) is no inversion — it's a utility like `logging`.
- **PII redaction = two layers (§7.6/S11):** (1) source discipline — instrumentation sets only counts/intent/booleans, never raw content; (2) `RedactingSpanExporter` decorator drops content-keyed attrs + scrubs string values, **reusing `llm.redaction.redact_contact_details`** (DRY — do not re-implement PII detection). Fail-closed (drop batch on redaction error).
- **Retention (§7.6):** for *exported* traces, retention lives in the OTLP backend's own window, NOT in-app. The §7.6 "30-day Celery purge" applies only to app-owned stores (PG/Redis). Delegating is architecturally correct — accept it.
- **Budget/posture:** default-off (`OTEL_ENABLED=False` → global no-op tracer), vendor-neutral OTLP/HTTP (no vendor SDK), community packages, opt-in local Collector via separate compose override. Never require a live backend for CI/tests.
- **No 2nd admin surface** — telemetry access = provider's own login; no in-app dashboard (YAGNI). Consistent with SSO-only (§6.2).

**Why:** keeps future observability tasks (P11-02 Sentry, P11-04 GA4, P11-05 verify) consistent.
**How to apply:** reuse this pattern for any new telemetry; reject re-implemented PII scrubbers, in-app dashboards, or non-default-off exporters.
