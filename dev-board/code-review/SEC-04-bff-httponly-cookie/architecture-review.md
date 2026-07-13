# Architecture review — SEC-04-bff-httponly-cookie · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §7.2 BFF, not transparent proxy | `rewrites()` passthrough removed; Route Handlers hold session + inject `Authorization` server-side | `next.config.ts` drops `/api/*` rewrites; catch-all `app/api/[...path]/route.ts` + `lib/bffProxy.proxyRequest` inject `Bearer` from cookie, strip client-supplied `authorization`/`cookie` | none |
| A2 | §6.13 httpOnly cookie posture | httpOnly · Secure · SameSite=Lax; token never in JS | `setSessionCookie`: httpOnly, secure=prod-only, sameSite=lax, path=/, Max-Age tracks JWT `exp`. No `localStorage`/`accessToken`/`authHeaders` remain (grep: comments only) | none. Secure-prod-only matches task ("Secure in production") |
| A3 | §7.2 no token in URL | OIDC callback sets cookie, no token fragment reaches browser | Backend keeps server-to-server fragment redirect (documented in `auth.py`); BFF callback handler extracts token Node-side, sets cookie, redirects browser to clean `/auth/callback`; client page hydrates via `/api/auth/session` | none |
| A4 | §7.2 SSE passthrough survives | Stream backend body straight through, no buffering | catch-all `runtime="nodejs"` + `force-dynamic`; returns `backendResponse.body` verbatim, strips `content-encoding`/`content-length`/`transfer-encoding` | none |
| A5 | §8 structure | `frontend/app/api/` = BFF Route Handlers; transport in `lib/` | New handlers under `app/api/*`; pure token/cookie/proxy logic in `lib/bffSession.ts` + `lib/bffProxy.ts` (import-light, DI-testable) | none — matches §8 line 644 |
| A6 | §7.2 security headers / CSP; CORS closed | Baseline headers on Next origin; no `ACAO: *` | `next.config.ts` adds CSP, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`; backend `ALLOWED_ORIGINS` untouched (out of SEC-04 diff) | none (see Note 1) |
| A7 | FIX-05 single backend-URL source | Keep `resolveInternalApiBaseUrl()` as sole resolver | `bffProxy.resolveBackendUrl` + `proxyRequest` both route through it; no second URL path | none |
| A8 | §7.5 / task S13 non-goal | No consent/rate-limit logic added; handlers extensible | Guest handler kept open with documented seam for later ToS check; authN/authZ untouched | none |
| A9 | Layering (Router→Service→…) | Backend logic unchanged | `backend/app/api/auth.py` = comment only; BFF is a thin frontend transport layer | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — BFF confined to `frontend/app/api/*` + `lib/`; backend untouched beyond a comment
- [x] Honors locked decisions — SSO-only/PKCE preserved; Postgres+Redis-only unaffected; no AuthN/AuthZ change
- [x] Interfaces-before-implementations — cookie/proxy split into pure `bffSession`/`bffProxy` seams (injectable `fetchImpl`/`env`)
- [x] Budget posture — no new services; no reverse-proxy container added (§11)

## Notes
1. **CSP `script-src 'unsafe-inline' 'unsafe-eval'`** partially undercuts the XSS-defense rationale that motivates the httpOnly cookie (§7.2). Documented as a deliberate tradeoff (Next inline bootstrap; nonce-based CSP is a larger separate change). Acceptable for this task with a **logged follow-up** to tighten to a nonce-based policy; severity is the code-reviewer's call, not a design blocker.
2. **FIX-05 reversal is correct, not a regression.** SEC-04 moves `INTERNAL_API_URL` from Docker build ARG → runtime `environment:`. The FIX-05 build-ARG ruling was mechanism-specific: Next freezes `rewrites()` into the build manifest, so a runtime var was ignored. The BFF Route Handlers (`force-dynamic`, nodejs) read `INTERNAL_API_URL` at request time, so a runtime env is the correct shape. Blessed as an evolution; the `localhost:8000` default stays P11-compatible.
3. Backend fragment-redirect kept server-to-server-only with a clear in-code warning against "fixing" it back into a browser-facing pattern — exactly the reviewer-durability the task asked for.
4. `backend/` (graph/responder/web_searcher/guardrails/structuring/chat/fakes) changes in the working tree belong to SEC-01/SEC-02 and are out of SEC-04 scope — not reviewed here.
