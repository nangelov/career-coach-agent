/**
 * Client-side profile API (design §5.1 / §4, §9 API table; backend P5-04/05/06).
 *
 * This is the thin, DOM-light API-client layer for the whole `/api/profile` surface plus
 * the generic async-job poller it depends on. It mirrors the conventions established by
 * `lib/auth.ts` / `lib/chatStream.ts`:
 *
 *   - pure functions with an injectable `fetchImpl` / `baseUrl` (DI for tests — no hard
 *     `window`/`fetch` globals in the request paths),
 *   - the bearer session token attached as `Authorization: Bearer <token>` via
 *     {@link authHeaders} exactly like the chat/auth clients,
 *   - wire types that mirror the backend Pydantic schemas verbatim (snake_case fields), so a
 *     `GET` result can be edited and `PUT` straight back with no lossy remapping.
 *
 * The flow it serves (§5.3): `uploadCv` returns a Celery `task_id` immediately (the parse runs
 * off the request path); the caller polls `GET /api/jobs/status/{task_id}` — `pollJobUntilTerminal`
 * wraps the interval-based re-fetch so callers don't hand-roll `setInterval`. `getProfile` /
 * `updateProfile` read and replace the structured profile persisted for a logged-in user.
 *
 * Errors are surfaced as a typed {@link ProfileApiError} carrying the HTTP status, so the UI
 * can branch on the states the backend distinguishes (401 expired, 403 guest-cannot-save, 413
 * too-large, 415 unsupported, 429 rate-limited) rather than showing one generic message.
 */

import { authHeaders, type Session } from "@/lib/auth";

// --------------------------------------------------------------------------- //
// Wire types (mirror backend/app/ingestion/profile.py::ProfileSchema)
// --------------------------------------------------------------------------- //
/** One work-experience entry (backend `ExperienceItem`) — every field is nullable. */
export interface ExperienceItem {
  title: string | null;
  company: string | null;
  start_date: string | null;
  end_date: string | null;
  description: string | null;
}

/** One education entry (backend `EducationItem`) — every field is nullable. */
export interface EducationItem {
  institution: string | null;
  degree: string | null;
  field: string | null;
  start_date: string | null;
  end_date: string | null;
}

/**
 * A structured CV/profile (backend `ProfileSchema`, the shape in `profiles.data`). Kept
 * snake_case to match the wire exactly so an edited profile round-trips through `PUT` without
 * a bidirectional field remap. Each section defaults to empty — a partial CV degrades to
 * empty lists rather than erroring (design §5.1 graceful degradation).
 */
export interface Profile {
  skills: string[];
  experience: ExperienceItem[];
  education: EducationItem[];
  goals: string[];
}

/** The stable, client-facing job lifecycle (backend `JobStatusValue`). */
export type JobStatusValue = "pending" | "in_progress" | "success" | "failure";

/**
 * One poll of an async job's progress (backend `JobStatusResponse`). `stage`/`message` carry
 * the producer's fine-grained progress (in-progress only); `result` is set only on success;
 * `error` is a client-safe message set only on failure.
 */
export interface JobStatus {
  taskId: string;
  status: JobStatusValue;
  state: string | null;
  stage: string | null;
  message: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

/** The async parse-job handle returned by `POST /api/profile/cv` (backend `CvUploadResponse`). */
export interface CvUploadHandle {
  taskId: string;
}

// --------------------------------------------------------------------------- //
// Options (dependency injection for tests — mirrors AuthClientOptions)
// --------------------------------------------------------------------------- //
export interface ProfileClientOptions {
  /** Base URL override; defaults to same-origin ("" → dev/prod proxy to /api). */
  baseUrl?: string;
  /** Injected fetch for testing. */
  fetchImpl?: typeof fetch;
}

/** Options for {@link pollJobUntilTerminal}: interval, progress callback, and cancellation. */
export interface JobPollOptions extends ProfileClientOptions {
  /** Milliseconds between polls (default 1500). */
  intervalMs?: number;
  /** Invoked with every poll result so the UI can show live progress. */
  onUpdate?: (status: JobStatus) => void;
  /** Abort the polling loop (e.g. on component unmount). Rejects with an AbortError. */
  signal?: AbortSignal;
}

// --------------------------------------------------------------------------- //
// Errors
// --------------------------------------------------------------------------- //
/**
 * A failed profile API call, carrying the HTTP `status` so the UI can branch on the backend's
 * distinct rejection states (401/403/413/415/429/…) instead of a single generic error.
 */
export class ProfileApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ProfileApiError";
    this.status = status;
  }
}

function abortError(): Error {
  const err = new Error("Polling was cancelled.");
  err.name = "AbortError";
  return err;
}

/** True for the AbortError thrown when {@link pollJobUntilTerminal} is cancelled. */
export function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === "AbortError";
}

// --------------------------------------------------------------------------- //
// Defensive wire → type mapping (mirrors lib/chatStream.ts helpers)
// --------------------------------------------------------------------------- //
function str(value: unknown): string {
  return value == null ? "" : String(value);
}

function nullableStr(value: unknown): string | null {
  return value == null ? null : String(value);
}

function strArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(str) : [];
}

function toJobStatusValue(value: unknown): JobStatusValue {
  return value === "in_progress" || value === "success" || value === "failure"
    ? value
    : "pending";
}

function parseExperienceItem(raw: unknown): ExperienceItem {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    title: nullableStr(o.title),
    company: nullableStr(o.company),
    start_date: nullableStr(o.start_date),
    end_date: nullableStr(o.end_date),
    description: nullableStr(o.description),
  };
}

function parseEducationItem(raw: unknown): EducationItem {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    institution: nullableStr(o.institution),
    degree: nullableStr(o.degree),
    field: nullableStr(o.field),
    start_date: nullableStr(o.start_date),
    end_date: nullableStr(o.end_date),
  };
}

/** Parse a `GET/PUT /api/profile` body into a {@link Profile}, degrading missing fields to empty. */
export function parseProfile(raw: unknown): Profile {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    skills: strArray(o.skills),
    experience: Array.isArray(o.experience)
      ? o.experience.map(parseExperienceItem)
      : [],
    education: Array.isArray(o.education)
      ? o.education.map(parseEducationItem)
      : [],
    goals: strArray(o.goals),
  };
}

function parseJobStatus(raw: unknown): JobStatus {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    taskId: str(o.task_id),
    status: toJobStatusValue(o.status),
    state: nullableStr(o.state),
    stage: nullableStr(o.stage),
    message: nullableStr(o.message),
    result:
      o.result && typeof o.result === "object"
        ? (o.result as Record<string, unknown>)
        : null,
    error: nullableStr(o.error),
  };
}

/** True when a profile has no data in any section — the "no profile yet" empty shape. */
export function isProfileEmpty(profile: Profile): boolean {
  return (
    profile.skills.length === 0 &&
    profile.experience.length === 0 &&
    profile.education.length === 0 &&
    profile.goals.length === 0
  );
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

async function toProfileError(
  response: Response,
  fallback: string,
): Promise<ProfileApiError> {
  return new ProfileApiError(response.status, await readDetail(response, fallback));
}

function uploadFallback(status: number): string {
  switch (status) {
    case 400:
      return "That file couldn't be read. Please choose a different CV.";
    case 401:
      return "Your session has expired. Please sign in again.";
    case 413:
      return "That file is too large. Please upload a smaller CV.";
    case 415:
      return "That file type isn't supported. Upload a PDF, DOCX, PPTX, or image.";
    case 429:
      return "You've reached your upload limit. Sign in to upload more.";
    default:
      return `Upload failed (HTTP ${status}).`;
  }
}

function updateFallback(status: number): string {
  switch (status) {
    case 401:
      return "Your session has expired. Please sign in again.";
    case 403:
      return "Guests can't save a profile. Sign in to store and edit your profile.";
    case 422:
      return "Some fields couldn't be saved. Please check your entries and try again.";
    default:
      return `Could not save your profile (HTTP ${status}).`;
  }
}

// --------------------------------------------------------------------------- //
// API calls
// --------------------------------------------------------------------------- //
/**
 * Upload a CV (`POST /api/profile/cv`, multipart) and return the async parse-job handle. The
 * parse runs off the request path (§5.3), so this resolves as soon as the file is validated and
 * enqueued; poll {@link pollJobUntilTerminal} with the returned `taskId` to watch progress.
 *
 * Throws a {@link ProfileApiError} carrying the HTTP status on rejection (413 too-large, 415
 * unsupported, 429 over-limit, 401 expired, …), preferring the backend's `detail` message.
 */
export async function uploadCv(
  file: File,
  session: Session,
  options: ProfileClientOptions = {},
): Promise<CvUploadHandle> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const form = new FormData();
  form.append("file", file);
  // NB: never set Content-Type for a FormData body — the browser adds the multipart boundary.
  const response = await fetchImpl(`${baseUrl}/api/profile/cv`, {
    method: "POST",
    headers: { ...authHeaders(session), Accept: "application/json" },
    body: form,
  });
  if (!response.ok) {
    throw await toProfileError(response, uploadFallback(response.status));
  }
  const body = (await response.json()) as { task_id?: unknown };
  const taskId = typeof body.task_id === "string" ? body.task_id : "";
  if (!taskId) {
    throw new ProfileApiError(response.status, "The upload response was malformed.");
  }
  return { taskId };
}

/** Fetch one poll of a job's status (`GET /api/jobs/status/{task_id}`). */
export async function pollJobStatus(
  taskId: string,
  session: Session,
  options: ProfileClientOptions = {},
): Promise<JobStatus> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(
    `${baseUrl}/api/jobs/status/${encodeURIComponent(taskId)}`,
    {
      method: "GET",
      headers: { ...authHeaders(session), Accept: "application/json" },
    },
  );
  if (!response.ok) {
    throw await toProfileError(
      response,
      `Could not check the parse status (HTTP ${response.status}).`,
    );
  }
  return parseJobStatus(await response.json());
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const cleanup = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(abortError());
    };
    const timer = setTimeout(() => {
      cleanup();
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort);
  });
}

/**
 * Poll `GET /api/jobs/status/{task_id}` on an interval until the job reaches a terminal state
 * (`success` / `failure`), invoking `onUpdate` after each poll so the UI can show live progress.
 * Resolves with the terminal {@link JobStatus}. Cancellable via `options.signal` (rejects with an
 * AbortError, distinguishable with {@link isAbortError}) so a component can stop polling on unmount.
 */
export async function pollJobUntilTerminal(
  taskId: string,
  session: Session,
  options: JobPollOptions = {},
): Promise<JobStatus> {
  const { intervalMs = 1500, onUpdate, signal } = options;
  for (;;) {
    if (signal?.aborted) {
      throw abortError();
    }
    const status = await pollJobStatus(taskId, session, options);
    onUpdate?.(status);
    if (status.status === "success" || status.status === "failure") {
      return status;
    }
    await delay(intervalMs, signal);
  }
}

/**
 * Read the caller's structured profile (`GET /api/profile`). A caller with no profile yet — a
 * fresh account or a guest — gets an **empty** profile at 200 (not a 404), so the view/edit UI
 * always has a renderable shape (backend contract). Throws {@link ProfileApiError} on non-2xx.
 */
export async function getProfile(
  session: Session,
  options: ProfileClientOptions = {},
): Promise<Profile> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(`${baseUrl}/api/profile`, {
    method: "GET",
    headers: { ...authHeaders(session), Accept: "application/json" },
  });
  if (!response.ok) {
    const fallback =
      response.status === 401
        ? "Your session has expired. Please sign in again."
        : `Could not load your profile (HTTP ${response.status}).`;
    throw await toProfileError(response, fallback);
  }
  return parseProfile(await response.json());
}

/**
 * Replace the caller's structured profile (`PUT /api/profile`) and return the stored result.
 * A **guest** is rejected with 403 (a profile is anchored to a `users` row); this surfaces as a
 * {@link ProfileApiError} with `status === 403` carrying the backend's sign-in message, so the UI
 * can show it as a clear prompt rather than a generic error.
 */
export async function updateProfile(
  profile: Profile,
  session: Session,
  options: ProfileClientOptions = {},
): Promise<Profile> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(`${baseUrl}/api/profile`, {
    method: "PUT",
    headers: {
      ...authHeaders(session),
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(profile),
  });
  if (!response.ok) {
    throw await toProfileError(response, updateFallback(response.status));
  }
  return parseProfile(await response.json());
}
