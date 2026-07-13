/**
 * @jest-environment node
 */
import { NextRequest } from "next/server";

import { GET as callbackGET } from "@/app/api/auth/callback/[provider]/route";
import { POST as guestPOST } from "@/app/api/auth/guest/route";
import { GET as loginGET } from "@/app/api/auth/login/[provider]/route";
import { POST as logoutPOST } from "@/app/api/auth/logout/route";
import { GET as sessionGET } from "@/app/api/auth/session/route";
import { SESSION_COOKIE } from "@/lib/bffSession";

function makeToken(payload: Record<string, unknown>): string {
  const seg = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj)).toString("base64url");
  return `${seg({ alg: "HS256" })}.${seg(payload)}.sig`;
}

const nowSec = Math.floor(Date.now() / 1000);
const TOKEN = makeToken({
  sub: "u1",
  role: "user",
  sid: "sid-1",
  iat: nowSec,
  exp: nowSec + 3600,
});

let fetchSpy: jest.SpyInstance;

beforeEach(() => {
  fetchSpy = jest.spyOn(global, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
});

/** A guest request carrying the consent body the browser now sends (§6.22). */
function guestRequest(consent: unknown = true): NextRequest {
  return new NextRequest("http://localhost:3000/api/auth/guest", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ consent }),
  });
}

describe("POST /api/auth/guest", () => {
  it("sets the httpOnly cookie, returns a token-free body, and forwards consent", async () => {
    fetchSpy.mockResolvedValue(
      new Response(JSON.stringify({ access_token: TOKEN, session_id: "sid-1", role: "guest" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await guestPOST(guestRequest(true));

    // Cookie carries the token, httpOnly + SameSite=Lax.
    expect(response.cookies.get(SESSION_COOKIE)?.value).toBe(TOKEN);
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toMatch(/HttpOnly/i);
    expect(setCookie).toMatch(/SameSite=lax/i);

    // The consent flag is forwarded to the backend (the real enforcement point).
    const forwardedInit = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(forwardedInit.body as string)).toEqual({ consent: true });

    // Body is token-free.
    const body = await response.json();
    expect(body).toMatchObject({ sessionId: "sid-1", role: "user" });
    expect(JSON.stringify(body)).not.toContain(TOKEN);
    expect(body.accessToken).toBeUndefined();
  });

  it("forwards consent=false when the browser did not accept (backend rejects it)", async () => {
    fetchSpy.mockResolvedValue(new Response(null, { status: 400 }));
    const response = await guestPOST(guestRequest(false));
    const forwardedInit = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(forwardedInit.body as string)).toEqual({ consent: false });
    // The backend's 400 propagates and no cookie is set.
    expect(response.status).toBe(400);
    expect(response.cookies.get(SESSION_COOKIE)).toBeUndefined();
  });

  it("propagates a backend failure without setting a cookie", async () => {
    fetchSpy.mockResolvedValue(new Response(null, { status: 503 }));
    const response = await guestPOST(guestRequest(true));
    expect(response.status).toBe(503);
    expect(response.cookies.get(SESSION_COOKIE)).toBeUndefined();
  });
});

describe("GET /api/auth/session", () => {
  it("returns the token-free state for a valid cookie", async () => {
    const request = new NextRequest("http://localhost:3000/api/auth/session", {
      headers: { cookie: `${SESSION_COOKIE}=${TOKEN}` },
    });
    const response = await sessionGET(request);
    const body = await response.json();
    expect(body).toMatchObject({ isAuthenticated: true, sessionId: "sid-1", role: "user" });
    expect(JSON.stringify(body)).not.toContain(TOKEN);
  });

  it("reports unauthenticated with no cookie", async () => {
    const request = new NextRequest("http://localhost:3000/api/auth/session");
    const response = await sessionGET(request);
    expect(await response.json()).toEqual({ isAuthenticated: false });
  });
});

describe("POST /api/auth/logout", () => {
  it("forwards the token to revoke and clears the cookie", async () => {
    fetchSpy.mockResolvedValue(new Response(null, { status: 204 }));
    const request = new NextRequest("http://localhost:3000/api/auth/logout", {
      method: "POST",
      headers: { cookie: `${SESSION_COOKIE}=${TOKEN}` },
    });

    const response = await logoutPOST(request);

    // Backend revoke carried the Authorization header.
    const [, init] = fetchSpy.mock.calls[0];
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: `Bearer ${TOKEN}`,
    });
    // Cookie is cleared (Max-Age=0).
    expect(response.status).toBe(204);
    const cleared = response.cookies.get(SESSION_COOKIE);
    expect(cleared?.value).toBe("");
    expect(cleared?.maxAge).toBe(0);
  });

  it("still clears the cookie when the backend revoke fails", async () => {
    fetchSpy.mockRejectedValue(new Error("offline"));
    const request = new NextRequest("http://localhost:3000/api/auth/logout", {
      method: "POST",
      headers: { cookie: `${SESSION_COOKIE}=${TOKEN}` },
    });
    const response = await logoutPOST(request);
    expect(response.cookies.get(SESSION_COOKIE)?.maxAge).toBe(0);
  });
});

describe("GET /api/auth/login/{provider}", () => {
  it("redirects the browser to the provider consent URL obtained server-side", async () => {
    fetchSpy.mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: { location: "https://accounts.google.com/o/oauth2/v2/auth?x=1" },
      }),
    );
    const request = new NextRequest(
      "http://localhost:3000/api/auth/login/google?upgrade_ticket=UPG",
    );
    const response = await loginGET(request, {
      params: Promise.resolve({ provider: "google" }),
    });

    // Called the backend with the upgrade_ticket forwarded, redirects not auto-followed.
    const [target, init] = fetchSpy.mock.calls[0];
    expect(target).toContain("/api/auth/login/google?upgrade_ticket=UPG");
    expect((init as RequestInit).redirect).toBe("manual");
    // Browser is redirected to the provider.
    expect(response.headers.get("location")).toBe(
      "https://accounts.google.com/o/oauth2/v2/auth?x=1",
    );
  });

  it("falls back to the login screen with a reason when the backend does not redirect", async () => {
    fetchSpy.mockResolvedValue(new Response(null, { status: 404 }));
    const request = new NextRequest("http://localhost:3000/api/auth/login/unknown");
    const response = await loginGET(request, {
      params: Promise.resolve({ provider: "unknown" }),
    });
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/?login_error=unknown_provider",
    );
  });

  it("reports provider_unavailable when the backend fails with a non-404", async () => {
    fetchSpy.mockResolvedValue(new Response(null, { status: 502 }));
    const request = new NextRequest("http://localhost:3000/api/auth/login/google");
    const response = await loginGET(request, {
      params: Promise.resolve({ provider: "google" }),
    });
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/?login_error=provider_unavailable",
    );
  });

  it("reports consent_required when the backend rejects with 400 (§6.22)", async () => {
    fetchSpy.mockResolvedValue(new Response(null, { status: 400 }));
    const request = new NextRequest("http://localhost:3000/api/auth/login/google");
    const response = await loginGET(request, {
      params: Promise.resolve({ provider: "google" }),
    });
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/?login_error=consent_required",
    );
  });
});

describe("GET /api/auth/callback/{provider}", () => {
  it("extracts the token from the backend fragment, sets the cookie, redirects clean", async () => {
    fetchSpy.mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: {
          location: `http://localhost:3000/auth/callback#access_token=${TOKEN}&session_id=sid-1&role=user&expires_in=3600`,
        },
      }),
    );
    const request = new NextRequest(
      "http://localhost:3000/api/auth/callback/google?code=abc&state=xyz",
    );
    const response = await callbackGET(request, {
      params: Promise.resolve({ provider: "google" }),
    });

    // Cookie set from the fragment token…
    expect(response.cookies.get(SESSION_COOKIE)?.value).toBe(TOKEN);
    // …and the browser-visible redirect is clean (no token in the URL / fragment).
    const location = response.headers.get("location") ?? "";
    expect(location).toContain("/auth/callback");
    expect(location).not.toContain("#");
    expect(location).not.toContain(TOKEN);
  });

  it("redirects without a cookie when the exchange yields no token", async () => {
    fetchSpy.mockResolvedValue(new Response(null, { status: 400 }));
    const request = new NextRequest(
      "http://localhost:3000/api/auth/callback/google?code=bad&state=bad",
    );
    const response = await callbackGET(request, {
      params: Promise.resolve({ provider: "google" }),
    });
    expect(response.cookies.get(SESSION_COOKIE)).toBeUndefined();
    expect(response.headers.get("location")).toContain("/auth/callback");
  });
});
