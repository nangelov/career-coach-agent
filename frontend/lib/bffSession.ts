/**
 * BFF session primitives (design §7.2 / §6.13) — the token-handling core shared by the
 * Next.js Route Handlers that own the session cookie.
 *
 * SEC-04 moves the session out of `localStorage` and into an **httpOnly · Secure ·
 * SameSite=Lax** cookie that only the Next server ever reads. This module is the pure,
 * framework-free part of that machinery:
 *
 *   - {@link SESSION_COOKIE} — the single cookie name that carries the backend session JWT;
 *   - {@link decodeSessionToken} — *unverified* claim decode (base64url of the JWT payload)
 *     used only to render UI state (`role`, `sessionId`, expiry). The token is still verified
 *     for real by the FastAPI backend on every proxied call — the BFF never trusts these
 *     claims for authorization, only for display/hydration;
 *   - {@link clientSessionState} — the **token-free** projection returned to the browser by
 *     `GET /api/auth/session` and `POST /api/auth/guest` (never the raw token).
 *
 * Kept import-light (no `next/server`) so it is trivially unit-testable and reusable from the
 * cookie/proxy layer in `lib/bffProxy.ts`.
 */

import type { SessionRole } from "@/lib/auth";

/** The one cookie name that holds the backend session JWT (httpOnly — never read by JS). */
export const SESSION_COOKIE = "cc_session";

/** The verified-by-the-backend claim shape of a session JWT (mirrors `SessionClaims`). */
export interface SessionTokenClaims {
  /** Subject — the user id (logged-in) or the session id (guest). */
  sub: string;
  /** Identity kind the UI branches on. */
  role: SessionRole;
  /** Session id — the handle the chat/rate-limit calls key on. */
  sid: string;
  /** Issued-at (unix seconds). */
  iat: number;
  /** Expiry (unix seconds). */
  exp: number;
}

/**
 * The **token-free** session projection handed to the browser (hydration + guest-create).
 * Deliberately carries no `accessToken` — the token lives only in the httpOnly cookie.
 */
export interface ClientSessionState {
  isAuthenticated: boolean;
  sessionId?: string;
  role?: SessionRole;
  /** Epoch milliseconds when the session token expires. */
  expiresAt?: number;
}

/** Decode a base64url segment to a UTF-8 string (Node `Buffer`, always present server-side). */
function base64UrlDecode(segment: string): string {
  const normalized = segment.replace(/-/g, "+").replace(/_/g, "/");
  return Buffer.from(normalized, "base64").toString("utf-8");
}

/**
 * Decode (do **not** verify) a session JWT's claims. Returns null for any structurally
 * invalid token. This is *display-only*: the backend re-verifies the signature/expiry on
 * every proxied request, so a forged token here buys nothing — it just renders a UI that the
 * backend immediately rejects.
 */
export function decodeSessionToken(token: string): SessionTokenClaims | null {
  const parts = token.split(".");
  if (parts.length !== 3) {
    return null;
  }
  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(base64UrlDecode(parts[1])) as Record<string, unknown>;
  } catch {
    return null;
  }
  const { sid, role, exp } = raw;
  if (typeof sid !== "string" || !sid) {
    return null;
  }
  if (role !== "guest" && role !== "user") {
    return null;
  }
  if (typeof exp !== "number") {
    return null;
  }
  return {
    sub: typeof raw.sub === "string" ? raw.sub : sid,
    role,
    sid,
    iat: typeof raw.iat === "number" ? raw.iat : 0,
    exp,
  };
}

/**
 * Project a (possibly absent) session token into the token-free {@link ClientSessionState}
 * the browser hydrates from. An absent, malformed, or already-expired token resolves to
 * `{ isAuthenticated: false }` so the UI falls back to the login screen.
 */
export function clientSessionState(
  token: string | undefined,
  now: number = Date.now(),
): ClientSessionState {
  if (!token) {
    return { isAuthenticated: false };
  }
  const claims = decodeSessionToken(token);
  if (!claims) {
    return { isAuthenticated: false };
  }
  const expiresAt = claims.exp * 1000;
  if (expiresAt <= now) {
    return { isAuthenticated: false };
  }
  return {
    isAuthenticated: true,
    sessionId: claims.sid,
    role: claims.role,
    expiresAt,
  };
}

/**
 * The cookie `Max-Age` (seconds) for a freshly-minted token — its remaining lifetime, so the
 * cookie expires exactly when the JWT does. Undefined (a session cookie) if the token is
 * unreadable.
 */
export function sessionCookieMaxAge(
  token: string,
  now: number = Date.now(),
): number | undefined {
  const claims = decodeSessionToken(token);
  if (!claims) {
    return undefined;
  }
  return Math.max(0, claims.exp - Math.floor(now / 1000));
}
