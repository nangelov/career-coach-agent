# Architecture review — FIX-05-docker-frontend-api-routing · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Same-origin / avoid CORS (`next.config.ts` "avoid CORS and hard-coded hosts"; §7/§11 data-min posture) | A routing fix that keeps browser on one origin, no hard-coded backend host in the client bundle | Always-on `rewrites()` proxy `/api/:path*` → `${INTERNAL_API_URL}/api/:path*`; browser talks only to `:3000`; `baseUrl=""` client seam untouched; no CORS opened | None |
| A2 | Frontend structure / transport in `lib/` ([[project-frontend-sse-pattern]]) | Reusable transport/config logic lives in `frontend/lib/`, thin `next.config.ts` | Pure helper `lib/apiProxy.ts` (`resolveInternalApiBaseUrl`/`buildApiRewrites`); `next.config.ts` delegates | None |
| A3 | Config seam / DRY-KISS | One env-driven destination, no parallel mechanism | Single `INTERNAL_API_URL`, trimmed + trailing-slash-normalized, one rewrite rule; no client-bundle edits | None |
| A4 | Phase fit — do not implement P11 (plan.md P11; §8/§11 single-container) | Make local `docker compose` work now; leave HF Spaces single-container routing to P11 | Scope limited to compose two-container topology; no Dockerfile-merge/single-container work; default `localhost:8000` is forward-compatible with P11 co-located backend | None |
| A5 | Locked decisions untouched (SSO-only, Postgres+Redis only, no managed tier) | Routing-only change, no auth/datastore drift | OAuth `redirect_uri`/post-login URLs unchanged and still correct (verified live 302 to Google); no new service/datastore | None |
| A6 | Budget posture (§11 free/OSS/self-hosted) | No extra infra | Reuses the Next server as the proxy; no added reverse-proxy container | None |

## Cross-cutting checks
- [x] Fits target structure — frontend/infra change; transport helper correctly in `lib/`; no backend layering touched
- [x] Honors locked decisions (SSO redirect URLs unchanged; Postgres+Redis+compose topology intact; no managed tier)
- [x] Interfaces-before-implementations — `baseUrl` DI seam and `apiProxy` helper are the seams; no bypass
- [x] Budget posture respected (no new container/service)

## Notes
- **P11 is de-risked, not boxed in.** The `INTERNAL_API_URL` default `http://localhost:8000` means the single-
  container HF Space (backend co-located on localhost:8000, per plan.md P11 / §8) works with zero change to this
  rewrite. The build-ARG design is a documented, self-contained knob — P11 can keep it, or move to a merged
  single-origin Dockerfile, without unwinding anything here. No corner painted.
- **Build-ARG-not-runtime is the correct call and is well-documented** (Dockerfile, `apiProxy.ts`, compose
  comment, `.env.example`). Next freezes `rewrites()` into `routes-manifest.json` at build; a runtime
  `environment:` entry would silently regress. Engineer proved this empirically — the right rigor for an
  infra-timing gotcha.
- Regression test (`__tests__/apiProxy.test.ts`) asserts the proxy is emitted **unconditionally** — it locks in
  the exact FIX-05 failure mode (rewrite disabled outside `next dev`) so `npm test` catches recurrence.
- Live docker-compose evidence spans guest auth (201), SSO (302 to Google), profile (200), and a full chat SSE
  round-trip through `:3000 → backend:8000` — routing conformance demonstrated across the `/api/*` surface, not
  asserted.
- No follow-up owed. Design ruling recorded to system-architect memory for P11 reference.
