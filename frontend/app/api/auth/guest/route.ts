/**
 * `POST /api/auth/guest` BFF handler (design §7.2 / §6.13).
 *
 * Calls the backend to mint an anonymous guest session, stores the returned JWT in the
 * httpOnly session cookie, and returns a **token-free** body (`sessionId`, `role`,
 * `expiresAt`) the UI hydrates from. The access token never reaches the browser.
 *
 * Consent gate (SEC-06 / §6.22): the browser sends `{ consent: true }` once the login
 * screen's ToS/privacy checkbox is ticked. This handler forwards that flag to the backend,
 * which is the real enforcement (it rejects a guest start without consent, 400).
 */

import { NextResponse, type NextRequest } from "next/server";

import { resolveBackendUrl, setSessionCookie } from "@/lib/bffProxy";
import { clientSessionState } from "@/lib/bffSession";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  // Read the consent flag from the browser request body (default false = fail closed;
  // a missing/invalid body throws and is treated as no consent).
  let consent = false;
  try {
    const body = (await request.json()) as { consent?: unknown } | undefined;
    consent = body?.consent === true;
  } catch {
    consent = false;
  }

  const backendResponse = await fetch(resolveBackendUrl("/api/auth/guest"), {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ consent }),
  });
  if (!backendResponse.ok) {
    return NextResponse.json(
      { error: "guest_session_failed" },
      { status: backendResponse.status },
    );
  }

  const payload = (await backendResponse.json()) as { access_token?: unknown };
  const token = typeof payload.access_token === "string" ? payload.access_token : "";
  if (!token) {
    return NextResponse.json({ error: "guest_session_malformed" }, { status: 502 });
  }

  const state = clientSessionState(token);
  const response = NextResponse.json({
    sessionId: state.sessionId,
    role: state.role,
    expiresAt: state.expiresAt ?? null,
  });
  setSessionCookie(response, token);
  return response;
}
