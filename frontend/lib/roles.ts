/**
 * Client-side roles / market API (design §5.6 / §9; backend P6-07). The thin, DOM-light
 * API-client layer for the market surface that *replaces* v1 job-search — **no listings, no
 * apply, no save/track** (§1.1), only a role's frequency-ranked, **cited** requirements and the
 * caller's read-only skills gap against them.
 *
 * It mirrors `lib/profile.ts`'s conventions exactly:
 *   - pure functions with an injectable `fetchImpl` / `baseUrl` (DI for tests — no hard globals),
 *   - no client-side auth: the Next.js BFF injects `Authorization` server-side from the httpOnly
 *     session cookie (SEC-04 / §7.2); the browser sends it automatically on these same-origin
 *     fetches — this layer never touches the token,
 *   - wire types that mirror the backend Pydantic schemas verbatim (snake_case fields),
 *   - a typed {@link RolesApiError} carrying the HTTP status so the UI can branch on the backend's
 *     distinct states (403 guest-cannot-gap, 429 rate-limited, …) rather than one generic error.
 *
 * The **cold role** (never mined) case is a `202` carrying a Celery `task_id`, the *same* async-job
 * shape `lib/profile.ts` established (`CvUploadResponse`). Polling is **not reimplemented** here:
 * {@link pollJobUntilTerminal} / {@link JobStatus} / {@link isAbortError} are re-exported from
 * `lib/profile.ts` so a caller polls `GET /api/jobs/status/{task_id}` with the one generic poller.
 */

import {
  isAbortError,
  pollJobUntilTerminal,
  type JobPollOptions,
  type JobStatus,
} from "@/lib/profile";

// Re-exported so the roles surface polls the *existing* generic job poller (P5-06 / §5.3) rather
// than hand-rolling a second one — the reuse the task mandates.
export { isAbortError, pollJobUntilTerminal };
export type { JobPollOptions, JobStatus };

// --------------------------------------------------------------------------- //
// Wire types (mirror backend app/schemas/roles.py + app/schemas/skills_gap.py)
// --------------------------------------------------------------------------- //
/**
 * One ranked, cited requirement for a role (backend `RoleRequirement`). `frequency` (0-1) and
 * `weight` are the aggregated market signal; `evidence` carries the citations (job-posting source
 * URLs / taxonomy source) backing it — the "every requirement is cited" contract (§5.6).
 */
export interface RoleRequirement {
  skill: string;
  frequency: number;
  weight: number;
  evidence: string[];
}

/**
 * `GET /api/roles/{role}/requirements` (HTTP 200) body (backend `RoleRequirementsResponse`).
 * `requirements` is frequency-ranked (most in-demand first); `evidence_count` / `refreshed_at`
 * expose how well-backed and how fresh the profile is. Snake_case, verbatim to the wire.
 */
export interface RoleRequirements {
  role: string;
  requirements: RoleRequirement[];
  evidence_count: number;
  refreshed_at: string | null;
}

/** One required skill the user's profile is missing (backend `SkillGap`), cited like a requirement. */
export interface SkillGap {
  skill: string;
  frequency: number;
  weight: number;
  evidence: string[];
}

/** Outcome of a gap request (backend `SkillsGapStatus`). */
export type SkillsGapStatus = "ok" | "profile_missing" | "role_profile_missing";

/**
 * `GET /api/roles/{role}/gap` (HTTP 200) body (backend `SkillsGapResult`). `matched` names the
 * required skills the user already has; `gap` holds the missing ones, most in-demand first, and is
 * `null` when `status !== "ok"` (no profile / no mined role). Read-only display here (PDP is P7).
 */
export interface SkillsGap {
  role: string;
  status: SkillsGapStatus;
  matched: string[];
  gap: SkillGap[] | null;
}

/**
 * Result of a market read: either the resolved payload, or a `mining` handle for the cold-role
 * `202` case (the role was never mined — a background job was enqueued; poll its `taskId`).
 */
export type RoleRequirementsOutcome =
  | { kind: "requirements"; requirements: RoleRequirements }
  | { kind: "mining"; taskId: string };

export type RoleGapOutcome =
  | { kind: "gap"; gap: SkillsGap }
  | { kind: "mining"; taskId: string };

// --------------------------------------------------------------------------- //
// Options (dependency injection for tests — mirrors ProfileClientOptions)
// --------------------------------------------------------------------------- //
export interface RolesClientOptions {
  /** Base URL override; defaults to same-origin ("" → the BFF proxy at /api). */
  baseUrl?: string;
  /** Injected fetch for testing. */
  fetchImpl?: typeof fetch;
}

// --------------------------------------------------------------------------- //
// Errors
// --------------------------------------------------------------------------- //
/**
 * A failed roles API call, carrying the HTTP `status` so the UI can branch on the backend's
 * distinct rejection states (403 guest-cannot-gap, 429 rate-limited, …) instead of one message.
 */
export class RolesApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "RolesApiError";
    this.status = status;
  }
}

// --------------------------------------------------------------------------- //
// Defensive wire → type mapping (mirrors lib/profile.ts helpers)
// --------------------------------------------------------------------------- //
function num(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

function nullableStr(value: unknown): string | null {
  return value == null ? null : String(value);
}

/** Coerce a JSONB `evidence` field (list[Any]) into a string list, degrading a non-list to `[]`. */
function evidenceList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function strArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function parseRequirement(raw: unknown): RoleRequirement {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    skill: String(o.skill ?? ""),
    frequency: num(o.frequency),
    weight: num(o.weight),
    evidence: evidenceList(o.evidence),
  };
}

/** Parse a `GET /api/roles/{role}/requirements` body, degrading missing fields defensively. */
export function parseRoleRequirements(raw: unknown): RoleRequirements {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    role: String(o.role ?? ""),
    requirements: Array.isArray(o.requirements)
      ? o.requirements.map(parseRequirement)
      : [],
    evidence_count: num(o.evidence_count),
    refreshed_at: nullableStr(o.refreshed_at),
  };
}

function toGapStatus(value: unknown): SkillsGapStatus {
  return value === "profile_missing" || value === "role_profile_missing"
    ? value
    : "ok";
}

/** Parse a `GET /api/roles/{role}/gap` body, degrading missing fields defensively. */
export function parseSkillsGap(raw: unknown): SkillsGap {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    role: String(o.role ?? ""),
    status: toGapStatus(o.status),
    matched: strArray(o.matched),
    gap: Array.isArray(o.gap) ? o.gap.map(parseRequirement) : null,
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

async function toRolesError(
  response: Response,
  fallback: string,
): Promise<RolesApiError> {
  return new RolesApiError(response.status, await readDetail(response, fallback));
}

function requirementsFallback(status: number): string {
  switch (status) {
    case 429:
      return "You've made too many requests. Please wait a moment and try again.";
    default:
      return `Couldn't load market requirements (HTTP ${status}).`;
  }
}

function gapFallback(status: number): string {
  switch (status) {
    case 401:
      return "Your session has expired. Please sign in again.";
    case 403:
      return "Sign in and upload a CV to see your personal skills gap.";
    default:
      return `Couldn't load your skills gap (HTTP ${status}).`;
  }
}

/** Read a `202` mine-job `{task_id}` handle, or throw a {@link RolesApiError} if malformed. */
async function readMiningHandle(response: Response): Promise<string> {
  const body = (await response.json().catch(() => ({}))) as { task_id?: unknown };
  const taskId = typeof body.task_id === "string" ? body.task_id : "";
  if (!taskId) {
    throw new RolesApiError(response.status, "The market response was malformed.");
  }
  return taskId;
}

// --------------------------------------------------------------------------- //
// API calls
// --------------------------------------------------------------------------- //
/**
 * Fetch a role's cached, frequency-ranked, cited requirements (`GET /api/roles/{role}/requirements`,
 * **no login required** — guests may query the market, §5.6). Returns `{ kind: "requirements" }`
 * on a `200` cache hit, or `{ kind: "mining", taskId }` on the `202` cold-role case (the role is
 * being mined for the first time — poll {@link pollJobUntilTerminal} with `taskId`, then re-call).
 * Throws {@link RolesApiError} carrying the HTTP status on any other non-2xx.
 */
export async function getRoleRequirements(
  role: string,
  options: RolesClientOptions = {},
): Promise<RoleRequirementsOutcome> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(
    `${baseUrl}/api/roles/${encodeURIComponent(role)}/requirements`,
    {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    },
  );
  if (response.status === 202) {
    return { kind: "mining", taskId: await readMiningHandle(response) };
  }
  if (!response.ok) {
    throw await toRolesError(response, requirementsFallback(response.status));
  }
  return { kind: "requirements", requirements: parseRoleRequirements(await response.json()) };
}

/**
 * Fetch the caller's skills gap against `role` (`GET /api/roles/{role}/gap`, **requires auth** —
 * a guest is rejected 403, §5.6). Returns `{ kind: "gap" }` on `200` (the `SkillsGap.status`
 * distinguishes `ok` from `profile_missing`), or `{ kind: "mining", taskId }` on the `202` cold
 * role. Throws {@link RolesApiError} (status 403 for a guest, 401 expired, …) on other non-2xx.
 */
export async function getRoleGap(
  role: string,
  options: RolesClientOptions = {},
): Promise<RoleGapOutcome> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(
    `${baseUrl}/api/roles/${encodeURIComponent(role)}/gap`,
    {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    },
  );
  if (response.status === 202) {
    return { kind: "mining", taskId: await readMiningHandle(response) };
  }
  if (!response.ok) {
    throw await toRolesError(response, gapFallback(response.status));
  }
  return { kind: "gap", gap: parseSkillsGap(await response.json()) };
}
