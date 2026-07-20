# Code review — P11-02-sentry-error-tracking · engineer revision 1

## Verdict: CHANGES_REQUESTED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major | app/observability/sentry.py:218 (`sentry_sdk.init`) | `include_local_variables` is left at its SDK default (**True**), so every captured exception attaches stack-frame local-variable values. `send_default_pii=False` does **not** gate this. The `before_send` scrubber only runs `redact_contact_details` (email/phone/URL/address/name) over strings — it does **not** remove non-contact free text. A locals-captured `messages`/`content`/CV-text string (e.g. "I've been a project manager for 10 years…") survives redaction and is sent to Sentry. This directly violates the task requirement "Sentry events must never contain chat message content, CV text" and the §6.24/§7.6 PII posture. | In `sentry_sdk.init`, set `include_local_variables=False` (primary fix). Add defense-in-depth `max_request_body_size="never"`. Add a unit test asserting `include_local_variables is False` in the captured init kwargs, mirroring the existing `send_default_pii` assertion. |

## Notes
- Everything else is solid and matches the P11-01 posture. Verified locally:
  `pytest tests/test_observability_sentry.py -q` → 13 passed; `scripts/check_curated_deps.py` → OK.
- Default-off gate (`SENTRY_DSN` empty → returns False, zero `init` calls) and guarded `sentry_sdk`
  import are correct and tested. `send_default_pii=False` set explicitly and asserted. `before_send` /
  `before_send_transaction` fail **closed** (drop on scrub error) — good.
- Request body / query string / cookies dropped wholesale and sensitive headers stripped
  (`_scrub_request`); `event.user` PII fields dropped keeping only opaque `id`; residual contact PII
  redacted everywhere via the reused S10 egress redactor (`redact_contact_details`) — no re-implementation.
  This closes the request-body vector; C1 is a separate (stack-locals) vector the same scrubber can't cover.
- `_redact_in_place` reassigns existing dict values during `.items()` iteration (no key add/remove) — safe
  in CPython. Recursion over the full event covers `extra` / `breadcrumbs` / `exception` frames.
- Admin-gated `/api/_debug/sentry-test` correctly reuses `require_admin`; 401/403/raise matrix tested.
  `response_model=None` on the `NoReturn` handler is appropriate.
- Curated-deps rationale (module-scope guarded import → curated, not allowlisted) is correct and the guard
  passes. `SENTRY_TRACES_SAMPLE_RATE` bounded `ge=0.0/le=1.0`, default 0 (error channel, not APM) — good.
- Alert-rule + live-verification guidance documented in `docs/sentry-alerting.md`. Consider adding the
  `include_local_variables=False` guarantee to that doc's PII-scrubbing section once C1 is fixed.

---

# Code review — P11-02-sentry-error-tracking · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| — | — | — | No new findings. C1 resolved. | — |

## Notes
- **C1 (major) — RESOLVED.** `sentry_sdk.init` (`app/observability/sentry.py:227`) now sets
  `include_local_variables=False`, closing the stack-locals vector where `messages`/`content`/CV
  free-text strings would bypass the contact-only `redact_contact_details` scrubber. Defense-in-depth
  `max_request_body_size="never"` (line 229) added. `send_default_pii=False` retained.
- Test `test_configure_sentry_sets_pii_off_and_scrub_hooks` now asserts
  `captured["include_local_variables"] is False` and `captured["max_request_body_size"] == "never"`
  alongside `send_default_pii is False` (`tests/test_observability_sentry.py:78-82`) — the fix is
  regression-guarded.
- Verified locally: `pytest tests/test_observability_sentry.py -q` → 13 passed. Remainder of the
  implementation (default-off DSN gate, guarded import, fail-closed `before_send`, request-body/cookie
  drop, reused S10 redactor, admin-gated test endpoint) is unchanged from revision 1 and remains sound.
- All acceptance criteria met.
