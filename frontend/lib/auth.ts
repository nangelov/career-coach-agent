/**
 * Client-side auth/session handling for the SSO-only backend (design §6.2, §7.1, §7.2).
 *
 * As of SEC-04 the session lives in an **httpOnly cookie** owned by the Next.js BFF Route
 * Handlers (`app/api/auth/*`), **not** in `localStorage`, and the browser never touches the
 * token: the BFF injects `Authorization: Bearer <token>` server-side on every proxied call.
 * This module therefore holds **no token** — it only:
 *
 *   - kicks off the flows (guest create, SSO login, guest→account upgrade, logout) by calling
 *     the same-origin BFF endpoints (the browser sends the httpOnly cookie automatically), and
 *   - hydrates the **token-free** {@link Session} (`sessionId`, `role`, `expiresAt`) from
 *     `GET /api/auth/session` on page load / refresh.
 *
 * Keeping it in `lib/` (thin, reusable, DOM-light) — separate from the React components in
 * `components/` — matches the §8 `lib/` = "api client / auth" structure.
 */

// --------------------------------------------------------------------------- //
// Session model (token-free — the token lives only in the httpOnly cookie)
// --------------------------------------------------------------------------- //
export type SessionRole = "guest" | "user";

export interface Session {
  /** Stable handle the client passes to `POST /api/chat` and rate-limit calls. */
  sessionId: string;
  /** `"guest"` (Redis-only, rate-limited) vs `"user"` (SSO, persisted). */
  role: SessionRole;
  /** Epoch milliseconds when the session expires, or null if unknown. */
  expiresAt: number | null;
}

/** The supported OIDC providers (must match backend `OAUTH_METADATA_URLS` keys). */
export type SsoProvider = "google" | "linkedin";

// --------------------------------------------------------------------------- //
// Options (dependency injection for tests — no direct globals in pure paths)
// --------------------------------------------------------------------------- //
export interface AuthClientOptions {
  /** Base URL override; defaults to same-origin ("" → the BFF at /api/auth/*). */
  baseUrl?: string;
  /** Injected fetch for testing. */
  fetchImpl?: typeof fetch;
  /** Injected full-page navigation for testing (defaults to `window.location.assign`). */
  navigate?: (url: string) => void;
}

function defaultNavigate(url: string): void {
  window.location.assign(url);
}

// --------------------------------------------------------------------------- //
// Wire ⇄ Session mapping (BFF token-free bodies — never an access token)
// --------------------------------------------------------------------------- //
interface SessionStatePayload {
  isAuthenticated?: unknown;
  sessionId?: unknown;
  role?: unknown;
  expiresAt?: unknown;
}

function toRole(value: unknown): SessionRole {
  return value === "user" ? "user" : "guest";
}

/**
 * Build a {@link Session} from a BFF token-free payload (the `/api/auth/guest` body or the
 * `/api/auth/session` state). Returns null when the mandatory `sessionId` is absent, so
 * callers never hold a half-formed session.
 */
export function sessionFromState(payload: SessionStatePayload): Session | null {
  const sessionId = payload.sessionId;
  if (typeof sessionId !== "string" || !sessionId) {
    return null;
  }
  const expiresAt = payload.expiresAt;
  return {
    sessionId,
    role: toRole(payload.role),
    expiresAt: typeof expiresAt === "number" ? expiresAt : null,
  };
}

// --------------------------------------------------------------------------- //
// Flows
// --------------------------------------------------------------------------- //
/**
 * Hydrate the current session from the httpOnly cookie via `GET /api/auth/session`. Returns
 * null when there is no valid session (the BFF reports `isAuthenticated: false`), so the UI
 * falls back to the login screen. This replaces the old `localStorage` read.
 */
export async function fetchSession(options: AuthClientOptions = {}): Promise<Session | null> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/api/auth/session`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
  } catch {
    return null;
  }
  if (!response.ok) {
    return null;
  }
  const payload = (await response.json()) as SessionStatePayload;
  if (payload.isAuthenticated !== true) {
    return null;
  }
  return sessionFromState(payload);
}

/**
 * Start an anonymous guest session (`POST /api/auth/guest`) and return it. The BFF sets the
 * httpOnly session cookie on its response; the returned body is token-free. Throws on a
 * non-2xx / network failure so the caller can surface a login error.
 */
export async function createGuestSession(options: AuthClientOptions = {}): Promise<Session> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(`${baseUrl}/api/auth/guest`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    // Consent gate (§6.22): the caller (login screen) only invokes this once the ToS/privacy
    // checkbox is ticked, so the request carries consent for the new guest session. The
    // backend rejects a guest start without it (the real enforcement); this is the wire flag.
    body: JSON.stringify({ consent: true }),
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`Could not start a guest session (HTTP ${response.status}).`);
  }
  const payload = (await response.json()) as SessionStatePayload;
  const session = sessionFromState(payload);
  if (!session) {
    throw new Error("Guest session response was malformed.");
  }
  return session;
}

/**
 * Begin the SSO login by full-page navigation to the BFF `GET /api/auth/login/{provider}`
 * (which calls the backend server-side and redirects the browser to the provider consent
 * screen). An optional `upgradeTicket` carries the current guest session across to the new
 * account (§4 upgrade-to-account).
 */
export function beginSsoLogin(
  provider: SsoProvider,
  options: AuthClientOptions & { upgradeTicket?: string; consent?: boolean } = {},
): void {
  const { baseUrl = "", navigate = defaultNavigate, upgradeTicket, consent } = options;
  // Consent gate (§6.22): thread `consent=1` to the backend `/login` (which rejects a login
  // without it, before redirecting to the provider). The login screen passes it once its
  // ToS/privacy checkbox is ticked. upgrade_ticket kept first for stable URL shape.
  const parts: string[] = [];
  if (upgradeTicket) {
    parts.push(`upgrade_ticket=${encodeURIComponent(upgradeTicket)}`);
  }
  if (consent) {
    parts.push("consent=1");
  }
  const query = parts.length ? `?${parts.join("&")}` : "";
  navigate(`${baseUrl}/api/auth/login/${encodeURIComponent(provider)}${query}`);
}

/**
 * Mint a single-use guest→account upgrade ticket (`POST /api/auth/upgrade`, guest-only) and
 * begin SSO login with it, so the active conversation is preserved on the new account. The
 * BFF injects the guest `Authorization` header from the cookie, so no token is passed here.
 */
export async function upgradeGuestToSso(
  provider: SsoProvider,
  options: AuthClientOptions = {},
): Promise<void> {
  const { baseUrl = "", fetchImpl = fetch, navigate } = options;
  const response = await fetchImpl(`${baseUrl}/api/auth/upgrade`, {
    method: "POST",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`Could not begin account upgrade (HTTP ${response.status}).`);
  }
  const body = (await response.json()) as { upgrade_ticket?: unknown };
  const upgradeTicket =
    typeof body.upgrade_ticket === "string" ? body.upgrade_ticket : undefined;
  // The upgrading guest already accepted the consent gate at guest-session start (§6.22), so
  // the carried-over login is consented — thread the flag so the backend `/login` accepts it.
  beginSsoLogin(provider, { baseUrl, navigate, upgradeTicket, consent: true });
}

/**
 * End the session (`POST /api/auth/logout`). The BFF revokes server-side (best-effort) and
 * clears the httpOnly cookie, so the browser always drops the credential. Never throws.
 */
export async function logout(options: AuthClientOptions = {}): Promise<void> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  try {
    await fetchImpl(`${baseUrl}/api/auth/logout`, {
      method: "POST",
      credentials: "same-origin",
    });
  } catch {
    // Best-effort; the cookie self-expires and the backend token self-expires regardless.
  }
}
