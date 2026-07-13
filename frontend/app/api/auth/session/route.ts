/**
 * `GET /api/auth/session` BFF handler (design §7.2 / §6.13).
 *
 * Reads the httpOnly session cookie server-side and returns the **token-free** client
 * session state (`isAuthenticated`, `sessionId`, `role`, `expiresAt`). This is how the UI
 * hydrates auth state on page load / refresh now that the token is no longer in
 * `localStorage`. The raw token is never included in the response.
 */

import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, clientSessionState } from "@/lib/bffSession";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  return NextResponse.json(clientSessionState(token));
}
