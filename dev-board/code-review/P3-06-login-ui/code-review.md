# Code review — P3-06-login-ui · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | frontend/components/Chat.tsx:208-215 | `handleStop` awaits `cancelChat` with no try/catch; wired as `onClick={() => void handleStop()}`. A network failure on the cancel POST becomes an unhandled promise rejection (cancel is inherently best-effort). | Wrap the `cancelChat` call in try/catch and swallow/log the failure, mirroring the best-effort posture of `logout()` in `lib/auth.ts`. |
| C2 | nit | frontend/lib/chatStream.ts:78-82, 304-315 | `RateLimitedEvent.retryAfter` is parsed from the `Retry-After` header and plumbed all the way through, but `Chat.tsx` only consumes `message` — `retryAfter` is never surfaced (no countdown / disabled state). | Either use it (e.g. a "try again in Ns" hint or a disabled window) or drop the field to avoid dead data; acceptable to defer if a follow-up UI task will consume it. |
| C3 | nit | frontend/__tests__/Chat.test.tsx:56-60 | Stale comment "The request carried the client-generated session id" — the id is now seeded from a stored session, not client-minted (the whole point of this task). | Update the comment so it does not imply the removed client-minting behavior. |

## Notes
- **Backend contract verified end-to-end.** The frontend matches `backend/app/api/auth.py` and `schemas/auth.py`: guest POST expects 2xx (backend 201), upgrade POST expects 2xx (backend 201) and reads `upgrade_ticket`, logout POST fire-and-forget (backend 204), and the callback fragment fields (`access_token`/`token_type`/`session_id`/`role`/`expires_in`) exactly match `sso_callback`'s `urlencode` payload. The 401→`auth_error` and 429→`rate_limited` mapping matches `require_auth` (401) and `rate_limit_exceeded_http` (429 with `detail` + `Retry-After`) in `security/dependencies.py`.
- **Security — token in localStorage (accepted, not gating).** Storing the session JWT in `localStorage` exposes it to XSS, but this is forced by the P3-02 contract, which delivers the token in the URL *fragment* (no httpOnly cookie is available to the SPA). The engineer's rationale is sound and consistent with design §7.1; expiry is enforced on load and the token is cleared on logout/401. Flagging as an accepted risk for the record, not a change request. The callback page correctly `router.replace("/")`s to drop the token-bearing fragment from history.
- **Own-data-only preserved.** The client sends `session_id: session.sessionId` and the backend re-derives identity from the verified token (`authorize_session_access`), so the client cannot spoof another session. `user_id` is never sent from the client.
- **Injection-safe.** `sessionFromFragment` uses `URLSearchParams` (decodes fragment values); `beginSsoLogin` `encodeURIComponent`s the provider and upgrade ticket. No `dangerouslySetInnerHTML`, no eval-style execution.
- **Guest-upgrade fallback correct.** `UpgradePrompt.handleUpgrade` attempts the session-preserving ticket flow and, on any failure, falls back to a plain `beginSsoLogin` rather than dead-ending the user.
- **Layering respected** (§8): transport/auth logic in `lib/`, UI in `components/`, route in `app/`; components depend on `lib`, not vice versa. DI of `fetchImpl`/`navigate` keeps pure paths testable.
- **Verification reproduced:** `npm test` → 6 suites / 50 tests pass; `tsc --noEmit` clean; `next lint` clean. Tests meaningfully cover render + button→fetch/navigation, token attachment, 401 fallback, 429 upgrade prompt, and callback fragment parse/failure.
- All four acceptance criteria are met. The three findings above are minor/nit and do not gate; the engineer may address or defer them in a follow-up.
