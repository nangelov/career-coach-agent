import type { NextConfig } from "next";

// Baseline security headers for the Next origin (design §7.2 "Security headers / CSP;
// CORS remains closed"). Applied to every route. The app is a strictly same-origin SPA:
// it only fetches its own `/api/*` (the BFF), so `connect-src 'self'` and
// `frame-ancestors 'none'` are safe. Next.js injects inline bootstrap/hydration scripts
// and Tailwind emits inline styles, so `'unsafe-inline'` is required for script/style-src
// (a nonce-based CSP is a larger, separate change). `img-src` allows data: URIs and https
// (citation favicons / avatars).
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
];

const nextConfig: NextConfig = {
  // No `rewrites()` /api passthrough: SEC-04 replaced it with the BFF Route Handlers under
  // `app/api/*`, which attach the session `Authorization` header server-side from the
  // httpOnly cookie (a transparent rewrite let the browser carry the token — insufficient
  // per design §7.2). The backend origin resolver lives in `lib/apiProxy.ts`.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: SECURITY_HEADERS,
      },
    ];
  },
};

export default nextConfig;
