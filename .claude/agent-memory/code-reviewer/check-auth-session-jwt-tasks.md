---
name: check-auth-session-jwt-tasks
description: Reviewing P3 auth/session tasks (guest session, SSO, session-JWT codec, authz/rate-limits) — token-codec security checks and known deferrals
metadata:
  type: project
---

Reviewing P3 auth work (P3-01 guest session, P3-02 SSO/OIDC, P3-04 authz/rate-limits, …). The backend
mints its own session JWT (backend is the session owner, §6.2/§7.1) via a shared codec in
`app/security/tokens.py` using **joserfc** (Authlib's successor JOSE lib). Token claims:
`sub`/`role`/`sid`/`iat`/`exp`, `role ∈ {guest,user}`; guest `sub == sid == session_id`.

**Token-codec security checks (verify every revision that touches signing/verify):**
- `decode` must pin `algorithms=[configured]` — blocks alg-swap / `alg:none`. (P3-01 did this.)
- `exp` must be *essential* (a token with no exp must not validate) AND validated against now.
  joserfc: `jwt.decode` checks signature only; claim/expiry validation is a separate
  `JWTClaimsRegistry(exp={"essential": True}).validate(...)` call. Confirm both run.
- Claims re-validated through a typed model (Pydantic `SessionClaims`) so an unknown `role` is rejected.
- All joserfc/validation errors wrapped in one codec-owned exception (`InvalidSessionToken`) → callers
  never import joserfc error types; P3-02's verify dep maps it to 401.
- Signing key only from `JWT_SECRET_KEY` (required, no default in config); empty secret must fail at
  construction, not at first sign.

**joserfc dependency:** app code imports `joserfc` directly but pyproject declares only `authlib>=1.3.0`
(joserfc arrives transitively; pinned in uv.lock). Flag as **minor** — recommend an explicit
`joserfc>=1.6.0` in pyproject since the signing path imports it directly and old authlib predates the split.

**P3-02 SSO/OIDC posture (don't re-flag as blockers in P3-03/P3-04):**
- Identity resolved via the provider **userinfo endpoint** (not id_token/JWKS) using the just-issued
  access token over TLS — a documented deliberate simplification; PKCE(S256)+single-use `state` cover
  code-interception/CSRF. Account identity is keyed on `(provider, sub)` (`uq_users_provider_sub` upsert),
  **not email** — so `email_verified` is NOT load-bearing (no takeover via unverified email). Note only.
- A `nonce` is generated + stored in the OAuth-state record but **never validated** (no id_token) — dead
  security artifact; nit, not a gate. If future work adds id_token/JWKS, use or drop it.
- OIDC callback declares `code`/`state` as required `Query(...)` → a provider `error=access_denied` (user
  denies consent) yields 422 not a graceful redirect. Minor UX gap, tested as `test_callback_missing_params_422`.
- Token delivered to SPA in the redirect **URL fragment** (not query) — deliberate (no server-log/Referer
  leak); browser-history exposure is the accepted SPA tradeoff, documented. Note only.
- Logout = delete Redis session record; `SessionAuthenticator.authenticate` requires a live record → immediate
  revocation w/o denylist. `test_logout_revokes_session` proves the post-logout 401. Good pattern.

**P3-03 guest→account upgrade (don't re-flag these; sound patterns):** upgrade binds via a server-minted,
opaque, single-use, short-lived **upgrade ticket** — `POST /api/auth/upgrade` (guest-authed, 409s non-guest)
mints it from the *verified* `current_user.session_id` (never a client id); `begin_login` **pops** it before
the cross-origin redirect (so a Referer leak to the IdP carries a dead ticket) and stashes the guest sid in the
OAuth-state record. Carryover keeps the **same session_id** (Redis working memory untouched) + promotes the
record in place + best-effort backfills the clean user↔assistant transcript via `ConversationStore.persist_turn`
(`conversation_id=None` per turn is idempotent get-or-create → one conversation). `upgrade()` returns False
(→ fresh session) when session lapsed/already-user, making replay + double-callback no-ops.
- **Recurring check — in-place role promotion leaves the lower-privilege token valid.** `SessionAuthenticator.
  authenticate` derives role from `claims.role`, NOT `record.role`. When a session record is promoted in place
  (guest→user) without deleting it, the pre-upgrade guest JWT keeps resolving as `role=guest` for the now-user
  session until TTL. Flag as **minor** (same-principal, no user-scoped escalation; keeping the session_id is
  required for carry-over) — but always check it whenever a task mutates a session record's role/owner in place.

**Guest-creation abuse gap:** `POST /api/auth/guest` is (correctly) unauthenticated; each call writes a
24h-TTL Redis record. P3-04's per-session 10-msg/1-upload limit does NOT cover session *creation* rate —
no task owns that Redis-growth/DoS surface. Flag as minor/note, don't gate (edge/proxy layer may cover it).

**Stores:** `SessionStore` port in `services/session_store.py` (+ `InMemorySessionStore` test double),
Redis adapter `RedisSessionStore` in `repositories/redis.py` (key prefix `session:record`, per-create TTL
floored at 1). `SessionRecord`/`SessionRole` schema is generic over guest/user (P3-02 reuses with
`user_id` set) — that's intended DRY, not YAGNI. `AppStateKeys.AUTH_SERVICE` follows the StrEnum
app.state-key convention (see [[check-cross-cutting-drift]]).

Related: [[check-cross-cutting-drift]], [[check-persistence-rehydration-tasks]], [[check-fastapi-request-anno]].
