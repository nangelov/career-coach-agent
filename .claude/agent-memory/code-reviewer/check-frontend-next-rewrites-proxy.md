---
name: check-frontend-next-rewrites-proxy
description: Reviewing frontend Next.js rewrites()/API-proxy + docker routing tasks (e.g. FIX-05) — build-time freezing, build ARG vs runtime env, regression-test-covers-helper-not-config gap
metadata:
  type: project
---

Reviewing Next.js `rewrites()` / same-origin `/api/*` proxy + docker-compose routing changes (first seen FIX-05).

**Why:** the app is same-origin by design — browser talks only to Next `:3000`, Next server reverse-proxies `/api/*` to FastAPI `backend:8000`. Client `lib/*` API clients default `baseUrl = ""`. The routing lives entirely in `frontend/next.config.ts::rewrites()` (delegating to `frontend/lib/apiProxy.ts`).

**How to apply — checks that matter here:**
- **Build-time freezing is real.** Next.js evaluates `rewrites()` during `next build` and freezes destinations into `.next/routes-manifest.json`; `next start` serves the frozen manifest and does not re-read the env var. So the backend host MUST be a Docker **build ARG** (Dockerfile builder stage) + docker-compose `build.args`, NOT a runtime `environment:` entry. Same gotcha as `NEXT_PUBLIC_*` inlining. Reject/flag any runtime-env attempt.
- **Regression-test blind spot (the classic here):** the pure helper `buildApiRewrites()` is unit-tested for "always emits the rule", but the original bug (a `NODE_ENV !== "development"` guard returning `[]`) lived in `next.config.ts::rewrites()`. A test on the helper does NOT catch re-introduction of that guard in the config wrapper. Note as minor unless the delegation is trivial; ideal fix is a test that imports `next.config.ts` and asserts `await nextConfig.rewrites()` is non-empty.
- Confirm default (unset env) preserves bare `next dev`/`next start` behavior (`http://localhost:8000`) — no dev-workflow regression.
- `INTERNAL_API_URL` is server/build-time only, never `NEXT_PUBLIC_*` → no browser-bundle leakage, no CORS (browser origin unchanged). Good.
- SSO: `redirect_uri`/OAUTH_* point at the directly-exposed backend `:8000`, not the proxy — usually no change needed; verify against pasted 302 evidence.
- This class of routing bug is only caught by a live `docker compose up` run, not unit tests — require pasted evidence across the whole `/api/*` surface (guest 201, SSO 302, profile 200, chat SSE round-trip), not just one endpoint.
