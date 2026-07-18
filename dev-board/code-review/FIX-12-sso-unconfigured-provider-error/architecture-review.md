# Architecture review — FIX-12-sso-unconfigured-provider-error · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Pre-flight guard in the service, HTTP mapping in the router, BFF/UI in `frontend/` | Guard `_require_configured_provider` in `services/auth.py`; 503 mapping in `api/auth.py`; reason-surfacing in `frontend/components/Chat.tsx`; BFF branch unchanged in `app/api/auth/login/[provider]/route.ts` | None |
| A2 | Layering (Router→Service→Repo) | Credential check off injected state, not by reaching into OIDC client/network; router only maps to HTTP | Check reads injected `_provider_credentials` mapping; `begin_login` raises before any `OIDCClient` call; `sso_login` only maps `ProviderNotConfigured`→503 | None — pre-flight stays off the network |
| A3 | SSO-only auth (§7.1, CLAUDE.md locked) | No password surface; only add a "is this provider configured" guard, OAuth flow (PKCE/state/exchange) untouched | Guard added; PKCE/state/token-exchange paths untouched; `GOOGLE_*`/`LINKEDIN_*` stay optional `Settings` fields (single-provider deployments keep working) | None |
| A4 | BFF transport (§7.2 / §6.13, SEC-04) | 503 flows through the existing "anything else → `provider_unavailable`" branch; token never enters browser JS/URL | BFF maps non-3xx → `provider_unavailable`; Chat.tsx reads only the `?login_error` reason (no token), strips it via `replaceState` | None — consistent with [[project-bff-session-transport]] |
| A5 | Exception→status distinctness | New status distinct from existing mappings (404 unknown, 400 consent, 502 OIDC) | `ProviderNotConfigured`→503, separate from `OIDCError`'s 502 (reachability); 404/400 behavior unchanged | None |
| A6 | Ordering / no side effects on failure | Guard before OIDC call and before an upgrade ticket is consumed | Order: known-provider (404) → configured (503) → consent (400) → ticket → OIDC; unconfigured provider never consumes an upgrade ticket | None — sound ordering choice |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — check in service, mapping in router
- [x] Honors locked decisions (SSO-only, no new password surface; Postgres+Redis only; no ReAct parser touched)
- [x] Interfaces-before-implementations — no new port needed; credentials injected via ctor, consistent with existing `from_settings` wiring ([[project-auth-session-seam]])
- [x] Budget posture respected (no new paid dependency)

## Notes
- Fail-closed default is correct: `_provider_credentials.get(provider, ("", ""))` means a provider present in `OAUTH_METADATA_URLS` but absent from the credentials map also raises `ProviderNotConfigured` rather than 302-redirecting with a blank `client_id`. Good defensive posture.
- Minor DRY observation (non-blocking, cheap to fix later): the `{"google": ..., "linkedin": ...}` provider-name literals in `from_settings` duplicate the provider set implied by `OAUTH_METADATA_URLS`. Acceptable at two providers; if a third is ever added, both spots must be updated. Log-only, no change required.
- Bullet 4 (surface `provider_unavailable` on the login screen) delivered as a small in-place addition reusing the existing `loginMessage` prop — correctly avoided building provider-discovery plumbing, matching the task's "only if low-risk" constraint.
- Scope is a bug fix on top of `[x]` P3-02; no phase-fit or data-ownership concerns.
