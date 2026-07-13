/**
 * `GET /api/auth/callback/{provider}` BFF handler (design §7.2 / §6.13).
 *
 * The OAuth provider redirects the *browser* here (a public Next route). Server-side, this
 * calls the backend callback endpoint (redirects not auto-followed) to complete the code
 * exchange. The backend's response is a redirect whose URL fragment carries the session
 * token — but **only this Node process ever sees that Location header**, never the browser.
 * We extract the token, set it in the httpOnly cookie, and issue the browser a clean redirect
 * to `/auth/callback` (no token in the URL, nothing in history).
 */

import { NextResponse, type NextRequest } from "next/server";

import { resolveBackendUrl, setSessionCookie } from "@/lib/bffProxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Extract `access_token` from the backend redirect's `#fragment` (server-side only). */
function tokenFromRedirect(location: string | null): string | null {
  if (!location) {
    return null;
  }
  const hashIndex = location.indexOf("#");
  if (hashIndex < 0) {
    return null;
  }
  const token = new URLSearchParams(location.slice(hashIndex + 1)).get("access_token");
  return token && token.length > 0 ? token : null;
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ provider: string }> },
): Promise<NextResponse> {
  const { provider } = await context.params;
  const backendResponse = await fetch(
    resolveBackendUrl(
      `/api/auth/callback/${encodeURIComponent(provider)}${request.nextUrl.search}`,
    ),
    { method: "GET", redirect: "manual" },
  );

  const token = tokenFromRedirect(backendResponse.headers.get("location"));
  // Always land the browser on the clean callback page; it hydrates from the cookie (or
  // shows a failure state when the cookie was not set).
  const response = NextResponse.redirect(new URL("/auth/callback", request.url), 302);
  if (token) {
    setSessionCookie(response, token);
  }
  return response;
}
