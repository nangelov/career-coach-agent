/**
 * Client-side memory-panel API (design §5.4 point 4 / §6.10; backend P9-05). The thin, DOM-light
 * API-client layer for the whole `/api/memory` surface — the "what the coach knows about you"
 * transparency & control screen: the user's explicit, editable {@link Preferences} plus the list
 * of inferred {@link LearnedMemory} rows they can delete.
 *
 * It mirrors `lib/dashboard.ts` / `lib/profile.ts` conventions exactly:
 *   - pure functions with an injectable `fetchImpl` / `baseUrl` (DI for tests — no hard globals),
 *   - no client-side auth: the Next.js BFF injects `Authorization` server-side from the httpOnly
 *     session cookie (SEC-04 / §7.2); the browser sends it automatically on these same-origin
 *     fetches — this layer never touches a token,
 *   - wire types that mirror the backend Pydantic schemas verbatim (snake_case fields), so a
 *     read preferences document can be edited and `PUT` straight back with no lossy remapping,
 *   - a typed {@link MemoryApiError} carrying the HTTP status so the UI can branch on the backend's
 *     distinct states (401 expired, 403 guest-needs-account, 404 not-owned, 429),
 *   - defensive `raw: unknown → typed` parsing (never trust the wire shape blindly).
 *
 * **Account-only (§5.4 / §5.4 durable store).** Learned memory + preferences are durable-only; a
 * guest gets `403` from every call here (guest personalization is session-only, P9-07). The UI
 * renders a clear "sign in to see what the coach has learned" state rather than surfacing the 403.
 *
 * **No per-fact confirmation (§6.10).** Preference edits and memory deletions are immediate — this
 * is the opt-out control surface, deliberately *not* the propose/approve model the dashboard uses.
 */

// --------------------------------------------------------------------------- //
// Wire types (mirror backend app/schemas/memory.py response models verbatim)
// --------------------------------------------------------------------------- //
/**
 * A user's explicit, editable personalization settings (backend `Preferences`) — the PUT body and
 * response. All fields are optional so the panel can render/save a partial document; a `PUT`
 * replaces the whole document (upsert). Kept snake_case so a read round-trips through `PUT` with no
 * field remap.
 */
export interface Preferences {
  tone: string | null;
  formality: string | null;
  language: string | null;
  focus_areas: string[];
  avoid: string[];
}

/** One inferred `user_memories` row as shown in the panel (backend `LearnedMemory`; embedding excluded). */
export interface LearnedMemory {
  id: string;
  text: string;
  memory_type: string;
  confidence: number;
  created_at: string;
}

/** The `GET /api/memory` response — explicit preferences + the learned memories list (backend `MemoryView`). */
export interface MemoryView {
  preferences: Preferences;
  memories: LearnedMemory[];
}

// --------------------------------------------------------------------------- //
// Options (dependency injection for tests — mirrors DashboardClientOptions)
// --------------------------------------------------------------------------- //
export interface MemoryClientOptions {
  /** Base URL override; defaults to same-origin ("" → the BFF proxy at /api). */
  baseUrl?: string;
  /** Injected fetch for testing. */
  fetchImpl?: typeof fetch;
}

// --------------------------------------------------------------------------- //
// Errors
// --------------------------------------------------------------------------- //
/**
 * A failed memory API call, carrying the HTTP `status` so the UI can branch on the backend's
 * distinct rejection states (401 expired, 403 guest-needs-account, 404 not-owned, 429) instead of
 * one generic error.
 */
export class MemoryApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "MemoryApiError";
    this.status = status;
  }
}

// --------------------------------------------------------------------------- //
// Defensive wire → type mapping (mirrors lib/dashboard.ts helpers)
// --------------------------------------------------------------------------- //
function str(value: unknown): string {
  return value == null ? "" : String(value);
}

function nullableStr(value: unknown): string | null {
  return value == null ? null : String(value);
}

function num(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

function strArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(str) : [];
}

/** Parse a `GET/PUT` preferences body, degrading missing fields to null/empty (empty = no row yet). */
export function parsePreferences(raw: unknown): Preferences {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    tone: nullableStr(o.tone),
    formality: nullableStr(o.formality),
    language: nullableStr(o.language),
    focus_areas: strArray(o.focus_areas),
    avoid: strArray(o.avoid),
  };
}

function parseLearnedMemory(raw: unknown): LearnedMemory {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    id: str(o.id),
    text: str(o.text),
    memory_type: str(o.memory_type),
    confidence: num(o.confidence),
    created_at: str(o.created_at),
  };
}

/** Parse a `GET /api/memory` body, degrading missing fields defensively. */
export function parseMemoryView(raw: unknown): MemoryView {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    preferences: parsePreferences(o.preferences),
    memories: Array.isArray(o.memories) ? o.memories.map(parseLearnedMemory) : [],
  };
}

// --------------------------------------------------------------------------- //
// Error helpers (best-effort FastAPI {"detail": ...} extraction — never throws)
// --------------------------------------------------------------------------- //
async function readDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body?.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // non-JSON / empty body — use the fallback
  }
  return fallback;
}

function fallbackMessage(status: number, action: string): string {
  switch (status) {
    case 401:
      return "Your session has expired. Please sign in again.";
    case 403:
      return "Memory requires an account. Sign in to view and manage what the coach knows.";
    case 404:
      return "That memory no longer exists. Refresh the page.";
    case 429:
      return "You've made too many requests. Please wait a moment and try again.";
    default:
      return `Could not ${action} (HTTP ${status}).`;
  }
}

async function toMemoryError(
  response: Response,
  action: string,
): Promise<MemoryApiError> {
  return new MemoryApiError(
    response.status,
    await readDetail(response, fallbackMessage(response.status, action)),
  );
}

// --------------------------------------------------------------------------- //
// API calls
// --------------------------------------------------------------------------- //
/**
 * Read the caller's explicit preferences + learned memories (`GET /api/memory`). A **guest** is
 * rejected `403` (§5.4 — memory needs an account); this surfaces as a {@link MemoryApiError} with
 * `status === 403`. Throws on any non-2xx.
 */
export async function getMemory(
  options: MemoryClientOptions = {},
): Promise<MemoryView> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(`${baseUrl}/api/memory`, {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw await toMemoryError(response, "load what the coach knows");
  }
  return parseMemoryView(await response.json());
}

/**
 * Replace the caller's explicit preferences (`PUT /api/memory/preferences`) and return the stored
 * result — immediate, no confirmation (§6.10). Throws {@link MemoryApiError} on non-2xx.
 */
export async function updatePreferences(
  preferences: Preferences,
  options: MemoryClientOptions = {},
): Promise<Preferences> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(`${baseUrl}/api/memory/preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(preferences),
  });
  if (!response.ok) {
    throw await toMemoryError(response, "save your preferences");
  }
  return parsePreferences(await response.json());
}

/**
 * Delete one learned memory (`DELETE /api/memory/{memory_id}`) — immediate (§6.10). An unknown or
 * not-owned id reads as `404`. Throws {@link MemoryApiError} on non-2xx.
 */
export async function deleteMemory(
  memoryId: string,
  options: MemoryClientOptions = {},
): Promise<void> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(
    `${baseUrl}/api/memory/${encodeURIComponent(memoryId)}`,
    {
      method: "DELETE",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    },
  );
  if (!response.ok) {
    throw await toMemoryError(response, "delete that memory");
  }
}

/**
 * Forget **all** the caller's learned memories (`DELETE /api/memory`); preferences are untouched
 * (§6.10). Returns how many rows were cleared. Throws {@link MemoryApiError} on non-2xx.
 */
export async function deleteAllMemories(
  options: MemoryClientOptions = {},
): Promise<number> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(`${baseUrl}/api/memory`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw await toMemoryError(response, "clear your memories");
  }
  const body = (await response.json()) as { deleted?: unknown };
  return num(body?.deleted);
}
