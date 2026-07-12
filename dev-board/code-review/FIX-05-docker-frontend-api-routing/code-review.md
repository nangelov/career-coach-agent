# Code review — FIX-05-docker-frontend-api-routing · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | frontend/__tests__/apiProxy.test.ts | The regression guard tests the pure helper `buildApiRewrites`, not the actual integration point `next.config.ts::rewrites()`. The FIX-05 bug lived as a `NODE_ENV !== "development"` guard *inside* `rewrites()`. If someone re-introduces that guard by wrapping the `buildApiRewrites()` call in `next.config.ts` (`if (prod) return []; return buildApiRewrites()`), the helper unit test still passes and the exact regression returns undetected. | Optional hardening (defer acceptable): add a test that imports `next.config.ts` and asserts `await nextConfig.rewrites()` returns a non-empty `/api/:path*` rule, so the delegation wrapper is covered too. Current structure (helper has no NODE_ENV branch) makes this low-probability; not gating. |

## Notes
- **Build-vs-runtime nuance correctly handled.** `INTERNAL_API_URL` is set as a Docker **build ARG** in the builder stage (`frontend/Dockerfile:22-23`) and passed via `docker-compose.yml` `frontend.build.args` (not a runtime `environment:` entry). The engineer's empirical proof (sentinel build value wins over a differing runtime value) is convincing, and the design is robust *regardless* of whether `next start` re-reads config: the runner stage deliberately does **not** re-export `INTERNAL_API_URL`, and the frozen `routes-manifest.json` value is authoritative. Comments in `apiProxy.ts`, `next.config.ts`, `Dockerfile`, `docker-compose.yml`, and `.env.example` are all consistent and warn against the runtime-env mis-set. Good DRY (single seam) and SoC (pure, injectable helper).
- **Regression guard is real for the core property.** The new test asserts `buildApiRewrites()` emits the `/api/:path*` rule unconditionally with no NODE_ENV branch — which is the correct property since the helper is now NODE_ENV-independent by construction. Ran it locally: `6 passed`. This closes the "no automated coverage" gap the task flagged (subject to the C1 blind spot).
- **No-regression to `next dev`.** With `INTERNAL_API_URL` unset the destination resolves to `http://localhost:8000` — byte-identical to the removed dev-only rewrite. Default preserved for bare `next dev`/`next start`.
- **Correctness of `resolveInternalApiBaseUrl`.** Handles unset, blank/whitespace, and trailing-slash trimming (`/\/+$/`). No edge-case gaps.
- **Security.** `INTERNAL_API_URL` is server-side/build-time only, never `NEXT_PUBLIC_*`-inlined, so it never reaches the browser bundle; no secret leakage. The always-on same-origin proxy adds no new attack surface beyond a standard reverse proxy and avoids CORS entirely (browser origin stays `:3000`). No untrusted-input or execution concerns.
- **P11 not painted into a corner.** Default `localhost:8000` means a future single-container topology (backend on localhost:8000) still resolves correctly; the change is additive.
- **SSO reasoning verified as sound.** `redirect_uri` correctly points at the directly-exposed backend `:8000`, while login initiation proxies through `:3000` — no OAUTH_* env change needed, consistent with the live 302 evidence.
- Live docker-compose evidence (guest 201, SSO 302 to Google, profile 200, chat SSE round-trip through `:3000 → backend:8000`) is pasted and covers the full `/api/*` surface as the task required. Backend code unchanged; ruff/mypy/pytest untouched and green.
