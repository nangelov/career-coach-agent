/**
 * Single source of truth for the FastAPI backend origin (design §7.2).
 *
 * The browser only ever talks to the Next.js origin; the Next server reverse-proxies
 * `/api/*` to the backend. As of SEC-04 that proxy is the **BFF Route Handlers**
 * (`app/api/[...path]/route.ts` and the `app/api/auth/*` handlers) — not a transparent
 * `next.config.ts` `rewrites()` passthrough, which let the browser originate the call and
 * carry the token. This helper resolves the backend host those handlers forward to.
 *
 * The backend host is parameterized by `INTERNAL_API_URL` so the same source works in every
 * topology:
 *   - bare `next dev` / `next start` on a dev box → default `http://localhost:8000`
 *   - `docker compose` → `INTERNAL_API_URL=http://backend:8000` (compose service DNS)
 *
 * Unlike the old build-frozen `rewrites()` destination, the Route Handlers read
 * `INTERNAL_API_URL` at **request time** (Node runtime), so it may be provided as a runtime
 * `environment:` entry (a Docker build ARG is no longer required). The var is only ever read
 * by the frontend's Node process, never the browser, so it needs no `NEXT_PUBLIC_*` inlining
 * and the browser origin never changes (still same-origin, no CORS).
 */

/** The default backend origin when `INTERNAL_API_URL` is unset (preserves bare `next dev`/`next start`). */
export const DEFAULT_INTERNAL_API_URL = "http://localhost:8000";

/** Minimal shape of the process env we read (kept injectable for unit tests). */
export type ProxyEnv = Record<string, string | undefined>;

/**
 * Resolve the backend origin the BFF forwards to. Reads `INTERNAL_API_URL`, trims
 * surrounding whitespace and any trailing slash, and falls back to
 * {@link DEFAULT_INTERNAL_API_URL} when unset/blank.
 */
export function resolveInternalApiBaseUrl(env: ProxyEnv = process.env): string {
  const raw = env.INTERNAL_API_URL?.trim();
  const base = raw ? raw : DEFAULT_INTERNAL_API_URL;
  return base.replace(/\/+$/, "");
}
