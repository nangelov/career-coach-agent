# Architecture review — P11-02-sentry-error-tracking · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | error-tracking lives in the observability seam; verification endpoint under `api/` | `app/observability/sentry.py` (init + scrubber + hooks), exported via `observability/__init__.py`; thin `app/api/debug.py` router | none |
| A2 | Layering (Router→Service, composition roots wire infra) | only composition roots init Sentry; router thin | `configure_sentry(settings)` called only in app factory (`main.py:160`) + Celery `worker_process_init` (`celery_app.py:65`); `debug.py` is a thin admin-gated route that only raises | none |
| A3 | §6.24/§7.6/§7.7 PII scrubbing on | `send_default_pii=False` + hook drops body/headers/cookies/user PII + redacts contact PII, reuse egress redactor (DRY) | `send_default_pii=False` explicit; `scrub_event` drops body/query/cookies + sensitive headers + `event.user` PII, then recursively runs strings through `app.llm.redaction.redact_contact_details` (reused, not re-implemented); fails closed | none |
| A4 | §6.26/§7.8 OTel/Sentry split | Sentry = error channel only, not APM; no OTel-over-Sentry bridge | `SENTRY_TRACES_SAMPLE_RATE` default `0.0`; no span bridging; `before_send_transaction` only scrubs if traces ever sampled | none |
| A5 | Default-off / fail-soft posture (mirror P11-01 OTel) | DSN-unset → complete no-op, no import error; consistent with `OTEL` disabled pattern | `configure_sentry` returns `False` unless SDK importable AND `SENTRY_DSN` non-blank; whole `sentry_sdk` import guarded; one knob (DSN), no redundant flag (KISS/YAGNI) | none |
| A6 | Budget posture §11 | free/OSS/self-hosted; paid behind opt-in | Sentry free-tier; traces=0 avoids paid APM spend; DSN via env/Space Secret, not committed | none |
| A7 | Auth § SSO-only | admin surface uses backend session, no passwords | `sentry_test` gated by `require_admin` (401 anon / 403 non-admin); no new auth path | none |
| A8 | Dep hygiene (curated CI list) | module-scope guarded light dep → curated, list == Makefile == CI | `sentry-sdk>=2.0.0` in `pyproject.toml`, `Makefile:58`, `backend-ci.yml:137` — all three consistent | none (matches [[ruling-curated-ci-light-deps]]) |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (composition roots wire infra; router thin + admin-gated; scrubber is a cross-cutting helper)
- [x] Honors locked decisions (no new datastore — Postgres+Redis only untouched; SSO-only admin gate; no ReAct parser touched; in-process embeddings untouched)
- [x] Interfaces-before-implementations — `scrub_event` is framework-agnostic (plain dict) and unit-testable; thin `before_send*` bridge to SDK types; reuses the S10 egress redactor seam rather than forking PII detection (DRY)
- [x] Budget posture respected (free-tier, traces=0, secrets via env/Space Secret)

## Notes
- No design deviations. The Sentry/OTel channel split (§6.26/§7.8) is respected cleanly: Sentry stays the error-alerting channel, OTel keeps APM, and the two-layer scrubber mirrors `RedactingSpanExporter`'s fail-closed posture — good cross-cutting consistency with P11-01.
- Reuse of `app.llm.redaction.redact_contact_details` as the single PII chokepoint is the right call — keeps one detection source of truth across LLM egress, OTel spans, and now Sentry events.
- `/api/_debug/sentry-test` is a net-new admin-only API surface but is verification-only, gated by `require_admin`, and not part of any product flow — acceptable and cheap to remove. No follow-up required.
- Alert-rule noise control is correctly treated as dashboard config (documented in `docs/sentry-alerting.md`), not app-enforced code — appropriate for infra.
