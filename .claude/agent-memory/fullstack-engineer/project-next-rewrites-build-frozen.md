---
name: next-rewrites-build-frozen
description: Next.js rewrites()/redirects/headers are evaluated at build time and frozen into routes-manifest.json; env vars in a rewrite destination must be passed as Docker build ARGs, not runtime environment
metadata:
  type: project
---

Next.js evaluates `next.config.ts` `rewrites()` (also `redirects`/`headers`) at **build time** (`next build`) and freezes the resolved result into `.next/routes-manifest.json`. `next start` serves that static manifest and does **not** re-read the config's env vars.

**Why:** verified empirically for FIX-05 — built with `INTERNAL_API_URL=sentinel`, the manifest had the sentinel baked in; running `next start` with a *different* runtime `INTERNAL_API_URL` still proxied to the build-time value.

**How to apply:** any env var used inside a rewrite `destination` (e.g. an `/api/*` reverse-proxy backend host) that must vary per deployment has to be passed as a Docker **build ARG** (`Dockerfile ARG/ENV` + docker-compose `build.args`), NOT a runtime `environment:` entry. Same build-time-freezing rule as `NEXT_PUBLIC_*` client vars. The frontend's same-origin `/api/*` proxy lives in `frontend/lib/apiProxy.ts` (pure, unit-tested helper) consumed by `next.config.ts`; the rewrite is intentionally always-on (not dev-only) so `docker compose` works — guarded by a jest regression test.
