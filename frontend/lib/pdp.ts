/**
 * Client-side PDP (Personal Development Plan) API (design §5.2 / §9; backend P7-03).
 *
 * The thin, DOM-light API-client layer for `POST /api/pdp` — the v2 replacement for v1's
 * `/pdp-generator`. Unlike v1 there is **no CV upload here**: the plan is built from the caller's
 * already-stored structured profile (P5/P7-03), so the request carries only a `career_goal`
 * (required) plus an optional `target_date` / `additional_context`.
 *
 * It mirrors `lib/roles.ts` / `lib/profile.ts` conventions exactly:
 *   - pure functions with an injectable `fetchImpl` / `baseUrl` (DI for tests — no hard globals),
 *   - no client-side auth: the Next.js BFF injects `Authorization` server-side from the httpOnly
 *     session cookie (SEC-04 / §7.2); the browser sends it automatically on these same-origin
 *     fetches — this layer never touches the token,
 *   - a typed {@link PdpApiError} carrying the HTTP status so the UI can branch on the backend's
 *     distinct states (401 expired, 403 guest, 422 no-profile, 429 rate-limited, 502 failed).
 *
 * The `200` response is the **binary PDF** (`application/pdf`); the backend also stamps an
 * `X-PDP-Status` header (`ok` | `role_profile_missing`) so the UI can surface a best-effort caveat
 * when the target role hasn't been mined yet (P7-03: a missing mined role is *not* a hard error —
 * the plan degrades to a profile-only best-effort). {@link generatePdp} returns the PDF as a
 * {@link Blob} plus that status and the download filename; {@link triggerDownload} performs the
 * browser download (the only DOM-touching function here, kept separate so the fetch path stays
 * pure and unit-testable).
 */

// --------------------------------------------------------------------------- //
// Wire types (mirror backend app/schemas/pdp.py::PdpRequest + PdpStatus)
// --------------------------------------------------------------------------- //
/**
 * The form input for a PDP request (camelCase in the UI; mapped to the snake_case wire body by
 * {@link generatePdp}). `careerGoal` is required; the other two are optional (`""` → omitted).
 */
export interface PdpFormInput {
  careerGoal: string;
  /** Optional ISO date (`YYYY-MM-DD`) the plan's timeline aims at. */
  targetDate?: string;
  /** Optional free-text context (constraints, preferences) for the coach. */
  additionalContext?: string;
}

/**
 * The `X-PDP-Status` a `200` PDF carries: `ok` (the target role was mined) or
 * `role_profile_missing` (the role hasn't been mined yet — the plan is a profile-only best-effort,
 * not a hard error). Mirrors the backend `PdpStatus` values reachable on a success response
 * (`generation_failed` / `profile_missing` never reach the client as a 200 — they map to 502/422).
 */
export type PdpDeliveryStatus = "ok" | "role_profile_missing";

/** A successfully generated plan: the PDF bytes, its download filename, and the delivery status. */
export interface PdpResult {
  blob: Blob;
  filename: string;
  status: PdpDeliveryStatus;
}

// --------------------------------------------------------------------------- //
// Options (dependency injection for tests — mirrors RolesClientOptions)
// --------------------------------------------------------------------------- //
export interface PdpClientOptions {
  /** Base URL override; defaults to same-origin ("" → the BFF proxy at /api). */
  baseUrl?: string;
  /** Injected fetch for testing. */
  fetchImpl?: typeof fetch;
}

// --------------------------------------------------------------------------- //
// Errors
// --------------------------------------------------------------------------- //
/**
 * A failed PDP API call, carrying the HTTP `status` so the UI can branch on the backend's distinct
 * rejection states (401 expired, 403 guest, 422 no-profile, 429 rate-limited, 502 failed) instead
 * of one generic message.
 */
export class PdpApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "PdpApiError";
    this.status = status;
  }
}

// --------------------------------------------------------------------------- //
// Error / header helpers
// --------------------------------------------------------------------------- //
/** Best-effort FastAPI `{"detail": ...}` extraction — never throws. */
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

function generateFallback(status: number): string {
  switch (status) {
    case 401:
      return "Your session has expired. Please sign in again.";
    case 403:
      return "Sign in and upload a CV to generate a development plan.";
    case 422:
      return "Upload a CV to your profile first, then generate a plan.";
    case 429:
      return "You've reached your limit. Please wait a moment and try again.";
    case 502:
      return "We couldn't generate your plan right now. Please try again in a moment.";
    default:
      return `Couldn't generate your plan (HTTP ${status}).`;
  }
}

/** Normalize the `X-PDP-Status` header to a known delivery status, defaulting to `ok`. */
function toDeliveryStatus(value: string | null): PdpDeliveryStatus {
  return value === "role_profile_missing" ? "role_profile_missing" : "ok";
}

/**
 * Extract the download filename from a `Content-Disposition` header (`attachment; filename=...`),
 * falling back to a generic `PDP.pdf` when the header is absent or unparseable.
 */
export function filenameFromDisposition(disposition: string | null): string {
  if (disposition) {
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    if (match?.[1]) {
      return decodeURIComponent(match[1].trim());
    }
  }
  return "PDP.pdf";
}

// --------------------------------------------------------------------------- //
// API call
// --------------------------------------------------------------------------- //
/**
 * Generate a Personal Development Plan (`POST /api/pdp`) from the caller's **stored** profile and
 * return the PDF as a {@link Blob} plus its download filename and delivery status. This is a
 * synchronous, potentially multi-second LLM call (P7-03) — there is no polling.
 *
 * On success (`200`) reads the binary body, the `X-PDP-Status` header, and the download name.
 * Throws a {@link PdpApiError} carrying the HTTP status on any non-2xx (401 expired, 403 guest,
 * 422 no-profile, 429 rate-limited, 502 failed), preferring the backend's `detail` message so the
 * UI can render a distinct state per outcome.
 */
export async function generatePdp(
  input: PdpFormInput,
  options: PdpClientOptions = {},
): Promise<PdpResult> {
  const { baseUrl = "", fetchImpl = fetch } = options;

  const body: Record<string, string> = { career_goal: input.careerGoal };
  if (input.targetDate) {
    body.target_date = input.targetDate;
  }
  if (input.additionalContext) {
    body.additional_context = input.additionalContext;
  }

  const response = await fetchImpl(`${baseUrl}/api/pdp`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/pdf",
    },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new PdpApiError(
      response.status,
      await readDetail(response, generateFallback(response.status)),
    );
  }

  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get("Content-Disposition")),
    status: toDeliveryStatus(response.headers.get("X-PDP-Status")),
  };
}

// --------------------------------------------------------------------------- //
// Browser download (the only DOM-touching helper — kept out of the fetch path)
// --------------------------------------------------------------------------- //
/**
 * Trigger a browser download of `blob` under `filename` via an object URL + a synthetic
 * `<a download>` click (matching v1's streamed-PDF download UX). Revokes the object URL after the
 * click so it isn't leaked. Kept separate from {@link generatePdp} so the fetch path stays pure
 * and this is trivially mockable in component tests (jsdom has no `URL.createObjectURL`).
 */
export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
