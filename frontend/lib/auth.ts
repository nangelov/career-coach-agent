/**
 * Client-side auth/session handling for the SSO-only backend (design §6.2, §7.1).
 *
 * The backend owns the session: `POST /api/auth/guest` and the SSO callback both mint
 * the **same** bearer-token shape (`access_token` + `session_id` + `role` + `expires_in`),
 * so guest and logged-in identities are handled uniformly here. There is **no** httpOnly
 * cookie — P3-02's callback hands the token to the SPA in the redirect URL *fragment*
 * (`#access_token=...`), so the token can only live client-side. We persist it in
 * `localStorage` (survives reloads so an SSO account stays logged in), attach it as
 * `Authorization: Bearer <token>` on API calls, and clear it on logout / expiry.
 *
 * This module is the frontend's single source of truth for the auth contract the Next.js
 * client consumes; it mirrors `backend/app/schemas/auth.py`. Keeping it in `lib/` (thin,
 * reusable, DOM-light) — separate from the React components in `components/` — matches the
 * backend's Router→Service split and the §8 `lib/` = "api client / auth" structure.
 */

// --------------------------------------------------------------------------- //
// Session model (mirrors backend GuestSessionResponse / SessionResponse)
// --------------------------------------------------------------------------- //
export type SessionRole = "guest" | "user";

export interface Session {
  /** Backend-signed session JWT sent as `Authorization: Bearer <token>`. */
  accessToken: string;
  /** Always `"bearer"` today; carried through for forward-compatibility. */
  tokenType: string;
  /** Stable handle the client passes to `POST /api/chat` and rate-limit calls. */
  sessionId: string;
  /** `"guest"` (Redis-only, rate-limited) vs `"user"` (SSO, persisted). */
  role: SessionRole;
  /** Epoch milliseconds when the token expires (from `expires_in`), or null if unknown. */
  expiresAt: number | null;
}

/** The supported OIDC providers (must match backend `OAUTH_METADATA_URLS` keys). */
export type SsoProvider = "google" | "linkedin";

export const STORAGE_KEY = "cc.session";

// --------------------------------------------------------------------------- //
// Options (dependency injection for tests — no direct globals in pure paths)
// --------------------------------------------------------------------------- //
export interface AuthClientOptions {
  /** Base URL override; defaults to same-origin ("" → dev/prod proxy to /api). */
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
// Wire ⇄ Session mapping
// --------------------------------------------------------------------------- //
interface TokenPayload {
  access_token?: unknown;
  token_type?: unknown;
  session_id?: unknown;
  role?: unknown;
  expires_in?: unknown;
}

function toRole(value: unknown): SessionRole {
  return value === "user" ? "user" : "guest";
}

/**
 * Build a {@link Session} from the backend token payload (guest body or callback
 * fragment). Returns null when the mandatory `access_token` / `session_id` are absent,
 * so callers never store a half-formed session.
 */
export function sessionFromPayload(payload: TokenPayload): Session | null {
  const accessToken = payload.access_token;
  const sessionId = payload.session_id;
  if (typeof accessToken !== "string" || !accessToken) {
    return null;
  }
  if (typeof sessionId !== "string" || !sessionId) {
    return null;
  }
  const expiresIn = Number(payload.expires_in);
  const expiresAt =
    Number.isFinite(expiresIn) && expiresIn > 0 ? Date.now() + expiresIn * 1000 : null;
  return {
    accessToken,
    tokenType: typeof payload.token_type === "string" ? payload.token_type : "bearer",
    sessionId,
    role: toRole(payload.role),
    expiresAt,
  };
}

/**
 * Parse the SSO callback fragment (`#access_token=...&session_id=...&role=user&...`) into
 * a {@link Session}. Accepts the raw `location.hash` (with or without the leading `#`).
 */
export function sessionFromFragment(fragment: string): Session | null {
  const hash = fragment.startsWith("#") ? fragment.slice(1) : fragment;
  if (!hash) {
    return null;
  }
  const params = new URLSearchParams(hash);
  return sessionFromPayload({
    access_token: params.get("access_token") ?? undefined,
    token_type: params.get("token_type") ?? undefined,
    session_id: params.get("session_id") ?? undefined,
    role: params.get("role") ?? undefined,
    expires_in: params.get("expires_in") ?? undefined,
  });
}

// --------------------------------------------------------------------------- //
// Persistence (localStorage — the token can only live client-side, see header)
// --------------------------------------------------------------------------- //
function isExpired(session: Session): boolean {
  return session.expiresAt != null && session.expiresAt <= Date.now();
}

/** Persist the session so it survives reloads. No-op if `localStorage` is unavailable. */
export function saveSession(session: Session): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Private-mode / storage-disabled: the in-memory session still works this tab.
  }
}

/** Remove the stored session (logout / expiry / 401). */
export function clearSession(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

/**
 * Load the stored session, or null when absent / malformed / expired. An expired session
 * is proactively cleared so a stale token never lingers.
 */
export function loadSession(): Session | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    clearSession();
    return null;
  }
  const session = parsed as Partial<Session>;
  if (typeof session.accessToken !== "string" || typeof session.sessionId !== "string") {
    clearSession();
    return null;
  }
  const normalized: Session = {
    accessToken: session.accessToken,
    tokenType: typeof session.tokenType === "string" ? session.tokenType : "bearer",
    sessionId: session.sessionId,
    role: toRole(session.role),
    expiresAt: typeof session.expiresAt === "number" ? session.expiresAt : null,
  };
  if (isExpired(normalized)) {
    clearSession();
    return null;
  }
  return normalized;
}

/** The `Authorization` header for an authenticated request, or `{}` when unauthenticated. */
export function authHeaders(session: Session | null): Record<string, string> {
  return session ? { Authorization: `Bearer ${session.accessToken}` } : {};
}

// --------------------------------------------------------------------------- //
// Flows
// --------------------------------------------------------------------------- //
/**
 * Start an anonymous guest session (`POST /api/auth/guest`), persist it, and return it.
 * Throws on a non-2xx / network failure so the caller can surface a login error.
 */
export async function createGuestSession(options: AuthClientOptions = {}): Promise<Session> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(`${baseUrl}/api/auth/guest`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Could not start a guest session (HTTP ${response.status}).`);
  }
  const payload = (await response.json()) as TokenPayload;
  const session = sessionFromPayload(payload);
  if (!session) {
    throw new Error("Guest session response was malformed.");
  }
  saveSession(session);
  return session;
}

/**
 * Begin the SSO login by full-page navigation to the backend `GET /api/auth/login/{provider}`
 * (which 302-redirects to the provider consent screen). An optional `upgradeTicket` carries
 * the current guest session across to the new account (§4 upgrade-to-account).
 */
export function beginSsoLogin(
  provider: SsoProvider,
  options: AuthClientOptions & { upgradeTicket?: string } = {},
): void {
  const { baseUrl = "", navigate = defaultNavigate, upgradeTicket } = options;
  const query = upgradeTicket
    ? `?upgrade_ticket=${encodeURIComponent(upgradeTicket)}`
    : "";
  navigate(`${baseUrl}/api/auth/login/${encodeURIComponent(provider)}${query}`);
}

/**
 * Mint a single-use guest→account upgrade ticket (`POST /api/auth/upgrade`, guest-only) and
 * begin SSO login with it, so the active conversation is preserved on the new account.
 */
export async function upgradeGuestToSso(
  provider: SsoProvider,
  session: Session,
  options: AuthClientOptions = {},
): Promise<void> {
  const { baseUrl = "", fetchImpl = fetch, navigate } = options;
  const response = await fetchImpl(`${baseUrl}/api/auth/upgrade`, {
    method: "POST",
    headers: { ...authHeaders(session), Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Could not begin account upgrade (HTTP ${response.status}).`);
  }
  const body = (await response.json()) as { upgrade_ticket?: unknown };
  const upgradeTicket =
    typeof body.upgrade_ticket === "string" ? body.upgrade_ticket : undefined;
  beginSsoLogin(provider, { baseUrl, navigate, upgradeTicket });
}

/**
 * End the session (`POST /api/auth/logout`) and clear the stored token. The stored session
 * is cleared even if the network call fails, so the client always drops the credential.
 */
export async function logout(
  session: Session,
  options: AuthClientOptions = {},
): Promise<void> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  try {
    await fetchImpl(`${baseUrl}/api/auth/logout`, {
      method: "POST",
      headers: authHeaders(session),
    });
  } catch {
    // Best-effort revocation; the token self-expires regardless.
  } finally {
    clearSession();
  }
}
