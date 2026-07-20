"use client";

import { useState } from "react";

import {
  APPROVE_STATUS,
  type GoalSummary,
  type Milestone,
  type Task,
} from "@/lib/dashboard";
import type { DashboardActions } from "@/components/Dashboard";
import { trackEvent } from "@/lib/analytics";

/** The board item a proposal/create acts on — a non-PII enum forwarded as an event parameter. */
type ItemType = "goal" | "milestone" | "task";

/**
 * One goal on the living-PDP board (design §5.2): its % to target date + task completion bars, its
 * nested milestones and tasks, and the human CRUD / AI-proposal approve-reject controls.
 *
 * An AI-proposed row (`status === "proposed"`, `source === "ai"`) is visually distinct (a
 * "Proposed by your coach" badge) and carries **Approve** (PATCH the row to its normal starting
 * status — goal→active / milestone→pending / task→todo) and **Reject** (DELETE) actions — the
 * "never silent" surface. All writes flow through the injected {@link DashboardActions}, which the
 * board wires to the real endpoints and re-fetches the summary after each mutation so the
 * server-computed percentages stay authoritative.
 */
export interface GoalCardProps {
  goal: GoalSummary;
  busy: boolean;
  actions: DashboardActions;
}

function isProposed(status: string): boolean {
  return status === "proposed";
}

/** Clamp a nullable server percentage into a 0–100 whole number, or `null` when not computable. */
function pct(value: number | null): number | null {
  if (value == null) {
    return null;
  }
  return Math.round(Math.max(0, Math.min(100, value)));
}

function ProposedBadge() {
  return (
    <span
      className="shrink-0 rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700"
      data-testid="proposed-badge"
    >
      Proposed by your coach
    </span>
  );
}

/** A labelled progress bar (plain CSS — no charting dep, per the task's lightweight posture). */
function ProgressBar({
  label,
  value,
  testId,
}: {
  label: string;
  value: number | null;
  testId: string;
}) {
  if (value == null) {
    return null;
  }
  return (
    <div className="space-y-1" data-testid={testId}>
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{label}</span>
        <span>{value}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-blue-500"
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

/**
 * Approve / reject controls for a proposed row (goal, milestone, or task). Emits the §6.27
 * engagement event (with the item type only — never the row's title/content) before running the
 * mutation.
 */
function ProposalControls({
  busy,
  itemType,
  onApprove,
  onReject,
}: {
  busy: boolean;
  itemType: ItemType;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <div className="flex gap-2" data-testid="proposal-controls">
      <button
        type="button"
        className="rounded-md bg-green-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
        disabled={busy}
        onClick={() => {
          trackEvent("dashboard_proposal_approve", { item_type: itemType });
          onApprove();
        }}
      >
        Approve
      </button>
      <button
        type="button"
        className="rounded-md border border-red-300 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
        disabled={busy}
        onClick={() => {
          trackEvent("dashboard_proposal_reject", { item_type: itemType });
          onReject();
        }}
      >
        Reject
      </button>
    </div>
  );
}

function MilestoneRow({
  milestone,
  busy,
  actions,
}: {
  milestone: Milestone;
  busy: boolean;
  actions: DashboardActions;
}) {
  const proposed = isProposed(milestone.status);
  return (
    <li
      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-gray-200 p-2"
      data-testid="milestone-row"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate text-sm font-medium text-gray-800">{milestone.title}</span>
        <span className="shrink-0 text-xs text-gray-400">{milestone.status}</span>
        {proposed ? <ProposedBadge /> : null}
      </div>
      {proposed ? (
        <ProposalControls
          busy={busy}
          itemType="milestone"
          onApprove={() =>
            void actions.updateMilestone(milestone.id, { status: APPROVE_STATUS.milestone })
          }
          onReject={() => void actions.deleteMilestone(milestone.id)}
        />
      ) : (
        <div className="flex gap-2">
          {milestone.status !== "completed" ? (
            <button
              type="button"
              className="text-xs font-medium text-blue-600 hover:text-blue-800 disabled:opacity-50"
              disabled={busy}
              onClick={() =>
                void actions.updateMilestone(milestone.id, { status: "completed" })
              }
            >
              Complete
            </button>
          ) : null}
          <button
            type="button"
            className="text-xs font-medium text-red-600 hover:text-red-800 disabled:opacity-50"
            disabled={busy}
            onClick={() => void actions.deleteMilestone(milestone.id)}
          >
            Delete
          </button>
        </div>
      )}
    </li>
  );
}

function TaskRow({
  task,
  busy,
  actions,
}: {
  task: Task;
  busy: boolean;
  actions: DashboardActions;
}) {
  const proposed = isProposed(task.status);
  return (
    <li
      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-gray-200 p-2"
      data-testid="task-row"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate text-sm text-gray-800">{task.title}</span>
        <span className="shrink-0 text-xs text-gray-400">{task.status}</span>
        {proposed ? <ProposedBadge /> : null}
      </div>
      {proposed ? (
        <ProposalControls
          busy={busy}
          itemType="task"
          onApprove={() => void actions.updateTask(task.id, { status: APPROVE_STATUS.task })}
          onReject={() => void actions.deleteTask(task.id)}
        />
      ) : (
        <div className="flex gap-2">
          {task.status !== "done" ? (
            <button
              type="button"
              className="text-xs font-medium text-blue-600 hover:text-blue-800 disabled:opacity-50"
              disabled={busy}
              onClick={() => void actions.updateTask(task.id, { status: "done" })}
            >
              Done
            </button>
          ) : null}
          <button
            type="button"
            className="text-xs font-medium text-red-600 hover:text-red-800 disabled:opacity-50"
            disabled={busy}
            onClick={() => void actions.deleteTask(task.id)}
          >
            Delete
          </button>
        </div>
      )}
    </li>
  );
}

/** A minimal "title + add" inline form used for adding a milestone or a task under a goal. */
function AddRowForm({
  label,
  placeholder,
  busy,
  itemType,
  onAdd,
  testId,
}: {
  label: string;
  placeholder: string;
  busy: boolean;
  itemType: Exclude<ItemType, "goal">;
  onAdd: (title: string) => void;
  testId: string;
}) {
  const [title, setTitle] = useState("");
  const submit = () => {
    const trimmed = title.trim();
    if (!trimmed || busy) {
      return;
    }
    // Engagement event (§6.27): the item type only — never the entered title.
    trackEvent("dashboard_item_create", { item_type: itemType });
    onAdd(trimmed);
    setTitle("");
  };
  return (
    <form
      className="flex items-center gap-2"
      data-testid={testId}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <input
        type="text"
        className="min-w-0 flex-1 rounded-md border border-gray-300 p-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        placeholder={placeholder}
        aria-label={label}
        value={title}
        disabled={busy}
        onChange={(event) => setTitle(event.target.value)}
      />
      <button
        type="submit"
        className="rounded-md border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        disabled={!title.trim() || busy}
      >
        Add
      </button>
    </form>
  );
}

export default function GoalCard({ goal, busy, actions }: GoalCardProps) {
  const proposed = isProposed(goal.status);
  return (
    <article
      className="space-y-3 rounded-xl border border-gray-200 p-4"
      data-testid="goal-card"
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-gray-900">{goal.title}</h3>
            <span className="text-xs text-gray-400">{goal.status}</span>
            {proposed ? <ProposedBadge /> : null}
          </div>
          {goal.target_role ? (
            <p className="text-xs text-gray-500">Target role: {goal.target_role}</p>
          ) : null}
          {goal.target_date ? (
            <p className="text-xs text-gray-500">Target date: {goal.target_date}</p>
          ) : null}
        </div>

        {proposed ? (
          <ProposalControls
            busy={busy}
            itemType="goal"
            onApprove={() => void actions.updateGoal(goal.id, { status: APPROVE_STATUS.goal })}
            onReject={() => void actions.deleteGoal(goal.id)}
          />
        ) : (
          <div className="flex gap-2">
            {goal.status === "active" ? (
              <button
                type="button"
                className="text-xs font-medium text-blue-600 hover:text-blue-800 disabled:opacity-50"
                disabled={busy}
                onClick={() => void actions.updateGoal(goal.id, { status: "completed" })}
              >
                Complete
              </button>
            ) : null}
            <button
              type="button"
              className="text-xs font-medium text-red-600 hover:text-red-800 disabled:opacity-50"
              disabled={busy}
              onClick={() => void actions.deleteGoal(goal.id)}
            >
              Delete
            </button>
          </div>
        )}
      </header>

      {/* Derived progress: % to target date + task completion (server-computed, P8-02). */}
      <div className="grid gap-3 sm:grid-cols-2">
        <ProgressBar
          label="% to target date"
          value={pct(goal.time_progress_pct)}
          testId="time-progress"
        />
        <ProgressBar
          label="Tasks completed"
          value={pct(goal.task_completion_pct)}
          testId="task-progress"
        />
      </div>

      {/* Milestones */}
      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Milestones
        </h4>
        {goal.milestones.length === 0 ? (
          <p className="text-xs text-gray-400">No milestones yet.</p>
        ) : (
          <ul className="space-y-2" data-testid="milestone-list">
            {goal.milestones.map((milestone) => (
              <MilestoneRow
                key={milestone.id}
                milestone={milestone}
                busy={busy}
                actions={actions}
              />
            ))}
          </ul>
        )}
        <AddRowForm
          label={`Add a milestone to ${goal.title}`}
          placeholder="New milestone…"
          busy={busy}
          itemType="milestone"
          testId="add-milestone-form"
          onAdd={(title) => void actions.createMilestone(goal.id, { title })}
        />
      </section>

      {/* Tasks */}
      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Tasks</h4>
        {goal.tasks.length === 0 ? (
          <p className="text-xs text-gray-400">No tasks yet.</p>
        ) : (
          <ul className="space-y-2" data-testid="task-list">
            {goal.tasks.map((task) => (
              <TaskRow key={task.id} task={task} busy={busy} actions={actions} />
            ))}
          </ul>
        )}
        <AddRowForm
          label={`Add a task to ${goal.title}`}
          placeholder="New task…"
          busy={busy}
          itemType="task"
          testId="add-task-form"
          onAdd={(title) => void actions.createTask({ goal_id: goal.id, title })}
        />
      </section>

      {/* Log progress against this goal (append-only check-in). */}
      <div>
        <button
          type="button"
          className="rounded-md border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          disabled={busy}
          data-testid="log-goal-progress"
          onClick={() => void actions.logProgress({ goal_id: goal.id })}
        >
          Log progress
        </button>
      </div>
    </article>
  );
}
