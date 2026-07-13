/**
 * Catch-all BFF proxy (design §7.2) — the single Route Handler that forwards every
 * `/api/*` browser call to the FastAPI backend with the session `Authorization` header
 * injected server-side from the httpOnly cookie.
 *
 * This replaces the old transparent `next.config.ts` `rewrites()` passthrough (which let the
 * browser originate the call and carry the token). More specific handlers under
 * `app/api/auth/*` take precedence per Next's routing rules; everything else (chat, profile,
 * jobs, auth/upgrade, …) flows through here.
 *
 * `runtime = "nodejs"` + streaming the backend body verbatim keeps `POST /api/chat` SSE
 * incremental (verified by the proxy unit tests).
 */

import type { NextRequest, NextResponse } from "next/server";

import { proxyRequest } from "@/lib/bffProxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function handle(request: NextRequest): Promise<NextResponse> {
  return proxyRequest(request);
}

export {
  handle as GET,
  handle as POST,
  handle as PUT,
  handle as DELETE,
  handle as PATCH,
};
