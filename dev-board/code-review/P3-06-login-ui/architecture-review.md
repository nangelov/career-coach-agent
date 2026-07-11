# Architecture review — P3-06-login-ui · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 frontend structure | `app/` routes, `components/` (incl. auth), `lib/` (api client + auth) | `app/auth/callback/page.tsx` (route), `components/Login.tsx` + `components/UpgradePrompt.tsx` (auth UI), `lib/auth.ts` (auth client) | None — placement is exact. |
| A2 | Layering (Router→Service split mirror) | transport/auth logic in `lib/`, UI in `components/`, thin route in `app/`; deps point components→lib, not the reverse | `lib/auth.ts` + `lib/chatStream.ts` are DOM-light and import no components; `Login`/`UpgradePrompt`/`Chat`/callback page import from `lib` only | None. Consistent with blessed P1-08 SSE layering ([[project-frontend-sse-pattern]]). |
| A3 | SSO-only auth, no passwords (§6.2/§7.1, locked decision) | Google + LinkedIn + guest entry; no password field anywhere | `Login.tsx` renders 2 SSO buttons + "Continue as guest"; SSO via full-page redirect to backend `GET /api/auth/login/{provider}`; no credential inputs | None. |
| A4 | Frontend/backend token contract (schemas/auth.py) | mirror `GuestSessionResponse`/`SessionResponse` (`access_token`, `token_type`, `session_id`, `role`, `expires_in`); uniform for guest+user | `sessionFromPayload`/`sessionFromFragment` map exactly those fields; single `Session` type for both roles | None — field-for-field match. |
| A5 | OIDC callback delivery (§7.1, P3-02) | backend 302s to `OAUTH_POST_LOGIN_REDIRECT` with token in URL **fragment**; SPA reads it client-side | `config.OAUTH_POST_LOGIN_REDIRECT` default `.../auth/callback` matches the `app/auth/callback` route; page parses `window.location.hash`, persists, `router.replace("/")` | None — route and config default are aligned. |
| A6 | Bearer attached on protected calls (P3-04, §7.1) | every `/api/chat` + cancel call carries `Authorization: Bearer <jwt>`; identity from token not body | `streamChat`/`cancelChat` accept `token`, set the header; `Chat` passes `session.accessToken`; 401→login fallback | None. Aligns with blessed [[project-authz-ratelimit]] (token-derived identity). |
| A7 | Guest rate-limit → upgrade prompt (§5/§6.8, Decision-8) | 429 surfaces "upgrade to continue", not a raw error | transport maps 429→`rate_limited` (carries backend `detail`+`Retry-After`); `Chat` renders `UpgradePrompt` | None. |
| A8 | Upgrade-to-account preserves session (§4, P3-03) | server-minted single-use ticket carried into SSO login; no client-supplied guest id | `upgradeGuestToSso` → `POST /api/auth/upgrade` (guest bearer) → ticket appended to login URL; falls back to plain login on failure | None — matches blessed [[project-guest-upgrade]] ticket pattern exactly. |
| A9 | Data ownership — guests Redis-only (§4) | frontend holds only a token; backend enforces store boundary | client is store-agnostic; role indicator is display-only | None. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (lib←components←app; no reverse deps)
- [x] Honors locked decisions (SSO-only Google/LinkedIn + guest, no passwords; backend-owned session JWT as Bearer; Next.js App Router; fragment token delivery per P3-02)
- [x] Interfaces-before-implementations — `lib/auth.ts` is the single frontend auth contract mirroring `schemas/auth.py`; flows take injectable `fetchImpl`/`navigate` seams
- [x] Budget posture respected — no paid/managed frontend services introduced

## Notes
- **Token storage = localStorage (design risk, accepted, not a gate).** The engineer correctly checked P3-02 and found the token is delivered in the URL *fragment* (§7.1 — deliberate so it never reaches server logs/Referer), so an httpOnly cookie is not available and the token can only live client-side. This is a settled consequence of the already-blessed P3-02 fragment design ([[project-auth-session-seam]]), not a new deviation — I am not relitigating it. The residual XSS-exposure of localStorage is inherent to any client-readable token. Logged follow-up (cheap to revisit, not now): if a future task reworks the callback to let the backend set a session cookie, prefer httpOnly over localStorage. Non-blocking.
- **Minor DRY (non-blocking):** `lib/auth.authHeaders(session)` and `chatStream`'s inline `Authorization: Bearer ${token}` both construct the header. Intentional SoC — `chatStream` stays decoupled from the `Session` model by taking a raw `token` string — so this is acceptable, not a required change. Engineer may leave as-is.
- **Chat is now auth-gated** (renders `<Login>` with no session). This is the correct product surface for P3 given P3-04 requires a bearer on `/api/chat`; the test updates that seed a session are a legitimate behavior change, not weakened coverage.
- Phase fit: squarely P3; no premature coupling to later phases (no profile/memory/PDP surfaces pulled forward).
