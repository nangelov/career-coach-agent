---
name: project-docker-api-routing
description: Blessed FIX-05 frontend→backend routing — always-on same-origin Next rewrite proxy, INTERNAL_API_URL build ARG
metadata:
  type: project
---

FIX-05 blessed the frontend→backend routing fix for `docker compose up`.

**Ruling:** always-on Next.js `rewrites()` proxy (dev-only guard removed) forwarding
`/api/*` from the `:3000` origin to the backend, destination parameterized by
`INTERNAL_API_URL` (default `http://localhost:8000`; compose sets `http://backend:8000`).
Same-origin = no CORS, no `NEXT_PUBLIC_*` client inlining, `baseUrl=""` DI seam preserved.
Logic is a pure `lib/apiProxy.ts` helper (`resolveInternalApiBaseUrl`/`buildApiRewrites`).

**Why:** matches the `next.config.ts` "avoid CORS and hard-coded hosts" preference and
§7/§11 data-min posture; adds no reverse-proxy container (budget §11).

**How to apply:** `INTERNAL_API_URL` MUST be a Docker **build ARG**, not a runtime env —
Next freezes `rewrites()` into `routes-manifest.json` at build; `next start` ignores
runtime env. The `localhost:8000` default is forward-compatible with the P11 single-
container HF Space (co-located backend on localhost:8000 needs zero change) — do NOT
treat this proxy as boxing in P11. See [[project-frontend-sse-pattern]] (lib/ transport)
and [[project-frontend-path]] (canonical `frontend/`).
