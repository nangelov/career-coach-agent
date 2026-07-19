/**
 * Client-side per-message feedback API (design §5.5; backend P9-01). The thin, DOM-light
 * API-client layer for `POST /api/messages/{message_id}/feedback` — a user rating one assistant
 * turn 👍/👎 with an optional free-text reason.
 *
 * It mirrors `lib/dashboard.ts` / `lib/profile.ts` conventions exactly:
 *   - a pure function with an injectable `fetchImpl` / `baseUrl` (DI for tests — no hard globals),
 *   - no client-side auth: the Next.js BFF injects `Authorization` server-side from the httpOnly
 *     session cookie (SEC-04 / §7.2); the browser sends it automatically on this same-origin
 *     fetch — this layer never touches a token,
 *   - a wire type mirroring the backend Pydantic schema verbatim (snake_case fields),
 *   - a typed {@link MessageFeedbackApiError} carrying the HTTP status so the UI can branch on the
 *     backend's distinct states (401 expired, 404 not-owned, 429) instead of one generic error.
 *
 * The endpoint is an **idempotent upsert** (backend contract): resubmitting for the same message
 * flips the rating / edits the reason on the same row, so the UI can re-call this freely to reflect
 * a toggled thumb or an added reason.
 */

// --------------------------------------------------------------------------- //
// Wire types (mirror backend app/schemas/message_feedback.py)
// --------------------------------------------------------------------------- //
/** The thumbs rating (backend `MessageRating`) — kept in lockstep with the check constraint. */
export type MessageRating = "up" | "down";

/** The stored per-message feedback echoed back after a capture (backend `MessageFeedbackResponse`). */
export interface MessageFeedback {
  message_id: string;
  rating: MessageRating;
  reason: string | null;
  created_at: string;
}

// --------------------------------------------------------------------------- //
// Options (dependency injection for tests — mirrors DashboardClientOptions)
// --------------------------------------------------------------------------- //
export interface MessageFeedbackClientOptions {
  /** Base URL override; defaults to same-origin ("" → the BFF proxy at /api). */
  baseUrl?: string;
  /** Injected fetch for testing. */
  fetchImpl?: typeof fetch;
}

// --------------------------------------------------------------------------- //
// Errors
// --------------------------------------------------------------------------- //
/**
 * A failed message-feedback call, carrying the HTTP `status` so the UI can branch on the backend's
 * distinct rejection states (401 expired, 404 not-owned, 429) instead of one generic error.
 */
export class MessageFeedbackApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "MessageFeedbackApiError";
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

function toRating(value: unknown): MessageRating {
  return value === "down" ? "down" : "up";
}

function parseMessageFeedback(raw: unknown): MessageFeedback {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    message_id: str(o.message_id),
    rating: toRating(o.rating),
    reason: nullableStr(o.reason),
    created_at: str(o.created_at),
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

function fallbackMessage(status: number): string {
  switch (status) {
    case 401:
      return "Your session has expired. Please sign in again.";
    case 404:
      return "That message no longer exists.";
    case 429:
      return "You've made too many requests. Please wait a moment and try again.";
    default:
      return `Could not save your feedback (HTTP ${status}).`;
  }
}

// --------------------------------------------------------------------------- //
// API call
// --------------------------------------------------------------------------- //
/**
 * Submit a 👍/👎 (+ optional reason) for one assistant message
 * (`POST /api/messages/{message_id}/feedback`). Idempotent: re-calling for the same message flips
 * the rating / edits the reason (backend upsert). Returns the stored feedback so the UI can render
 * the confirmed state. Throws a {@link MessageFeedbackApiError} carrying the HTTP status on non-2xx.
 */
export async function submitMessageFeedback(
  messageId: string,
  rating: MessageRating,
  reason?: string | null,
  options: MessageFeedbackClientOptions = {},
): Promise<MessageFeedback> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const body: { rating: MessageRating; reason?: string } = { rating };
  const trimmed = reason?.trim();
  if (trimmed) {
    body.reason = trimmed;
  }
  const response = await fetchImpl(
    `${baseUrl}/api/messages/${encodeURIComponent(messageId)}/feedback`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    },
  );
  if (!response.ok) {
    throw new MessageFeedbackApiError(
      response.status,
      await readDetail(response, fallbackMessage(response.status)),
    );
  }
  return parseMessageFeedback(await response.json());
}
