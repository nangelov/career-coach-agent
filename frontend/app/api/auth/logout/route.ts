/**
 * `POST /api/auth/logout` BFF handler (design §7.2 / §6.13).
 *
 * Best-effort revokes the session server-side (forwarding the token from the cookie to the
 * backend, which deletes the session record), then clears the httpOnly cookie regardless of
 * whether the backend call succeeded — so the browser always drops the credential.
 */

import { NextResponse, type NextRequest } from "next/server";

import { clearSessionCookie, resolveBackendUrl } from "@/lib/bffProxy";
import { SESSION_COOKIE } from "@/lib/bffSession";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (token) {
    try {
      await fetch(resolveBackendUrl("/api/auth/logout"), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      // Best-effort revocation; the token self-expires and we still clear the cookie.
    }
  }
  const response = new NextResponse(null, { status: 204 });
  clearSessionCookie(response);
  return response;
}
