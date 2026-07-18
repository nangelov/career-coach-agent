"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  beginSsoLogin,
  upgradeGuestToSso,
  type Session,
  type SsoProvider,
} from "@/lib/auth";
import {
  addProgress,
  createGoal,
  createMilestone,
  createTask,
  DashboardApiError,
  deleteGoal,
  deleteMilestone,
  deleteTask,
  getDashboardSummary,
  updateGoal,
  updateMilestone,
  updateTask,
  type DashboardSummary,
  type GoalCreate,
  type GoalSummary,
  type GoalUpdate,
  type MilestoneCreate,
  type MilestoneUpdate,
  type ProgressEntryCreate,
  type ProgressSummary,
  type TaskCreate,
  type TaskUpdate,
} from "@/lib/dashboard";
import GoalCard from "@/components/dashboard/GoalCard";

/**
 * The living-PDP dashboard (design §5.2): the goals/milestones/tasks board, a progress/streak
 * summary, % to target date bars, and the approve/reject surface for AI-proposed rows. It consumes
 * the P8-02 human CRUD endpoints only (never the chat graph).
 *
 * Guest vs. user (§5.2 — *"the dashboard requires an account"*): a guest is not fetched against the
 * 403-gated API; instead it sees a sign-in gate that preserves the current session across the
 * upgrade (mirrors `PdpGenerator`'s `GuestGate` / `UpgradePrompt`), not a raw 403.
 *
 * Every mutation flows through {@link DashboardActions}, which calls the real endpoint and then
 * re-fetches the summary so the server-computed percentages/streaks stay authoritative rather than
 * being reconstructed client-side.
 */
export interface DashboardProps {
  session: Session;
}

/**
 * The write surface passed down to {@link GoalCard}. Each call hits the real `/api/dashboard`
 * endpoint and refreshes the summary; approve = a `PATCH` off `proposed`, reject = a `DELETE`.
 */
export interface DashboardActions {
  updateGoal: (id: string, payload: GoalUpdate) => Promise<void>;
  deleteGoal: (id: string) => Promise<void>;
  createMilestone: (goalId: string, payload: MilestoneCreate) => Promise<void>;
  updateMilestone: (id: string, payload: MilestoneUpdate) => Promise<void>;
  deleteMilestone: (id: string) => Promise<void>;
  createTask: (payload: TaskCreate) => Promise<void>;
  updateTask: (id: string, payload: TaskUpdate) => Promise<void>;
  deleteTask: (id: string) => Promise<void>;
  logProgress: (payload: ProgressEntryCreate) => Promise<void>;
}

const GENERIC_ERROR = "Something went wrong. Please try again.";

const SSO_PROVIDERS: ReadonlyArray<{ id: SsoProvider; label: string }> = [
  { id: "google", label: "Sign in with Google" },
  { id: "linkedin", label: "Sign in with LinkedIn" },
];

export default function Dashboard({ session }: DashboardProps) {
  if (session.role === "guest") {
    return <GuestGate />;
  }
  return <Board />;
}

/**
 * Sign-in gate shown to a guest (the dashboard 403s guests, §5.2). Mirrors `PdpGenerator`'s
 * `GuestGate`: offers Google/LinkedIn sign-in that preserves the current guest session via a
 * single-use upgrade ticket, falling back to a plain login.
 */
function GuestGate() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpgrade = useCallback(async (provider: SsoProvider) => {
    setBusy(true);
    setError(null);
    try {
      await upgradeGuestToSso(provider);
    } catch {
      try {
        // The guest already accepted the consent gate at session start (§6.22).
        beginSsoLogin(provider, { consent: true });
      } catch {
        setError("Could not start sign-in. Please try again.");
        setBusy(false);
      }
    }
  }, []);

  return (
    <section
      className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-5 text-sm text-amber-900"
      aria-labelledby="dashboard-guest-heading"
      data-testid="dashboard-guest-gate"
    >
      <h2 id="dashboard-guest-heading" className="text-lg font-semibold">
        Sign in to save a living plan
      </h2>
      <p>
        Your dashboard tracks goals, milestones and progress over time, so it needs an account.
        Sign in to create and save your plan — your current session carries over.
      </p>

      {error ? (
        <p className="text-red-700" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {SSO_PROVIDERS.map((provider) => (
          <button
            key={provider.id}
            type="button"
            className="rounded-md bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            disabled={busy}
            onClick={() => void handleUpgrade(provider.id)}
          >
            {provider.label}
          </button>
        ))}
      </div>
    </section>
  );
}

/** Split goals into the display groups: proposed (needs approval) → active → done/other. */
function groupGoals(goals: GoalSummary[]): {
  proposed: GoalSummary[];
  active: GoalSummary[];
  other: GoalSummary[];
} {
  const proposed: GoalSummary[] = [];
  const active: GoalSummary[] = [];
  const other: GoalSummary[] = [];
  for (const goal of goals) {
    if (goal.status === "proposed") {
      proposed.push(goal);
    } else if (goal.status === "active") {
      active.push(goal);
    } else {
      other.push(goal);
    }
  }
  return { proposed, active, other };
}

/** The logged-in board: fetches the summary and renders progress + grouped goals. */
function Board() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const next = await getDashboardSummary();
    setSummary(next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    getDashboardSummary()
      .then((next) => {
        if (!cancelled) {
          setSummary(next);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(
            err instanceof DashboardApiError
              ? err.message
              : "Couldn't load your dashboard. Please try again.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Run a mutation, then re-fetch so the server-computed summary (percentages, streaks) is
  // authoritative. Errors surface the backend's `detail` via the typed DashboardApiError.
  const runAction = useCallback(
    async (fn: () => Promise<unknown>) => {
      if (busy) {
        return;
      }
      setBusy(true);
      setActionError(null);
      try {
        await fn();
        await refresh();
      } catch (err) {
        setActionError(err instanceof DashboardApiError ? err.message : GENERIC_ERROR);
      } finally {
        setBusy(false);
      }
    },
    [busy, refresh],
  );

  const actions = useMemo<DashboardActions>(
    () => ({
      updateGoal: (id, payload) => runAction(() => updateGoal(id, payload)),
      deleteGoal: (id) => runAction(() => deleteGoal(id)),
      createMilestone: (goalId, payload) => runAction(() => createMilestone(goalId, payload)),
      updateMilestone: (id, payload) => runAction(() => updateMilestone(id, payload)),
      deleteMilestone: (id) => runAction(() => deleteMilestone(id)),
      createTask: (payload) => runAction(() => createTask(payload)),
      updateTask: (id, payload) => runAction(() => updateTask(id, payload)),
      deleteTask: (id) => runAction(() => deleteTask(id)),
      logProgress: (payload) => runAction(() => addProgress(payload)),
    }),
    [runAction],
  );

  const handleCreateGoal = useCallback(
    (payload: GoalCreate) => runAction(() => createGoal(payload)),
    [runAction],
  );

  if (loading) {
    return (
      <section className="rounded-xl border border-gray-200 p-5" aria-busy="true">
        <p className="text-sm text-gray-500" role="status">
          Loading your dashboard…
        </p>
      </section>
    );
  }

  if (loadError) {
    return (
      <section className="rounded-xl border border-gray-200 p-5">
        <p
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
          data-testid="dashboard-load-error"
        >
          {loadError}
        </p>
      </section>
    );
  }

  if (!summary) {
    return null;
  }

  const { proposed, active, other } = groupGoals(summary.goals);

  return (
    <div className="space-y-6" data-testid="dashboard">
      <ProgressPanel progress={summary.progress} />

      {actionError ? (
        <p
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
          data-testid="dashboard-action-error"
        >
          {actionError}
        </p>
      ) : null}

      <CreateGoalForm busy={busy} onCreate={handleCreateGoal} />

      {summary.goals.length === 0 ? (
        <p className="text-sm text-gray-500" data-testid="dashboard-empty">
          You don&apos;t have any goals yet. Add your first career goal above to start your plan.
        </p>
      ) : (
        <>
          <GoalGroup
            title="Proposed by your coach"
            goals={proposed}
            busy={busy}
            actions={actions}
            testId="goal-group-proposed"
          />
          <GoalGroup
            title="Active goals"
            goals={active}
            busy={busy}
            actions={actions}
            testId="goal-group-active"
          />
          <GoalGroup
            title="Completed & archived"
            goals={other}
            busy={busy}
            actions={actions}
            testId="goal-group-other"
          />
        </>
      )}
    </div>
  );
}

/** A titled group of goal cards; renders nothing when the group is empty. */
function GoalGroup({
  title,
  goals,
  busy,
  actions,
  testId,
}: {
  title: string;
  goals: GoalSummary[];
  busy: boolean;
  actions: DashboardActions;
  testId: string;
}) {
  if (goals.length === 0) {
    return null;
  }
  return (
    <section className="space-y-3" data-testid={testId}>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">{title}</h2>
      {goals.map((goal) => (
        <GoalCard key={goal.id} goal={goal} busy={busy} actions={actions} />
      ))}
    </section>
  );
}

/** The streak counter + a small activity bar over the append-only progress log (§5.2). */
function ProgressPanel({ progress }: { progress: ProgressSummary }) {
  const recent = Math.max(0, Math.min(7, progress.entries_last_7_days));
  const barPct = Math.round((recent / 7) * 100);
  return (
    <section
      className="grid gap-4 rounded-xl border border-gray-200 p-4 sm:grid-cols-3"
      data-testid="progress-panel"
    >
      <div>
        <p className="text-2xl font-semibold text-gray-900" data-testid="streak-days">
          {progress.current_streak_days}
        </p>
        <p className="text-xs text-gray-500">
          day streak{progress.current_streak_days === 1 ? "" : ""}
        </p>
      </div>
      <div>
        <p className="text-2xl font-semibold text-gray-900" data-testid="total-entries">
          {progress.total_entries}
        </p>
        <p className="text-xs text-gray-500">total check-ins</p>
      </div>
      <div className="space-y-1">
        <div className="flex items-baseline justify-between text-xs text-gray-500">
          <span>Last 7 days</span>
          <span data-testid="entries-last-7-days">{progress.entries_last_7_days}</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
          <div
            className="h-full rounded-full bg-green-500"
            style={{ width: `${barPct}%` }}
            data-testid="activity-bar"
          />
        </div>
        {progress.last_entry_date ? (
          <p className="text-xs text-gray-400">Last check-in: {progress.last_entry_date}</p>
        ) : null}
      </div>
    </section>
  );
}

/** Inline "create a goal" form — a human write (`source="user"`, enforced server-side). */
function CreateGoalForm({
  busy,
  onCreate,
}: {
  busy: boolean;
  onCreate: (payload: GoalCreate) => void;
}) {
  const [title, setTitle] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [targetDate, setTargetDate] = useState("");

  const submit = () => {
    const trimmed = title.trim();
    if (!trimmed || busy) {
      return;
    }
    onCreate({
      title: trimmed,
      target_role: targetRole.trim() || null,
      target_date: targetDate || null,
    });
    setTitle("");
    setTargetRole("");
    setTargetDate("");
  };

  return (
    <form
      className="space-y-3 rounded-xl border border-gray-200 p-4"
      data-testid="create-goal-form"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <h2 className="text-sm font-semibold text-gray-700">Add a goal</h2>
      <div className="grid gap-2 sm:grid-cols-3">
        <input
          type="text"
          className="rounded-md border border-gray-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 sm:col-span-3"
          placeholder="Goal title (e.g. Become an AI Solution Architect)"
          aria-label="Goal title"
          value={title}
          disabled={busy}
          onChange={(event) => setTitle(event.target.value)}
        />
        <input
          type="text"
          className="rounded-md border border-gray-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 sm:col-span-2"
          placeholder="Target role (optional)"
          aria-label="Target role"
          value={targetRole}
          disabled={busy}
          onChange={(event) => setTargetRole(event.target.value)}
        />
        <input
          type="date"
          className="rounded-md border border-gray-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          aria-label="Target date"
          value={targetDate}
          disabled={busy}
          onChange={(event) => setTargetDate(event.target.value)}
        />
      </div>
      <button
        type="submit"
        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        disabled={!title.trim() || busy}
      >
        Add goal
      </button>
    </form>
  );
}
