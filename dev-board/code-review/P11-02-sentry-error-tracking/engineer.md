# Engineer report — P11-02-sentry-error-tracking · Revision 2

## Summary
Sentry free-tier **error notification** (§6.24 / §7.7, S15) with **PII scrubbing on**. Default-off
and fail-soft, mirroring P11-01's OTel posture: a complete no-op unless `SENTRY_DSN` is configured
(the whole `sentry_sdk` import is guarded too), so CI / tests / local dev never touch Sentry and
need no DSN. Initialised in the FastAPI app factory and each Celery worker's post-fork init.
`send_default_pii=False` is set explicitly and a `before_send` / `before_send_transaction` hook
scrubs every event — dropping the request body / query string / cookies + sensitive headers,
dropping user PII, and redacting residual contact PII by **reusing** the P11-01/S10 egress
redactor (`app.llm.redaction.redact_contact_details`) rather than re-implementing detection. Sentry
stays the **error channel only** — traces default to 0 sample (APM is OTel's job, §6.26 split). A
low-noise alert rule and a live-DSN verification path are documented; an admin-gated
`/api/_debug/sentry-test` endpoint forces a real error for P11-05-verify.

## Files changed
- `backend/app/observability/sentry.py` — NEW. `configure_sentry` (default-off init with
  `send_default_pii=False` + scrub hooks + FastAPI/Celery integrations), `scrub_event`
  (framework-agnostic PII scrubber), the `before_send` / `before_send_transaction` hooks
  (fail-closed: drop the event if scrubbing raises), guarded `sentry_sdk` import → no-op if absent.
- `backend/app/observability/__init__.py` — export `configure_sentry`, `scrub_event`.
- `backend/app/api/debug.py` — NEW. Admin-gated `GET /api/_debug/sentry-test` (`response_model=None`)
  raising `SentryTestError` to verify delivery.
- `backend/app/main.py` — app factory calls `configure_sentry(settings)`; includes `debug_router`.
- `backend/app/tasks/celery_app.py` — worker `worker_process_init` now also calls
  `configure_sentry` (renamed `_init_worker_tracing` → `_init_worker_observability`).
- `backend/app/config.py` — 3 settings: `SENTRY_DSN` (default "", the off gate),
  `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE` (default 0.0).
- `backend/pyproject.toml` — added `sentry-sdk>=2.0.0` (light pure-Python; module-scope guarded
  import → curated, not allowlisted).
- `.github/workflows/backend-ci.yml`, `backend/Makefile` — added `sentry-sdk` to the curated list.
- `docs/sentry-alerting.md` — NEW. Enable steps, the exact low-noise issue-alert rule to set in
  the Sentry dashboard, the PII-scrubbing guarantee, and the verify-delivery path.
- `backend/tests/test_observability_sentry.py` — NEW. 13 tests.

## Key decisions
- **DSN presence is the default-off gate** (§6.24). No separate `SENTRY_ENABLED` flag: an empty
  `SENTRY_DSN` is off (mirrors OTel's disabled posture, and matches the acceptance criteria which
  key on DSN set/unset). KISS — one knob, no redundant flag that could contradict the DSN.
- **Two-layer PII scrubbing, reusing the egress redactor (§7.6).** Layer 1 drops raw content
  wholesale — the request **body** / query string / cookies (a POST body is where chat/CV text and
  OAuth codes live), sensitive headers, and `event.user` identifying fields. Layer 2 recursively
  runs every remaining string through `redact_contact_details` (the same S10 chokepoint the OTel
  span exporter reuses). `send_default_pii=False` is the primary switch on top. Fails **closed** —
  a scrub exception drops the event rather than send un-scrubbed PII (same posture as
  `RedactingSpanExporter`).
- **Error channel only, not APM.** `SENTRY_TRACES_SAMPLE_RATE` defaults to 0 so we don't double-pay
  for Sentry performance spans — distributed tracing stays with OTel (§6.26 / §7.8). A
  `before_send_transaction` hook is still wired so *if* traces are ever sampled they're scrubbed too.
- **Admin-gated test-error endpoint** reuses the existing `require_admin` gate (a public "throw an
  error" route would be alert-spam); `response_model=None` because the handler only ever raises.
- **Curated dep, not allowlisted.** `sentry-sdk` is light pure-Python (urllib3+certifi; the
  FastAPI/Celery integrations ship inside it) and imported (guarded) at module scope, so per the
  `check_curated_deps.py` rule it belongs in the curated CI/Makefile list — not the lazy-import
  allowlist.

## How to verify
- `cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app/`
- `.venv/bin/python scripts/check_curated_deps.py`
- `.venv/bin/python -m pytest tests/test_observability_sentry.py -q`
- Live (P11-05-verify / owner): set `SENTRY_DSN`, hit `GET /api/_debug/sentry-test` as an admin,
  confirm the PII-scrubbed `SentryTestError` issue appears. See `docs/sentry-alerting.md`.

## Tests (final step — mandatory)
- `.venv/bin/python -m pytest -q` → **976 passed, 83 skipped** (was 963 passed; +13 new; skips are
  pre-existing heavy-dep / live-DB skips, unchanged). No failures.
- New `tests/test_observability_sentry.py`: 13 passed — default-off no-op, SDK-unavailable no-op,
  `send_default_pii=False` + scrub hooks + 0 sample-rate init contract, body/cookies/query/header
  drop, user-PII drop, contact-PII redaction everywhere (no marker survives), minimal-event
  tolerance, fail-closed on scrub error, and the endpoint 401/403/raise matrix.
- `ruff check .` → All checks passed. `ruff format --check .` → 280 files already formatted.
- `mypy app/` → Success: no issues found in 155 source files. `check_curated_deps.py` → OK.
- No test was weakened or deleted. Two implementation fixes surfaced while getting to green:
  (1) a `NoReturn` handler needs `response_model=None` (FastAPI can't build a response field from
  it); (2) httpx `ASGITransport` has no `raise_server_exceptions` kwarg and re-propagates unhandled
  exceptions, so the admin test asserts `pytest.raises(SentryTestError)` — the exact unhandled path
  Sentry's FastAPI integration captures.

## Self-check
- [x] Meets acceptance criteria: DSN-unset → no-op, no import error (curated-deps guard passes);
      DSN-set → unhandled exception reaches `before_send`, proven by a unit test asserting PII
      markers (email/phone/CV-shaped text) are stripped from a synthetic event; `send_default_pii=False`
      asserted; documented live-verification path; alert-rule guidance documented.
- [x] No secrets committed (DSN/env via Space Secrets only); Router→Service/observability layering
      respected (debug router is thin + admin-gated; scrubbing is a cross-cutting helper; only the
      composition roots — app factory + worker init — wire `configure_sentry`).
- [x] Tests/lints/mypy/curated-deps pass (pasted above).

## Notes / non-goals
- No incident-response programme and no OTel-via-Sentry span bridging (§7.7 / §6.26 split), per the
  task constraints.
- No live DSN is available here; scrubbing is implemented against the SDK's documented `before_send`
  contract with the transport mocked (`sentry_sdk.init` patched) — real-DSN delivery is P11-05-verify.

## Response to review (revision 2)
- **C1 (major) — `include_local_variables=True` leaks chat/CV free text past the contact-only
  redactor.** Fixed. `sentry_sdk.init` now sets **`include_local_variables=False`** (primary fix —
  stack-frame locals like `messages` / `content` / CV strings are never attached to captured
  exceptions, closing the stack-locals vector the `redact_contact_details` string scrubber can't
  cover). Added defense-in-depth **`max_request_body_size="never"`** so the request body is never
  captured at all. Extended `test_configure_sentry_sets_pii_off_and_scrub_hooks` to assert both
  `include_local_variables is False` and `max_request_body_size == "never"` in the captured init
  kwargs, mirroring the existing `send_default_pii` assertion. Updated the PII-scrubbing section of
  `docs/sentry-alerting.md` to document both guarantees. (`app/observability/sentry.py`,
  `tests/test_observability_sentry.py`, `docs/sentry-alerting.md`.)
- **architecture-review.md** — APPROVED, no action required.

### Verification (revision 2)
- `ruff check` / `ruff format --check` → clean; `mypy app/observability/sentry.py` → Success.
- `pytest tests/test_observability_sentry.py -q` → 13 passed.
- Full suite `pytest -q` → **976 passed, 83 skipped** (unchanged count; skips pre-existing). No failures.
