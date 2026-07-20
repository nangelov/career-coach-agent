# Task P11-02-sentry-error-tracking — S15 Sentry free-tier error notification
- **Phase:** P11   **Status:** ENG   **Tags:** (I)

## Scope
tasks.md P11 item 4: **(I) S15 — Sentry free tier** error notification, **PII scrubbing on**, low-noise alert
rule (§6.24 / §7.7).

- Add `sentry-sdk` (FastAPI + optional Celery integration) initialized in the app factory (`app/main.py`
  lifespan/startup) and the Celery worker entrypoint, **gated by an env var** (`SENTRY_DSN` unset → Sentry is a
  complete no-op; don't require a live DSN for local dev/CI).
- Config via `app/config.py` (`pydantic-settings`): `SENTRY_DSN` (optional), `SENTRY_ENVIRONMENT`,
  `SENTRY_TRACES_SAMPLE_RATE` (default low/0 — this is an *error* tool, tracing is OTel's job, don't double up
  APM spend), `SENTRY_ENABLED`-style default-off posture consistent with `P11-01`'s `OTEL_ENABLED` pattern.
- **PII scrubbing on** (§6.24/§7.7 + design's general PII posture): set `send_default_pii=False` explicitly,
  and add a `before_send` (and `before_send_transaction` if traces are ever sampled) hook that strips/redacts
  request bodies, headers (Authorization/cookies), and any user-identifying free text — reuse
  `app.llm.redaction` / `app.observability.redaction` (from P11-01) rather than re-implementing PII detection.
  Sentry events must never contain chat message content, CV text, or contact-detail PII.
- **Low-noise alert rule**: Sentry's default is "email on every new issue" — this must be scoped down so a
  free-tier account isn't flooded. Since this is infra/config (not code the app enforces), document the exact
  Sentry project alert-rule setting to configure (e.g. "alert only when an issue is seen ≥N times in M
  minutes", or "only for unhandled exceptions", first-seen digest) in the engineer report / a short doc — this
  is the kind of thing a human sets once in the Sentry dashboard using the DSN they create.
- Wire a way to **force a test error** for verification (e.g. a `/api/_debug/sentry-test` endpoint gated to
  `is_admin` users only, or a documented one-liner script) — P11-05-verify will use it to confirm delivery once
  a real DSN is configured.

## Acceptance criteria
- [ ] `SENTRY_DSN` unset → app starts normally, zero Sentry calls, no crash, no dependency import error (lazy
      import, mirroring `P11-01`'s optional-dependency pattern verified by `scripts/check_curated_deps.py`).
- [ ] `SENTRY_DSN` set → an unhandled exception in a request reaches Sentry's `before_send`, which is proven by
      a unit test asserting the hook strips known PII markers (message content / CV-text-shaped string /
      email/phone) from a synthetic event before it would be sent (mock the transport, don't hit a live DSN in
      tests/CI).
- [ ] `send_default_pii=False` set explicitly; test asserts it.
- [ ] A documented way exists to trigger a real test error for manual verification against a live Sentry
      project.
- [ ] Alert-rule guidance documented (not necessarily enforceable in code — Sentry dashboard config).

## Design references
- dev-board/app-design-and-features.md: §6.24 (Sentry free tier, PII scrubbing), §7.7 (error notification /
  key-rotation posture)
- Reuse `app.observability.redaction` / `app.llm.redaction` from `dev-board/code-review/P11-01-otel-tracing/`
  rather than re-implementing PII detection.

## Constraints / non-goals
- Don't build an incident-response programme — this is a free-tier, low-noise error channel, not on-call
  tooling (§7.7 explicitly rules this out).
- Don't wire OTel spans through Sentry (that's `P11-01`'s job) — Sentry stays the error-alerting channel only,
  per the design's split (§6.26 note).
- No live Sentry account/DSN is available to you — implement against the SDK's documented `before_send`
  contract and mock the transport in tests; leave real-DSN verification to `P11-05-verify` / the human owner.
