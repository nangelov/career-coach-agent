import {
  addProgress,
  APPROVE_STATUS,
  createGoal,
  createMilestone,
  createTask,
  DashboardApiError,
  deleteGoal,
  deleteMilestone,
  deleteTask,
  getDashboardSummary,
  listProgress,
  parseDashboardSummary,
  updateGoal,
  updateMilestone,
  updateTask,
} from "@/lib/dashboard";

/** A minimal ok/json Response stand-in. */
function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** A 204 No Content stand-in (DELETE) — no JSON body. */
function noContent(): Response {
  return {
    ok: true,
    status: 204,
    json: async () => {
      throw new Error("no body");
    },
  } as unknown as Response;
}

// --------------------------------------------------------------------------- //
// parseDashboardSummary — defensive wire mapping
// --------------------------------------------------------------------------- //
describe("parseDashboardSummary", () => {
  it("maps a full summary body verbatim (snake_case) with nested rows + derived pct", () => {
    const parsed = parseDashboardSummary({
      goals: [
        {
          id: "g1",
          title: "Become an AI Architect",
          target_role: "AI Solution Architect",
          target_date: "2026-12-31",
          status: "active",
          source: "user",
          created_at: "2026-07-01T00:00:00Z",
          updated_at: "2026-07-02T00:00:00Z",
          milestones: [
            {
              id: "m1",
              goal_id: "g1",
              title: "Ship an ML service",
              due_date: null,
              status: "proposed",
              source: "ai",
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
            },
          ],
          tasks: [
            {
              id: "t1",
              goal_id: "g1",
              milestone_id: null,
              title: "Read a paper",
              description: null,
              due_date: null,
              status: "todo",
              source: "user",
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
            },
          ],
          time_progress_pct: 42.4,
          task_completion_pct: null,
        },
      ],
      progress: {
        total_entries: 9,
        entries_last_7_days: 3,
        current_streak_days: 2,
        last_entry_date: "2026-07-17",
      },
    });

    expect(parsed.goals).toHaveLength(1);
    const goal = parsed.goals[0];
    expect(goal.id).toBe("g1");
    expect(goal.target_role).toBe("AI Solution Architect");
    expect(goal.time_progress_pct).toBe(42.4);
    expect(goal.task_completion_pct).toBeNull();
    expect(goal.milestones[0].status).toBe("proposed");
    expect(goal.milestones[0].source).toBe("ai");
    expect(goal.tasks[0].milestone_id).toBeNull();
    expect(parsed.progress).toEqual({
      total_entries: 9,
      entries_last_7_days: 3,
      current_streak_days: 2,
      last_entry_date: "2026-07-17",
    });
  });

  it("degrades missing / malformed fields defensively", () => {
    const parsed = parseDashboardSummary({});
    expect(parsed.goals).toEqual([]);
    expect(parsed.progress).toEqual({
      total_entries: 0,
      entries_last_7_days: 0,
      current_streak_days: 0,
      last_entry_date: null,
    });

    const partial = parseDashboardSummary({ goals: [{ id: "g" }] });
    expect(partial.goals[0]).toMatchObject({
      id: "g",
      title: "",
      milestones: [],
      tasks: [],
      time_progress_pct: null,
      task_completion_pct: null,
    });
  });
});

// --------------------------------------------------------------------------- //
// getDashboardSummary
// --------------------------------------------------------------------------- //
describe("getDashboardSummary", () => {
  it("GETs /api/dashboard (no client Authorization) and returns the parsed summary", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({
        goals: [],
        progress: {
          total_entries: 0,
          entries_last_7_days: 0,
          current_streak_days: 0,
          last_entry_date: null,
        },
      }),
    );
    await getDashboardSummary({ fetchImpl: fetchImpl as unknown as typeof fetch });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/dashboard");
    expect(init.method).toBe("GET");
    expect(init.headers.Authorization).toBeUndefined();
    expect(init.credentials).toBe("same-origin");
  });

  it("surfaces a guest 403 as a DashboardApiError carrying the status", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse(
        { detail: "The dashboard requires an account. Sign in to create and save your plan." },
        false,
        403,
      ),
    );
    await expect(
      getDashboardSummary({ fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toMatchObject({ status: 403, message: /requires an account/i });
  });

  it("falls back to a generic message when the error body has no detail", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({}, false, 500));
    await expect(
      getDashboardSummary({ fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toBeInstanceOf(DashboardApiError);
  });
});

// --------------------------------------------------------------------------- //
// goals — create / update (approve) / delete (reject)
// --------------------------------------------------------------------------- //
describe("goal writes", () => {
  it("POSTs a create-goal body", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ id: "g1", title: "Grow" }, true, 201));
    await createGoal(
      { title: "Grow", target_role: null, target_date: null },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/dashboard/goals");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      title: "Grow",
      target_role: null,
      target_date: null,
    });
  });

  it("PATCHes a proposed goal to its approve status (approve = move off proposed)", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ id: "g1", status: "active" }));
    await updateGoal(
      "g1",
      { status: APPROVE_STATUS.goal },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/dashboard/goals/g1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ status: "active" });
  });

  it("DELETEs a goal (reject) and resolves on 204", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(noContent());
    await deleteGoal("g1", { fetchImpl: fetchImpl as unknown as typeof fetch });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/dashboard/goals/g1");
    expect(init.method).toBe("DELETE");
  });

  it("throws a DashboardApiError on a failed delete", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "Goal not found." }, false, 404));
    await expect(
      deleteGoal("gone", { fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toMatchObject({ status: 404 });
  });
});

// --------------------------------------------------------------------------- //
// milestones + tasks endpoints
// --------------------------------------------------------------------------- //
describe("milestone + task writes", () => {
  it("POSTs a milestone under its goal", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({ id: "m1" }, true, 201));
    await createMilestone(
      "g1",
      { title: "Checkpoint" },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(fetchImpl.mock.calls[0][0]).toBe("/api/dashboard/goals/g1/milestones");
  });

  it("PATCHes a milestone by its own id (not nested under the goal)", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({ id: "m1" }));
    await updateMilestone(
      "m1",
      { status: APPROVE_STATUS.milestone },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(fetchImpl.mock.calls[0][0]).toBe("/api/dashboard/milestones/m1");
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({ status: "pending" });
  });

  it("DELETEs a milestone", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(noContent());
    await deleteMilestone("m1", { fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(fetchImpl.mock.calls[0][0]).toBe("/api/dashboard/milestones/m1");
  });

  it("POSTs a task to the flat /tasks endpoint with its goal_id", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({ id: "t1" }, true, 201));
    await createTask(
      { goal_id: "g1", title: "Do a thing" },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/dashboard/tasks");
    expect(JSON.parse(init.body)).toEqual({ goal_id: "g1", title: "Do a thing" });
  });

  it("PATCHes a task to done and DELETEs a task", async () => {
    const patchFetch = jest.fn().mockResolvedValue(jsonResponse({ id: "t1" }));
    await updateTask(
      "t1",
      { status: "done" },
      { fetchImpl: patchFetch as unknown as typeof fetch },
    );
    expect(patchFetch.mock.calls[0][0]).toBe("/api/dashboard/tasks/t1");
    expect(JSON.parse(patchFetch.mock.calls[0][1].body)).toEqual({ status: "done" });

    const delFetch = jest.fn().mockResolvedValue(noContent());
    await deleteTask("t1", { fetchImpl: delFetch as unknown as typeof fetch });
    expect(delFetch.mock.calls[0][0]).toBe("/api/dashboard/tasks/t1");
  });
});

// --------------------------------------------------------------------------- //
// progress
// --------------------------------------------------------------------------- //
describe("progress", () => {
  it("POSTs a progress entry", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({ id: "p1" }, true, 201));
    await addProgress(
      { goal_id: "g1", note: "made progress" },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/dashboard/progress");
    expect(JSON.parse(init.body)).toEqual({ goal_id: "g1", note: "made progress" });
  });

  it("GETs the progress log with paging params and parses the list", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse([{ id: "p1", note: "x" }, { id: "p2" }]));
    const entries = await listProgress(
      { limit: 10, offset: 5 },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(fetchImpl.mock.calls[0][0]).toBe("/api/dashboard/progress?limit=10&offset=5");
    expect(entries).toHaveLength(2);
    expect(entries[0].id).toBe("p1");
  });
});
