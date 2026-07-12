/**
 * Server-side API proxy configuration for the Next.js `rewrites()` hook (see
 * `next.config.ts`).
 *
 * Every browser-side API call in this app targets a **same-origin** path
 * (`${baseUrl}/api/...` with `baseUrl` defaulting to `""` — see `lib/auth.ts`,
 * `lib/chatStream.ts`, `lib/profile.ts`). The browser therefore only ever talks
 * to the Next.js origin (`:3000`); the Next.js server reverse-proxies `/api/*`
 * to the FastAPI backend. This keeps us **same-origin (no CORS)** and avoids
 * hard-coding the backend host into the client bundle.
 *
 * The proxy runs in **all** environments (not just `next dev`): under
 * `docker compose up` the frontend and backend are separate containers/origins
 * with no reverse proxy in front, so without this rewrite the browser's
 * `/api/*` calls 404 inside the Next.js server itself (this file fixes
 * FIX-05-docker-frontend-api-routing).
 *
 * The backend host is parameterized by the `INTERNAL_API_URL` env var so the
 * same source works in every topology:
 *   - bare `next dev` / `next start` on a dev box → default `http://localhost:8000`
 *   - `docker compose` → `INTERNAL_API_URL=http://backend:8000` (compose service DNS)
 *
 * IMPORTANT — this is read at **build time**, not container runtime: Next.js
 * evaluates `rewrites()` during `next build` and freezes the resolved
 * destination into `.next/routes-manifest.json`; `next start` serves that static
 * manifest and does **not** re-read `INTERNAL_API_URL`. So docker-compose must
 * pass it as a Docker **build ARG** (`build.args`), not a runtime `environment:`
 * entry. (Verified empirically for FIX-05.) The var is only ever read by the
 * frontend's Node process, never by the browser, so it needs no `NEXT_PUBLIC_*`
 * client inlining and the browser origin never changes (still no CORS).
 */

/** The default backend origin when `INTERNAL_API_URL` is unset (preserves bare `next dev`/`next start`). */
export const DEFAULT_INTERNAL_API_URL = "http://localhost:8000";

/** Minimal shape of the process env we read (kept injectable for unit tests). */
export type ProxyEnv = Record<string, string | undefined>;

/**
 * Resolve the backend origin the `/api/*` rewrite forwards to. Reads
 * `INTERNAL_API_URL`, trims surrounding whitespace and any trailing slash, and
 * falls back to {@link DEFAULT_INTERNAL_API_URL} when unset/blank.
 */
export function resolveInternalApiBaseUrl(env: ProxyEnv = process.env): string {
  const raw = env.INTERNAL_API_URL?.trim();
  const base = raw ? raw : DEFAULT_INTERNAL_API_URL;
  return base.replace(/\/+$/, "");
}

/** A single Next.js rewrite rule (source → destination), matching `next.config.ts`'s expected shape. */
export interface ApiRewriteRule {
  source: string;
  destination: string;
}

/**
 * Build the always-on `/api/*` → backend rewrite rule(s). Returns an array so it
 * can be spread straight into `next.config.ts`'s `rewrites()`.
 */
export function buildApiRewrites(env: ProxyEnv = process.env): ApiRewriteRule[] {
  const base = resolveInternalApiBaseUrl(env);
  return [
    {
      source: "/api/:path*",
      destination: `${base}/api/:path*`,
    },
  ];
}
