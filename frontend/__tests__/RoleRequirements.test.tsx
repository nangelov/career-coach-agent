import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import RoleRequirements from "@/components/RoleRequirements";
import { type Session } from "@/lib/auth";
import {
  getRoleGap,
  getRoleRequirements,
  pollJobUntilTerminal,
  RolesApiError,
  type RoleRequirements as RoleRequirementsData,
  type SkillsGap,
} from "@/lib/roles";

jest.mock("@/lib/roles", () => {
  const actual = jest.requireActual("@/lib/roles");
  return {
    __esModule: true,
    ...actual,
    getRoleRequirements: jest.fn(),
    getRoleGap: jest.fn(),
    pollJobUntilTerminal: jest.fn(),
  };
});

const mockGetRequirements = getRoleRequirements as jest.MockedFunction<
  typeof getRoleRequirements
>;
const mockGetGap = getRoleGap as jest.MockedFunction<typeof getRoleGap>;
const mockPoll = pollJobUntilTerminal as jest.MockedFunction<typeof pollJobUntilTerminal>;

function session(role: Session["role"] = "user"): Session {
  return { sessionId: "sid", role, expiresAt: Date.now() + 3_600_000 };
}

function requirements(): RoleRequirementsData {
  return {
    role: "AI Solution Architect",
    requirements: [
      {
        skill: "Python",
        frequency: 0.8,
        weight: 0.9,
        evidence: ["https://jobs.example/1"],
      },
      { skill: "Kubernetes", frequency: 0.4, weight: 0.4, evidence: [] },
    ],
    evidence_count: 5,
    refreshed_at: null,
  };
}

function okGap(): SkillsGap {
  return {
    role: "AI Solution Architect",
    status: "ok",
    matched: ["Python"],
    gap: [{ skill: "Kubernetes", frequency: 0.4, weight: 0.4, evidence: [] }],
  };
}

async function submit(role = "AI Solution Architect") {
  fireEvent.change(screen.getByLabelText(/target role/i), { target: { value: role } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /find requirements/i }));
  });
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("RoleRequirements", () => {
  it("renders the frequency-ranked, cited requirements for a user and shows the gap", async () => {
    mockGetRequirements.mockResolvedValue({ kind: "requirements", requirements: requirements() });
    mockGetGap.mockResolvedValue({ kind: "gap", gap: okGap() });

    render(<RoleRequirements session={session("user")} />);
    await submit();

    // Requirements render as a ranked, cited list — not a bare skill list.
    expect(await screen.findByTestId("requirements-list")).toBeInTheDocument();
    expect(screen.getAllByTestId("requirement")).toHaveLength(2);
    expect(screen.getByText(/80% of postings/)).toBeInTheDocument();
    const source = screen.getByRole("link", { name: /source 1/i });
    expect(source).toHaveAttribute("href", "https://jobs.example/1");

    // The user's gap panel renders the missing skill.
    expect(await screen.findByTestId("gap-panel")).toBeInTheDocument();
    expect(screen.getByTestId("gap-list")).toHaveTextContent(/kubernetes/i);
    expect(screen.getByTestId("gap-matched")).toHaveTextContent(/python/i);
    expect(screen.queryByTestId("gap-login-prompt")).not.toBeInTheDocument();
  });

  it("shows a log-in prompt (and never calls /gap) for a guest", async () => {
    mockGetRequirements.mockResolvedValue({ kind: "requirements", requirements: requirements() });

    render(<RoleRequirements session={session("guest")} />);
    await submit();

    expect(await screen.findByTestId("requirements-list")).toBeInTheDocument();
    expect(screen.getByTestId("gap-login-prompt")).toHaveTextContent(/log in/i);
    expect(mockGetGap).not.toHaveBeenCalled();
  });

  it("shows a cold-mine progress state, polls, then renders the resolved requirements", async () => {
    mockGetRequirements
      .mockResolvedValueOnce({ kind: "mining", taskId: "mine-1" })
      .mockResolvedValueOnce({ kind: "requirements", requirements: requirements() });
    mockGetGap.mockResolvedValue({ kind: "gap", gap: okGap() });
    mockPoll.mockResolvedValue({
      taskId: "mine-1",
      status: "success",
      state: null,
      stage: null,
      message: null,
      result: null,
      error: null,
    });

    render(<RoleRequirements session={session("user")} />);
    await submit("Novel Role");

    // Resolves to the rendered requirements without a page reload.
    expect(await screen.findByTestId("requirements-list")).toBeInTheDocument();
    expect(mockPoll).toHaveBeenCalledWith("mine-1", expect.objectContaining({}));
    expect(mockGetRequirements).toHaveBeenCalledTimes(2);
  });

  it("surfaces an API error state", async () => {
    mockGetRequirements.mockRejectedValue(
      new RolesApiError(429, "You've made too many requests."),
    );

    render(<RoleRequirements session={session("user")} />);
    await submit();

    expect(await screen.findByTestId("requirements-error")).toHaveTextContent(
      /too many requests/i,
    );
    expect(mockGetGap).not.toHaveBeenCalled();
  });

  it("prompts to upload a CV when the user has no profile yet (profile_missing)", async () => {
    mockGetRequirements.mockResolvedValue({ kind: "requirements", requirements: requirements() });
    mockGetGap.mockResolvedValue({
      kind: "gap",
      gap: { role: "AI Solution Architect", status: "profile_missing", matched: [], gap: null },
    });

    render(<RoleRequirements session={session("user")} />);
    await submit();

    expect(await screen.findByTestId("gap-profile-missing")).toHaveTextContent(
      /upload a cv/i,
    );
  });
});
