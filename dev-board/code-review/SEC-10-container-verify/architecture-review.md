# Architecture review — SEC-10-container-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Port lockdown (§7.2 / §6.12) | Only Next `frontend` publishes a host port; `backend`/`db`/`redis` internal-network-only | `docker-compose.yml`: only `frontend` has `ports: 3000:3000`; backend/db/redis/worker publish no host port (healthcheck curls localhost *inside* container). Live: :3000 → 200, :8000/:5432/:6379 → connection refused | None — matches [Docker API routing] ruling (runtime `INTERNAL_API_URL`, same-origin) |
| A2 | httpOnly + token-free cookie (§6.13 / §7.2) | Guest body carries no access token; JWT lives only in an httpOnly cookie | `app/api/auth/guest/route.ts` returns `{sessionId,role,expiresAt}` only; `setSessionCookie` sets `httpOnly:true` (+`Secure` in prod). Live: body token-free, `Set-Cookie` has `HttpOnly` | None — matches blessed [BFF session transport] |
| A3 | Server-side Authorization injection (§7.2) | BFF injects `Bearer` from the cookie server-side against the real backend; browser never carries the token | `lib/bffProxy.ts` strips client `cookie`/`authorization`, injects `Authorization: Bearer <token>` from the httpOnly cookie; catch-all `[...path]/route.ts` routes all non-auth `/api/*` through it. Live: `GET /api/profile` 200 with cookie, 401 without | None. Engineer correctly proved this via `/api/profile` (backend-hitting) rather than `/api/auth/session` (local cookie-decode only) — the right architectural distinction |
| A4 | Consent gate (§6.22) | Guest start rejected without consent, enforced backend-side | Guest handler forwards `{consent}` (fail-closed default false); backend is the real enforcer. Live: `consent:false` → 400 | None |
| A5 | SSE never raises into stream (§7.2 guardrail) | Stream always ends cleanly even on model failure | Live: `/api/chat` streamed `start`→`plan`→fallback `token`→`error` `done` end-to-end through the BFF; real LLM call blocked by sandbox DNS egress, not code | None — observed behavior is the designed graceful-degradation guardrail |
| A6 | No code changes on a (T) verify task | Verification-only; fix only genuine defects | Zero files changed; no defect surfaced | None — correct posture for a phase-exit (T) task |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — no source touched; BFF/compose seams unchanged
- [x] Honors locked decisions — Postgres+Redis 5-service stack, SSO/BFF cookie posture, no ReAct parser (untouched)
- [x] Interfaces-before-implementations — n/a (no code changed)
- [x] Budget posture respected — self-hosted stack, no paid tier introduced

## Notes
- SEC-09's gap (leaned on reported suites; never booted the full stack after SEC-03 port lockdown + SEC-04 BFF rework) is genuinely closed: the two highest-risk changes are now proven live, not just via unit tests — port lockdown confirmed by real connection-refused on 8000/5432/6379, and BFF auth injection confirmed by 200-with-cookie / 401-without against the *live* backend.
- 495 passed / 54 skipped backend is expected-by-design: the 54 skips are live-DB integration tests that skip when no host Postgres is reachable — consistent with the standing [CI posture] ruling (skip-not-fail).
- Honestly documented sandbox limits (no HF egress → real LLM token gen; no OIDC secrets → real SSO callback) meet the §6.17 honesty standard and are out of this task's scope; the guest + BFF-auth paths SEC-10 targets are fully covered.
- Follow-up (not blocking): real SSO login/callback and a real end-to-end LLM stream remain unverified in this sandbox — worth confirming in a deploy/staging env with real provider creds before P12.
