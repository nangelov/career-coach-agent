/**
 * BFF server-side proxy + cookie helpers (design §7.2 / §6.13).
 *
 * These run **only** on the Next.js server (Route Handlers). They are the load-bearing half
 * of the "backend is not a public API" posture: the browser talks only to the Next origin,
 * and this module (a) attaches `Authorization: Bearer <token>` from the httpOnly session
 * cookie server-side, and (b) sets/clears that cookie. The token never enters browser JS.
 *
 * The single source of truth for the backend origin stays {@link resolveInternalApiBaseUrl}
 * (FIX-05 lesson) — this module adds no second URL-resolution path.
 */

import { NextResponse, type NextRequest } from "next/server";

import { resolveInternalApiBaseUrl, type ProxyEnv } from "@/lib/apiProxy";
import { SESSION_COOKIE, sessionCookieMaxAge } from "@/lib/bffSession";

/** Absolute backend URL for a `/api/...` path (+ optional query), via the single resolver. */
export function resolveBackendUrl(pathAndQuery: string, env: ProxyEnv = process.env): string {
  return `${resolveInternalApiBaseUrl(env)}${pathAndQuery}`;
}

/** `Secure` cookies in production only, so http://localhost dev still receives the cookie. */
function cookieIsSecure(env: ProxyEnv = process.env): boolean {
  return env.NODE_ENV === "production";
}

/**
 * Attach the httpOnly session cookie carrying the backend JWT. `Max-Age` tracks the token's
 * remaining lifetime so the cookie and token expire together (design §7.2 cookie posture).
 */
export function setSessionCookie(
  response: NextResponse,
  token: string,
  env: ProxyEnv = process.env,
): void {
  response.cookies.set({
    name: SESSION_COOKIE,
    value: token,
    httpOnly: true,
    secure: cookieIsSecure(env),
    sameSite: "lax",
    path: "/",
    maxAge: sessionCookieMaxAge(token),
  });
}

/** Clear the session cookie (logout / auth failure) with matching attributes. */
export function clearSessionCookie(
  response: NextResponse,
  env: ProxyEnv = process.env,
): void {
  response.cookies.set({
    name: SESSION_COOKIE,
    value: "",
    httpOnly: true,
    secure: cookieIsSecure(env),
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}

// Request headers that must not be forwarded verbatim: hop-by-hop, the browser cookie (the
// backend must never see it), and any client-supplied Authorization (only the BFF sets it).
const STRIP_REQUEST_HEADERS = [
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "cookie",
  "authorization",
];

// Response headers that would corrupt a streamed passthrough (the body is re-framed by the
// Next server) — drop them so SSE / chunked responses stream cleanly to the browser.
const STRIP_RESPONSE_HEADERS = [
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
];

export interface ProxyOptions {
  /** Injected fetch for testing (defaults to global fetch). */
  fetchImpl?: typeof fetch;
  /** Injected env for testing (defaults to process.env). */
  env?: ProxyEnv;
}

/**
 * Forward an incoming BFF request to the FastAPI backend, injecting the session token from
 * the httpOnly cookie as `Authorization: Bearer <token>` and **streaming the response body
 * straight through** (no buffering) so `POST /api/chat` SSE stays incremental (design §7.2).
 *
 * The backend response body is returned as-is (a `ReadableStream`), and streaming-hostile
 * headers (`content-encoding`, `content-length`, …) are stripped so the stream is not
 * re-compressed or length-framed.
 */
export async function proxyRequest(
  request: NextRequest,
  options: ProxyOptions = {},
): Promise<NextResponse> {
  const { fetchImpl = fetch, env = process.env } = options;
  const method = request.method;

  const headers = new Headers(request.headers);
  for (const name of STRIP_REQUEST_HEADERS) {
    headers.delete(name);
  }
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }

  const target = `${resolveInternalApiBaseUrl(env)}${request.nextUrl.pathname}${request.nextUrl.search}`;
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual",
  };
  if (method !== "GET" && method !== "HEAD") {
    // Stream the request body through (multipart uploads, JSON, SSE-initiating POSTs).
    init.body = request.body;
    init.duplex = "half";
  }

  const backendResponse = await fetchImpl(target, init);

  const responseHeaders = new Headers(backendResponse.headers);
  for (const name of STRIP_RESPONSE_HEADERS) {
    responseHeaders.delete(name);
  }
  return new NextResponse(backendResponse.body, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
    headers: responseHeaders,
  });
}
