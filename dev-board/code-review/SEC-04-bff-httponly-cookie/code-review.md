# Code review — SEC-04-bff-httponly-cookie · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| — | — | — | No blocking or major findings. Both revision-1 findings (C1, C2) verified fixed against current source. | — |

## Re-review of revision-1 findings
- **C1 (major) — OAuth `redirect_uri` topology — FIXED.** Verified in current source, not just the report:
  - `.env.example` — `OAUTH_REDIRECT_BASE_URL=http://localhost:3000`; comment rewritten to "FRONTEND / Next origin" with the SEC-03 reasoning (backend has no published port, so the browser-facing callback must land on the Next origin where the BFF forwards server-side). `OAUTH_POST_LOGIN_REDIRECT` comment now correctly states the fragment is consumed server-side only.
  - `backend/app/config.py:182-206` — `OAUTH_REDIRECT_BASE_URL` default → `http://localhost:3000`; docstring now describes the frontend/Next origin + BFF-forwarding chain and instructs registering the same value in the provider console. The previously-false `OAUTH_POST_LOGIN_REDIRECT` docstring is corrected to "consumed server-side only by the Next.js BFF callback Route Handler." No backend logic touched (`_redirect_uri` derivation unchanged), consistent with the constraints.
- **C2 (nit) — silent login failure — ADDRESSED.** `frontend/app/api/auth/login/[provider]/route.ts:35-38` now redirects to `/?login_error=<reason>` (`unknown_provider` for 404, `provider_unavailable` otherwise). Both branches covered by `__tests__/bffAuthRoutes.test.ts:153,164`.

## Notes
- The revision-1 clean-bill items (token never in browser JS/URL; Authorization injected only by the BFF with client `authorization`/`cookie` stripped; cookie posture httpOnly/Secure-prod/SameSite=Lax/maxAge tracking `exp`; server-only isolation of `bffSession`/`bffProxy`; Dockerfile ARG→runtime reversal is correct and not a FIX-05 regression) were not disturbed by the revision-2 changes — the diff is confined to two config files and the login Route Handler.
- `login_error` is now emitted into the URL but no UI component reads it yet — the signal exists for a future UI toast/message but is not surfaced today. This is acceptable (C2 was a nit and UI messaging wiring is out of scope), noting it so it isn't mistaken for wired-up feedback.
- **Still owed (carried from rev1, non-gating):** a one-time live `docker compose up` SSE incrementality check for `POST /api/chat`. The unit test only proves `response.body` is a `ReadableStream`, not true per-chunk delivery, and Next's outbound `compress` is not explicitly disabled for `text/event-stream`. Recommend verifying before this ships to production.

## Verdict: APPROVED
