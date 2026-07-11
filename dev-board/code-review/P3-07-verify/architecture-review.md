# Architecture review — P3-07-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure / phase-exit posture | Verification-only `(T)` task: one new test module, **no** product code/endpoints/schema/migrations ([[project-phase-exit-verification]]) | Single new file `backend/tests/test_p3_exit_verification.py`; engineer.md confirms no other files touched | None |
| A2 | Layering (Router→Service→Agent/Repo) | Exit test drives the phase's real seams end-to-end, faking only at ports | Real router stack (`app.main.app`) + real `SessionAuthenticator`, `GuestAuthService`, `SsoAuthService`, `GuestUpgradeService`, `RateLimitService`; only `ChatService`/`ConversationStore`/OIDC/stores are port-level fakes | None — see Notes N1 |
| A3 | §7.1 AuthZ — identity from token, not body | `user_id` derived from verified token; own-data-only enforced ([[project-authz-ratelimit]]) | `test_sso_flow…` asserts `invocations[-1][1] == claims.sub`; router path (`chat.py:94,105`) confirmed to use `authorize_session_access` + `current_user.user_id` | None |
| A4 | §4/§6 Decision-8 guest cap | Guest = 10 msg/session, Redis-enforced, 11th denied with upgrade prompt | `test_guest_flow…`: 10×200 then `429` + `Retry-After` + "Sign in" detail | None |
| A5 | P3-03 guest→account upgrade | In-place same-`session_id` promotion + transcript backfill at upgrade boundary ([[project-guest-upgrade]]) | `test_upgrade_preserves…`: same `session_id`, record `role` guest→user, backfill persisted once, promoted token continues on same session | None |
| A6 | P3-02 SSO / session lifecycle | `login`→`callback` mints backend-owned session JWT; logout deletes the session record ([[project-auth-session-seam]]) | `test_sso_flow…` (mints decodable `role="user"` JWT bound to sid) + `test_logout_revokes…` (same token → 401 after logout) | None |
| A7 | §7 AuthZ cross-user | User A cannot read/cancel user B's session (403), rejected before service | `test_cross_user_access_is_denied`: chat+cancel → 403, only A's own session reaches the fake service | None |
| A8 | Locked decisions / budget posture | SSO-only, Postgres+Redis-only via ports, no network in tests, free/OSS | No-network `_MultiUserOIDCClient`, in-memory port impls, no HF/Redis/PG driver reached | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — test-only, drives the real router/service/port layering through HTTP
- [x] Honors locked decisions (SSO-only auth; Postgres+Redis-only via ports; no ReAct parser touched; no paid deps)
- [x] Interfaces-before-implementations — fakes are supplied at the real ports (`OIDCClient`, `ConversationStore`, `RateLimiter`, `SessionStore`, `ChatService`), proving the seams compose
- [x] Budget posture respected (in-memory ports, no live network/DB, free/OSS)

## Notes
- **N1 (design risk, not a gate) — port-level fakes vs. live-adapter posture.** The blessed
  phase-exit pattern ([[project-phase-exit-verification]]) had P2-08 exercise the *real*
  `PostgresConversationStore` adapter with skip-not-fail. P3-07 instead runs entirely over
  in-memory port implementations (`InMemorySessionStore`, `InMemoryRateLimiter`, etc.), so the
  `RedisRateLimiter` fixed-window adapter and Redis session-store adapter are **not** touched by
  this exit proof. This is defensible: P3's exit criteria are *functional* auth/session/authZ
  flows, and the phase-relevant seams (authenticator, guest/SSO/upgrade/rate-limit services, the
  real router) are all real. Adapter correctness remains the concern of the P3-01/P3-04 per-task
  suites. Accepted as-is; logged so a future live-integration sweep (or the P5 repo-owner-filter
  follow-up in [[project-authz-ratelimit]]) can add a Redis-adapter-backed pass if desired.
- **N2 (blessed) — local `_MultiUserOIDCClient` over widening the shared `FakeOIDCClient`.** The
  cross-user criterion needs two distinct `sub`s, which the fixed-`sub` shared fake cannot produce.
  Keeping a per-code identity map local to this module (YAGNI — no other suite needs multi-user)
  matches the accepted self-contained-per-file convention. Good call.
- **N3 (blessed) — faking `ChatService` at the auth boundary.** Correct scoping: the model⇄tools
  loop and logged-in persistence are P1/P2 concerns (already verified with real implementations);
  "now persisting" is proven via the real upgrade-backfill mechanism, not the chat loop.

No design deviations that would be expensive to unwind. Conforms to the P3 exit criteria and all
prior P3 rulings.
