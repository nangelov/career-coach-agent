# Architecture review — P3-02-sso-oidc · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | OIDC/PKCE mechanics + verify dependency in `security/` or thin router, not smeared into `services/` (blessed P3-01 ruling) | `security/oidc.py` (OAuth mechanics), `security/dependencies.py` (`require_auth`); ports in `services/`, adapters in `repositories/` + `security/` | None |
| A2 | Layering Router→Service→Repo | Router thin (HTTP/redirect/error-map); services depend on ports only, never DB drivers | `api/auth.py` thin (302/error-map only); `services/auth.py` depends on `OIDCClient`/`OAuthStateStore`/`UserStore`/`SessionStore`/`SessionTokenCodec` ports; adapters in `repositories/` | None |
| A3 | SSO-only, no passwords (§6.2, §7.1, §4 `users`) | Identity is `(provider, sub)` + minimal PII; no credential column ever written | `PostgresUserStore` upserts only `provider/sub/email/display_name`; no password field anywhere; `UserAccount` carries no secret | None |
| A4 | PKCE + minimal scopes (§7.1) | S256 PKCE so a leaked client id alone cannot complete a flow; scopes exactly `openid email profile` | `code_challenge_method="S256"` + per-attempt `code_verifier`; `OAUTH_SCOPES` default `openid email profile` | None |
| A5 | Backend-owned short-lived session JWT (§6.2, §7.1) | FastAPI mints its own JWT; Next.js pure Bearer client; short-lived, signing key from secret | `complete_login` mints `role="user"`, `sub=users.id` via shared `SessionTokenCodec`; `JWT_SECRET_KEY` required (`...`), `JWT_EXPIRE_MINUTES` default 60 | None |
| A6 | Secrets via Space secrets/env (§7, §7.1) | Client secret + signing key never committed | `JWT_SECRET_KEY` required (no default); all client id/secret default `""`; metadata URLs are public constants; `.env.example` placeholders | None |
| A7 | Redirect URIs locked to domain, not hardcoded (§7.1) | Callback URI derived from config | `_redirect_uri` = `<OAUTH_REDIRECT_BASE_URL>/api/auth/callback/{provider}`; supported set = keys of `OAUTH_METADATA_URLS` | None |
| A8 | Uniform token shape (§9, blessed P3-01) | One JWT/response shape for guest and user; `SessionRole` literal lives once | `SessionResponse` mirrors `GuestSessionResponse` field-for-field; single `SessionRole` in `schemas/auth.py`; `CurrentUser` unified | None |
| A9 | Reusable verify dependency (§7.1) | Single `require_auth` guard reusable by all protected routes, below `api/` | `security/dependencies.py::require_auth` → `CurrentUser`; no router-to-router coupling | None |
| A10 | Datastores Postgres+Redis only, single shared pools (§4) | Users→Postgres shared pool; ephemeral→shared Redis pool; no new pool/driver | `PostgresUserStore` over shared `PostgresConnectionProvider`; state/session stores over `_shared_redis_client`; no Mongo, no per-request clients | None |
| A11 | Guests Redis-only (§4) | Guest flow unchanged, no Postgres | `build_sso_auth_service` requires PG (fails loud) for users; guest path untouched, Redis-only | None |
| A12 | Phase fit (P3) | Login only; profile-import/authz/upgrade deferred | Scopes minimal, no stored provider token; authz→P3-04, guest-upgrade→P3-03 respected | None |
| A13 | Interfaces before implementations | Ports precede adapters | `OIDCClient`, `OAuthStateStore`, `UserStore` (+`SessionStore` from P3-01) are ABCs with in-memory + real adapters | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repo) — `security/` extension honored per blessed P3-01 ruling
- [x] Honors locked decisions (SSO-only, no passwords; Authlib OIDC + PKCE S256 + minimal scopes; backend session JWT; Postgres+Redis only)
- [x] Interfaces-before-implementations (`OIDCClient`/`OAuthStateStore`/`UserStore`/`SessionStore` ports before adapters)
- [x] Budget posture respected (self-hosted, free OSS: Authlib/joserfc, in-process; no paid provider, no managed tier)

## Notes
Design risks / follow-ups (all non-gating — behind ports, cheap to unwind later):

1. **Logged-in `sessions` anchored in Redis, not the §4 Postgres `sessions` table.** §4 lists
   `sessions` under Postgres; the engineer keeps the user session *record* in Redis
   (`RedisSessionStore`, TTL `USER_SESSION_TTL_SECONDS`) as the revocation handle, with durable
   identity in Postgres `users`. This is the documented Redis-anchored decision my P3-01 ruling
   explicitly permitted ("or a documented Redis-anchored decision; the generic port absorbs it").
   The `SessionStore` port makes a later move to a Postgres `sessions` adapter cheap. **Accepted;
   logged as a follow-up** if durable/audit session history is required later.

2. **Identity resolved via the `userinfo` endpoint, not `id_token`/JWKS.** §7.1 frames identity as
   "an OIDC ID token"; the implementation fetches provider-verified claims from `userinfo` over TLS
   with the just-issued access token, keeping the code JWKS-free while PKCE + `state` cover
   interception/CSRF. Design-conformant (SSO-only, minimal scopes, no passwords all preserved).
   Side effect: a `nonce` is generated and stored but never verified (it would only bind an
   `id_token`) — correctness/dead-value nuance for the **code-reviewer**, not a design-gate issue.

3. **CR-01 A10 / P3-01 open item** (remove client-trusted `ChatRequest.user_id`, populate identity
   from the verified token) is **not** in this task's scope — it lands with the authz/verify wiring
   in P3-04. `require_auth` + `CurrentUser` now provide the seam it will consume. Tracking only.
