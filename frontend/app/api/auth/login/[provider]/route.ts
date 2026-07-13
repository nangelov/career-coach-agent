/**
 * `GET /api/auth/login/{provider}` BFF handler (design §7.2 / §6.13).
 *
 * The browser can no longer reach the backend directly, so this handler calls the backend
 * login endpoint **server-side** (redirects not auto-followed) to obtain the OAuth-provider
 * consent URL, then issues that redirect to the browser itself. Any `upgrade_ticket` query
 * (guest→account upgrade) is forwarded through unchanged.
 */

import { NextResponse, type NextRequest } from "next/server";

import { resolveBackendUrl } from "@/lib/bffProxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ provider: string }> },
): Promise<NextResponse> {
  const { provider } = await context.params;
  const backendResponse = await fetch(
    resolveBackendUrl(`/api/auth/login/${encodeURIComponent(provider)}${request.nextUrl.search}`),
    { method: "GET", redirect: "manual" },
  );

  const location = backendResponse.headers.get("location");
  if (backendResponse.status >= 300 && backendResponse.status < 400 && location) {
    // Hand the provider consent URL to the browser as its own redirect.
    return NextResponse.redirect(location, 302);
  }
  // Login could not start: fall back to the login screen with a reason the UI can surface
  // (404 → unknown provider; 400 → consent not accepted (§6.22); anything else, e.g. 502 →
  // provider unavailable) instead of a silent redirect the user can't diagnose.
  let reason = "provider_unavailable";
  if (backendResponse.status === 404) {
    reason = "unknown_provider";
  } else if (backendResponse.status === 400) {
    reason = "consent_required";
  }
  const fallback = new URL("/", request.url);
  fallback.searchParams.set("login_error", reason);
  return NextResponse.redirect(fallback, 302);
}
