# Code review — FIX-12-sso-unconfigured-provider-error · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/services/auth.py:246-248 | `_require_configured_provider` treats whitespace-only creds (e.g. `" "`) as configured — `not client_id` is False for `" "`. Not a realistic env value; blank default `""` is correctly caught. | Optional: `.strip()` before the check. Not blocking. |
| C2 | nit | backend/app/services/auth.py:218-221 | `from_settings` hard-codes the credential dict to `google`/`linkedin`, while `_providers` derives from `OAUTH_METADATA_URLS`. A future provider added only via that env would fail-safe (`.get(...)` default `("","")` → 503), never leak a blank `client_id`. Correct fail-safe behavior; noting the coupling. | None required. |

## Notes
- Root-cause fix is correct and minimal. Pre-flight `_require_configured_provider` runs in
  `begin_login` **before** any OIDC call and before upgrade-ticket consumption (order:
  known → configured → consent → ticket → OIDC), exactly as scoped — an unconfigured provider
  can never 302 the browser to the IdP with a blank `client_id`, nor burn an upgrade ticket.
- Exception is distinct (`ProviderNotConfigured`), mapped to **503** in `sso_login` alongside the
  unchanged `UnknownProvider` (404) / `ConsentRequired` (400) / `OIDCError` (502). Error `detail`
  contains only the provider name — no credential leakage.
- BFF `login/[provider]/route.ts` routes 503 through its existing "anything else →
  `provider_unavailable`" branch (verified by reading the handler); the frontend now actually
  surfaces `?login_error=<reason>` via the existing `loginMessage`/`Login message` prop and strips
  the param with `history.replaceState`. Bullet 4 completed as a small, low-risk addition (no new
  endpoint / provider-discovery plumbing) — appropriate per task §Scope 4.
- Constraints honored: `GOOGLE_*`/`LINKEDIN_*` remain optional `""`-default `Settings` fields
  (single-provider deployments keep working — proven by `test_begin_login_configured_provider_
  still_works_when_other_unconfigured`); no OAuth-flow changes; `.env`/`.env.example` untouched.
- Router→Service layering respected: the credential check lives in the service off injected
  `provider_credentials`, not by reaching into the OIDC client; the API only maps to HTTP.
- Tests are real, not vacuous: service test asserts `oidc.authorization_requests == []` and
  `states.pop("state-1") is None` (both are genuine post-conditions — `FakeOIDCClient` records
  calls and mints `state-N` only when reached). Parametrized over both providers × both fields ×
  both-blank. All direct `SsoAuthService(...)` constructions (4 sites) updated for the new required
  kwarg.
- Verified locally: `pytest tests/test_sso_service.py tests/test_sso_api.py` → 25 passed;
  `npx jest bffAuthRoutes` → 14 passed (incl. the new 503 case); `npx jest Chat` → 31 passed.
- Acceptance criteria: all met.
