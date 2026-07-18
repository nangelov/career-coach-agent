/**
 * Client-side dashboard / living-PDP API (design §5.2 / §9; backend P8-02). The thin, DOM-light
 * API-client layer for the whole `/api/dashboard` surface: the `goals → milestones → tasks`
 * hierarchy plus the append-only progress log and the derived progress/streak summary.
 *
 * It mirrors `lib/roles.ts` / `lib/profile.ts` conventions exactly:
 *   - pure functions with an injectable `fetchImpl` / `baseUrl` (DI for tests — no hard globals),
 *   - no client-side auth: the Next.js BFF injects `Authorization` server-side from the httpOnly
 *     session cookie (SEC-04 / §7.2); the browser sends it automatically on these same-origin
 *     fetches — this layer never touches a token,
 *   - wire types that mirror the backend Pydantic schemas verbatim (snake_case fields), so a
 *     summary row can be edited and `PATCH`ed straight back with no lossy remapping,
 *   - a typed {@link DashboardApiError} carrying the HTTP status so the UI can branch on the
 *     backend's distinct states (401 expired, 403 guest-needs-account, 404 not-owned, 429),
 *   - defensive `raw: unknown → typed` parsing (never trust the wire shape blindly).
 *
 * **Approve / reject semantics (§5.2).** An AI-proposed row carries `status="proposed"` /
 * `source="ai"`. Approving is a `PATCH` moving `status` off `proposed` to its normal starting
 * state (goal → `active`, milestone → `pending`, task → `todo`); rejecting is a `DELETE`. There is
 * no dedicated approve endpoint — the generic update/delete calls here cover it.
 *
 * The human status vocabularies deliberately exclude `proposed` (that is an AI-only state); a human
 * `PATCH` never sets it (mirrors the backend `*Update` literals).
 */

// --------------------------------------------------------------------------- //
// Status vocabularies (mirror backend app/schemas/dashboard.py — human-settable only)
// --------------------------------------------------------------------------- //
/** Human-settable goal statuses (ORM vocabulary minus `proposed`). */
export type GoalStatus = "active" | "completed" | "abandoned";
/** Human-settable milestone statuses (ORM vocabulary minus `proposed`). */
export type MilestoneStatus = "pending" | "in_progress" | "completed";
/** Human-settable task statuses (ORM vocabulary minus `proposed`). */
export type TaskStatus = "todo" | "in_progress" | "done" | "cancelled";

/** The starting status a `proposed` row is approved *into*, keyed by kind (§5.2). */
export const APPROVE_STATUS = {
  goal: "active" as GoalStatus,
  milestone: "pending" as MilestoneStatus,
  task: "todo" as TaskStatus,
};

// --------------------------------------------------------------------------- //
// Wire types (mirror backend app/schemas/dashboard.py response models verbatim)
// --------------------------------------------------------------------------- //
/** A persisted goal (backend `GoalResponse`). `status`/`source` are plain strings — a read may be AI-made. */
export interface Goal {
  id: string;
  title: string;
  target_role: string | null;
  target_date: string | null;
  status: string;
  source: string;
  created_at: string;
  updated_at: string;
}

/** A persisted milestone under its goal (backend `MilestoneResponse`). */
export interface Milestone {
  id: string;
  goal_id: string;
  title: string;
  due_date: string | null;
  status: string;
  source: string;
  created_at: string;
  updated_at: string;
}

/** A persisted dashboard task (backend `TaskResponse`). */
export interface Task {
  id: string;
  goal_id: string;
  milestone_id: string | null;
  title: string;
  description: string | null;
  due_date: string | null;
  status: string;
  source: string;
  created_at: string;
  updated_at: string;
}

/** A persisted progress-log entry (backend `ProgressEntryResponse`; append-only). */
export interface ProgressEntry {
  id: string;
  goal_id: string | null;
  task_id: string | null;
  note: string | null;
  source: string;
  created_at: string;
}

/**
 * A goal with its nested milestones + tasks and derived progress (backend `GoalSummary`).
 * `time_progress_pct` is elapsed time toward `target_date` (0–100); `task_completion_pct` is
 * `done` tasks over total. Both are `null` when not computable (no target date / no tasks).
 */
export interface GoalSummary extends Goal {
  milestones: Milestone[];
  tasks: Task[];
  time_progress_pct: number | null;
  task_completion_pct: number | null;
}

/** The progress/streak rollup over the caller's progress log (backend `ProgressSummary`). */
export interface ProgressSummary {
  total_entries: number;
  entries_last_7_days: number;
  current_streak_days: number;
  last_entry_date: string | null;
}

/** The `GET /api/dashboard` response — goals (nested) + a progress/streak summary. */
export interface DashboardSummary {
  goals: GoalSummary[];
  progress: ProgressSummary;
}

// --------------------------------------------------------------------------- //
// Request payloads (mirror backend *Create / *Update — status/source set server-side)
// --------------------------------------------------------------------------- //
export interface GoalCreate {
  title: string;
  target_role?: string | null;
  target_date?: string | null;
}

export interface GoalUpdate {
  title?: string;
  target_role?: string | null;
  target_date?: string | null;
  status?: GoalStatus;
}

export interface MilestoneCreate {
  title: string;
  due_date?: string | null;
}

export interface MilestoneUpdate {
  title?: string;
  due_date?: string | null;
  status?: MilestoneStatus;
}

export interface TaskCreate {
  goal_id: string;
  milestone_id?: string | null;
  title: string;
  description?: string | null;
  due_date?: string | null;
}

export interface TaskUpdate {
  milestone_id?: string | null;
  title?: string;
  description?: string | null;
  due_date?: string | null;
  status?: TaskStatus;
}

export interface ProgressEntryCreate {
  goal_id?: string | null;
  task_id?: string | null;
  note?: string | null;
}

// --------------------------------------------------------------------------- //
// Options (dependency injection for tests — mirrors RolesClientOptions)
// --------------------------------------------------------------------------- //
export interface DashboardClientOptions {
  /** Base URL override; defaults to same-origin ("" → the BFF proxy at /api). */
  baseUrl?: string;
  /** Injected fetch for testing. */
  fetchImpl?: typeof fetch;
}

// --------------------------------------------------------------------------- //
// Errors
// --------------------------------------------------------------------------- //
/**
 * A failed dashboard API call, carrying the HTTP `status` so the UI can branch on the backend's
 * distinct rejection states (401 expired, 403 guest-needs-account, 404 not-owned, 429) instead of
 * one generic error.
 */
export class DashboardApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "DashboardApiError";
    this.status = status;
  }
}

// --------------------------------------------------------------------------- //
// Defensive wire → type mapping (mirrors lib/roles.ts helpers)
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

function nullableNum(value: unknown): number | null {
  if (value == null) {
    return null;
  }
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function parseGoal(raw: unknown): Goal {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    id: str(o.id),
    title: str(o.title),
    target_role: nullableStr(o.target_role),
    target_date: nullableStr(o.target_date),
    status: str(o.status),
    source: str(o.source),
    created_at: str(o.created_at),
    updated_at: str(o.updated_at),
  };
}

function parseMilestone(raw: unknown): Milestone {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    id: str(o.id),
    goal_id: str(o.goal_id),
    title: str(o.title),
    due_date: nullableStr(o.due_date),
    status: str(o.status),
    source: str(o.source),
    created_at: str(o.created_at),
    updated_at: str(o.updated_at),
  };
}

function parseTask(raw: unknown): Task {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    id: str(o.id),
    goal_id: str(o.goal_id),
    milestone_id: nullableStr(o.milestone_id),
    title: str(o.title),
    description: nullableStr(o.description),
    due_date: nullableStr(o.due_date),
    status: str(o.status),
    source: str(o.source),
    created_at: str(o.created_at),
    updated_at: str(o.updated_at),
  };
}

function parseProgressEntry(raw: unknown): ProgressEntry {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    id: str(o.id),
    goal_id: nullableStr(o.goal_id),
    task_id: nullableStr(o.task_id),
    note: nullableStr(o.note),
    source: str(o.source),
    created_at: str(o.created_at),
  };
}

function parseGoalSummary(raw: unknown): GoalSummary {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    ...parseGoal(o),
    milestones: Array.isArray(o.milestones) ? o.milestones.map(parseMilestone) : [],
    tasks: Array.isArray(o.tasks) ? o.tasks.map(parseTask) : [],
    time_progress_pct: nullableNum(o.time_progress_pct),
    task_completion_pct: nullableNum(o.task_completion_pct),
  };
}

function parseProgressSummary(raw: unknown): ProgressSummary {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    total_entries: num(o.total_entries),
    entries_last_7_days: num(o.entries_last_7_days),
    current_streak_days: num(o.current_streak_days),
    last_entry_date: nullableStr(o.last_entry_date),
  };
}

/** Parse a `GET /api/dashboard` body, degrading missing fields defensively. */
export function parseDashboardSummary(raw: unknown): DashboardSummary {
  const o = (raw ?? {}) as Record<string, unknown>;
  return {
    goals: Array.isArray(o.goals) ? o.goals.map(parseGoalSummary) : [],
    progress: parseProgressSummary(o.progress),
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
      return "The dashboard requires an account. Sign in to create and save your plan.";
    case 404:
      return "That item no longer exists. Refresh your dashboard.";
    case 429:
      return "You've made too many requests. Please wait a moment and try again.";
    default:
      return `Could not ${action} (HTTP ${status}).`;
  }
}

async function toDashboardError(
  response: Response,
  action: string,
): Promise<DashboardApiError> {
  return new DashboardApiError(
    response.status,
    await readDetail(response, fallbackMessage(response.status, action)),
  );
}

// --------------------------------------------------------------------------- //
// Request helpers
// --------------------------------------------------------------------------- //
const JSON_HEADERS = { "Content-Type": "application/json", Accept: "application/json" };

/** Issue a JSON request and parse the 2xx body with `parse`, else throw a {@link DashboardApiError}. */
async function requestJson<T>(
  path: string,
  init: RequestInit,
  action: string,
  parse: (raw: unknown) => T,
  options: DashboardClientOptions,
): Promise<T> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(`${baseUrl}${path}`, {
    credentials: "same-origin",
    ...init,
  });
  if (!response.ok) {
    throw await toDashboardError(response, action);
  }
  return parse(await response.json());
}

/** Issue a `DELETE` (204 No Content); throw a {@link DashboardApiError} on non-2xx. */
async function requestDelete(
  path: string,
  action: string,
  options: DashboardClientOptions,
): Promise<void> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  const response = await fetchImpl(`${baseUrl}${path}`, {
    method: "DELETE",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw await toDashboardError(response, action);
  }
}

// --------------------------------------------------------------------------- //
// API calls — summary
// --------------------------------------------------------------------------- //
/**
 * Read the caller's living-PDP summary (`GET /api/dashboard`): goals with nested milestones + tasks
 * and a progress/streak rollup. A **guest** is rejected 403 (§5.2 — the dashboard needs an account);
 * this surfaces as a {@link DashboardApiError} with `status === 403`. Throws on any non-2xx.
 */
export function getDashboardSummary(
  options: DashboardClientOptions = {},
): Promise<DashboardSummary> {
  return requestJson(
    "/api/dashboard",
    { method: "GET", headers: { Accept: "application/json" } },
    "load your dashboard",
    parseDashboardSummary,
    options,
  );
}

// --------------------------------------------------------------------------- //
// API calls — goals
// --------------------------------------------------------------------------- //
export function createGoal(
  payload: GoalCreate,
  options: DashboardClientOptions = {},
): Promise<Goal> {
  return requestJson(
    "/api/dashboard/goals",
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(payload) },
    "create the goal",
    parseGoal,
    options,
  );
}

export function updateGoal(
  goalId: string,
  payload: GoalUpdate,
  options: DashboardClientOptions = {},
): Promise<Goal> {
  return requestJson(
    `/api/dashboard/goals/${encodeURIComponent(goalId)}`,
    { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(payload) },
    "update the goal",
    parseGoal,
    options,
  );
}

export function deleteGoal(
  goalId: string,
  options: DashboardClientOptions = {},
): Promise<void> {
  return requestDelete(
    `/api/dashboard/goals/${encodeURIComponent(goalId)}`,
    "remove the goal",
    options,
  );
}

// --------------------------------------------------------------------------- //
// API calls — milestones
// --------------------------------------------------------------------------- //
export function createMilestone(
  goalId: string,
  payload: MilestoneCreate,
  options: DashboardClientOptions = {},
): Promise<Milestone> {
  return requestJson(
    `/api/dashboard/goals/${encodeURIComponent(goalId)}/milestones`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(payload) },
    "create the milestone",
    parseMilestone,
    options,
  );
}

export function updateMilestone(
  milestoneId: string,
  payload: MilestoneUpdate,
  options: DashboardClientOptions = {},
): Promise<Milestone> {
  return requestJson(
    `/api/dashboard/milestones/${encodeURIComponent(milestoneId)}`,
    { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(payload) },
    "update the milestone",
    parseMilestone,
    options,
  );
}

export function deleteMilestone(
  milestoneId: string,
  options: DashboardClientOptions = {},
): Promise<void> {
  return requestDelete(
    `/api/dashboard/milestones/${encodeURIComponent(milestoneId)}`,
    "remove the milestone",
    options,
  );
}

// --------------------------------------------------------------------------- //
// API calls — tasks
// --------------------------------------------------------------------------- //
export function createTask(
  payload: TaskCreate,
  options: DashboardClientOptions = {},
): Promise<Task> {
  return requestJson(
    "/api/dashboard/tasks",
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(payload) },
    "create the task",
    parseTask,
    options,
  );
}

export function updateTask(
  taskId: string,
  payload: TaskUpdate,
  options: DashboardClientOptions = {},
): Promise<Task> {
  return requestJson(
    `/api/dashboard/tasks/${encodeURIComponent(taskId)}`,
    { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(payload) },
    "update the task",
    parseTask,
    options,
  );
}

export function deleteTask(
  taskId: string,
  options: DashboardClientOptions = {},
): Promise<void> {
  return requestDelete(
    `/api/dashboard/tasks/${encodeURIComponent(taskId)}`,
    "remove the task",
    options,
  );
}

// --------------------------------------------------------------------------- //
// API calls — progress
// --------------------------------------------------------------------------- //
export function addProgress(
  payload: ProgressEntryCreate,
  options: DashboardClientOptions = {},
): Promise<ProgressEntry> {
  return requestJson(
    "/api/dashboard/progress",
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(payload) },
    "log progress",
    parseProgressEntry,
    options,
  );
}

/** List the append-only progress log, newest first (`GET /api/dashboard/progress`). */
export function listProgress(
  params: { limit?: number; offset?: number } = {},
  options: DashboardClientOptions = {},
): Promise<ProgressEntry[]> {
  const query = new URLSearchParams();
  if (params.limit != null) {
    query.set("limit", String(params.limit));
  }
  if (params.offset != null) {
    query.set("offset", String(params.offset));
  }
  const qs = query.toString();
  return requestJson(
    `/api/dashboard/progress${qs ? `?${qs}` : ""}`,
    { method: "GET", headers: { Accept: "application/json" } },
    "load your progress log",
    (raw) => (Array.isArray(raw) ? raw.map(parseProgressEntry) : []),
    options,
  );
}
