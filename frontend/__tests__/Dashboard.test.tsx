import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import Dashboard from "@/components/Dashboard";
import { type Session } from "@/lib/auth";
import {
  addProgress,
  createGoal,
  createTask,
  deleteTask,
  DashboardApiError,
  getDashboardSummary,
  updateTask,
  type DashboardSummary,
} from "@/lib/dashboard";

jest.mock("@/lib/dashboard", () => {
  const actual = jest.requireActual("@/lib/dashboard");
  return {
    __esModule: true,
    ...actual,
    getDashboardSummary: jest.fn(),
    createGoal: jest.fn(),
    updateGoal: jest.fn(),
    deleteGoal: jest.fn(),
    createMilestone: jest.fn(),
    updateMilestone: jest.fn(),
    deleteMilestone: jest.fn(),
    createTask: jest.fn(),
    updateTask: jest.fn(),
    deleteTask: jest.fn(),
    addProgress: jest.fn(),
  };
});

const mockGetSummary = getDashboardSummary as jest.MockedFunction<typeof getDashboardSummary>;
const mockCreateGoal = createGoal as jest.MockedFunction<typeof createGoal>;
const mockCreateTask = createTask as jest.MockedFunction<typeof createTask>;
const mockUpdateTask = updateTask as jest.MockedFunction<typeof updateTask>;
const mockDeleteTask = deleteTask as jest.MockedFunction<typeof deleteTask>;
const mockAddProgress = addProgress as jest.MockedFunction<typeof addProgress>;

function session(role: Session["role"] = "user"): Session {
  return { sessionId: "sid", role, expiresAt: Date.now() + 3_600_000 };
}

function summary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    goals: [
      {
        id: "g1",
        title: "Become an AI Architect",
        target_role: "AI Solution Architect",
        target_date: "2026-12-31",
        status: "active",
        source: "user",
        created_at: "2026-07-01T00:00:00Z",
        updated_at: "2026-07-01T00:00:00Z",
        milestones: [],
        tasks: [
          {
            id: "t1",
            goal_id: "g1",
            milestone_id: null,
            title: "Read a paper",
            description: null,
            due_date: null,
            status: "proposed",
            source: "ai",
            created_at: "2026-07-01T00:00:00Z",
            updated_at: "2026-07-01T00:00:00Z",
          },
        ],
        time_progress_pct: 40,
        task_completion_pct: 0,
      },
    ],
    progress: {
      total_entries: 5,
      entries_last_7_days: 3,
      current_streak_days: 2,
      last_entry_date: "2026-07-17",
    },
    ...overrides,
  };
}

const EMPTY_SUMMARY: DashboardSummary = {
  goals: [],
  progress: {
    total_entries: 0,
    entries_last_7_days: 0,
    current_streak_days: 0,
    last_entry_date: null,
  },
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe("Dashboard", () => {
  it("shows a guest sign-in gate and never fetches the 403-gated API", () => {
    render(<Dashboard session={session("guest")} />);
    expect(screen.getByTestId("dashboard-guest-gate")).toBeInTheDocument();
    expect(mockGetSummary).not.toHaveBeenCalled();
  });

  it("renders the streak/progress numbers and % to target date for a logged-in user", async () => {
    mockGetSummary.mockResolvedValue(summary());
    render(<Dashboard session={session("user")} />);

    expect(await screen.findByTestId("dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("streak-days")).toHaveTextContent("2");
    expect(screen.getByTestId("total-entries")).toHaveTextContent("5");
    expect(screen.getByTestId("entries-last-7-days")).toHaveTextContent("3");
    // % to target date renders from the server-computed summary.
    expect(screen.getByTestId("time-progress")).toHaveTextContent("40%");
  });

  it("marks an AI-proposed task and approves it via a real PATCH off proposed", async () => {
    mockGetSummary.mockResolvedValue(summary());
    mockUpdateTask.mockResolvedValue({} as never);
    render(<Dashboard session={session("user")} />);

    expect(await screen.findByTestId("dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("proposed-badge")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /approve/i }));
    });

    // Approve = PATCH the proposed task to its normal starting status (todo), then re-fetch.
    expect(mockUpdateTask).toHaveBeenCalledWith("t1", { status: "todo" });
    await waitFor(() => expect(mockGetSummary).toHaveBeenCalledTimes(2));
  });

  it("rejects an AI-proposed task via a real DELETE", async () => {
    mockGetSummary.mockResolvedValue(summary());
    mockDeleteTask.mockResolvedValue();
    render(<Dashboard session={session("user")} />);

    expect(await screen.findByTestId("dashboard")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /reject/i }));
    });

    expect(mockDeleteTask).toHaveBeenCalledWith("t1");
    await waitFor(() => expect(mockGetSummary).toHaveBeenCalledTimes(2));
  });

  it("creates a goal from the inline form (human write) and re-fetches", async () => {
    mockGetSummary.mockResolvedValue(EMPTY_SUMMARY);
    mockCreateGoal.mockResolvedValue({} as never);
    render(<Dashboard session={session("user")} />);

    expect(await screen.findByTestId("dashboard-empty")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/goal title/i), {
      target: { value: "Learn Rust" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /add goal/i }));
    });

    expect(mockCreateGoal).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Learn Rust" }),
    );
    await waitFor(() => expect(mockGetSummary).toHaveBeenCalledTimes(2));
  });

  it("adds a task under a goal and logs progress against it", async () => {
    mockGetSummary.mockResolvedValue(summary());
    mockCreateTask.mockResolvedValue({} as never);
    mockAddProgress.mockResolvedValue({} as never);
    render(<Dashboard session={session("user")} />);

    expect(await screen.findByTestId("dashboard")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/add a task to/i), {
      target: { value: "Build a demo" },
    });
    await act(async () => {
      fireEvent.click(
        screen.getByTestId("add-task-form").querySelector("button")!,
      );
    });
    expect(mockCreateTask).toHaveBeenCalledWith({ goal_id: "g1", title: "Build a demo" });

    await act(async () => {
      fireEvent.click(screen.getByTestId("log-goal-progress"));
    });
    expect(mockAddProgress).toHaveBeenCalledWith({ goal_id: "g1" });
  });

  it("surfaces a load error from the summary endpoint", async () => {
    mockGetSummary.mockRejectedValue(new DashboardApiError(500, "Boom."));
    render(<Dashboard session={session("user")} />);
    expect(await screen.findByTestId("dashboard-load-error")).toHaveTextContent(/boom/i);
  });

  it("surfaces an action error without losing the board", async () => {
    mockGetSummary.mockResolvedValue(summary());
    mockDeleteTask.mockRejectedValue(new DashboardApiError(404, "Task not found."));
    render(<Dashboard session={session("user")} />);

    expect(await screen.findByTestId("dashboard")).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /reject/i }));
    });
    expect(await screen.findByTestId("dashboard-action-error")).toHaveTextContent(
      /task not found/i,
    );
  });
});
