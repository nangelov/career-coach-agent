import { act, fireEvent, render, screen } from "@testing-library/react";

import PdpGenerator from "@/components/PdpGenerator";
import { type Session } from "@/lib/auth";
import { generatePdp, PdpApiError, triggerDownload } from "@/lib/pdp";

jest.mock("@/lib/pdp", () => {
  const actual = jest.requireActual("@/lib/pdp");
  return {
    __esModule: true,
    ...actual,
    generatePdp: jest.fn(),
    triggerDownload: jest.fn(),
  };
});

const mockGenerate = generatePdp as jest.MockedFunction<typeof generatePdp>;
const mockDownload = triggerDownload as jest.MockedFunction<typeof triggerDownload>;

function session(role: Session["role"] = "user"): Session {
  return { sessionId: "sid", role, expiresAt: Date.now() + 3_600_000 };
}

function pdfResult(status: "ok" | "role_profile_missing" = "ok") {
  return {
    blob: new Blob(["pdf"], { type: "application/pdf" }),
    filename: "PDP_Goal.pdf",
    status,
  };
}

async function fillGoalAndSubmit(goal = "AI Solution Architect") {
  fireEvent.change(screen.getByLabelText(/set your career goal/i), {
    target: { value: goal },
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /generate pdp/i }));
  });
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("PdpGenerator", () => {
  it("generates a plan, triggers the download, and shows the success state (happy path)", async () => {
    mockGenerate.mockResolvedValue(pdfResult("ok"));

    render(<PdpGenerator session={session("user")} />);
    await fillGoalAndSubmit();

    expect(mockGenerate).toHaveBeenCalledWith(
      expect.objectContaining({ careerGoal: "AI Solution Architect" }),
    );
    expect(mockDownload).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId("pdp-success")).toBeInTheDocument();
    // The role was mined → no best-effort caveat.
    expect(screen.queryByTestId("pdp-role-missing-notice")).not.toBeInTheDocument();
  });

  it("shows the profile-only notice when the role hasn't been mined yet", async () => {
    mockGenerate.mockResolvedValue(pdfResult("role_profile_missing"));

    render(<PdpGenerator session={session("user")} />);
    await fillGoalAndSubmit();

    expect(await screen.findByTestId("pdp-role-missing-notice")).toHaveTextContent(
      /based on your profile only/i,
    );
    expect(mockDownload).toHaveBeenCalledTimes(1);
  });

  it("maps a 422 (no profile) to an upload-CV message pointing at the profile page", async () => {
    mockGenerate.mockRejectedValue(
      new PdpApiError(422, "Upload a CV to your profile first, then generate a plan."),
    );

    render(<PdpGenerator session={session("user")} />);
    await fillGoalAndSubmit();

    const error = await screen.findByTestId("pdp-error");
    expect(error).toHaveTextContent(/upload a cv/i);
    expect(screen.getByRole("link", { name: /go to your profile/i })).toHaveAttribute(
      "href",
      "/profile",
    );
    expect(mockDownload).not.toHaveBeenCalled();
  });

  it("keeps the generate button disabled until a career goal is entered", () => {
    render(<PdpGenerator session={session("user")} />);
    expect(screen.getByRole("button", { name: /generate pdp/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/set your career goal/i), {
      target: { value: "Engineer" },
    });
    expect(screen.getByRole("button", { name: /generate pdp/i })).toBeEnabled();
  });

  it("shows a sign-in gate (not the form) for a guest", () => {
    render(<PdpGenerator session={session("guest")} />);
    expect(screen.getByTestId("pdp-guest-gate")).toHaveTextContent(/sign in/i);
    expect(screen.queryByTestId("pdp-generator")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/set your career goal/i)).not.toBeInTheDocument();
  });
});
