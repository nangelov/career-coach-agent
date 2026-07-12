import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { type Session } from "@/lib/auth";
import CvUpload from "@/components/CvUpload";
import {
  pollJobUntilTerminal,
  ProfileApiError,
  uploadCv,
  type JobStatus,
} from "@/lib/profile";

jest.mock("@/lib/profile", () => {
  const actual = jest.requireActual("@/lib/profile");
  return {
    __esModule: true,
    ...actual,
    uploadCv: jest.fn(),
    pollJobUntilTerminal: jest.fn(),
  };
});

const mockUploadCv = uploadCv as jest.MockedFunction<typeof uploadCv>;
const mockPoll = pollJobUntilTerminal as jest.MockedFunction<typeof pollJobUntilTerminal>;

function session(role: Session["role"] = "guest"): Session {
  return {
    accessToken: "tok",
    tokenType: "bearer",
    sessionId: "sid",
    role,
    expiresAt: Date.now() + 3_600_000,
  };
}

function terminal(overrides: Partial<JobStatus>): JobStatus {
  return {
    taskId: "t1",
    status: "success",
    state: null,
    stage: null,
    message: null,
    result: null,
    error: null,
    ...overrides,
  };
}

function pickFile() {
  const input = screen.getByLabelText(/cv file/i);
  const file = new File(["cv"], "cv.pdf", { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("CvUpload", () => {
  it("uploads, shows progress from the poll, then success and calls onParsed", async () => {
    mockUploadCv.mockResolvedValue({ taskId: "t1" });
    let emitUpdate: ((s: JobStatus) => void) | undefined;
    let resolvePoll: ((s: JobStatus) => void) | undefined;
    mockPoll.mockImplementation((_taskId, _session, options) => {
      emitUpdate = options?.onUpdate;
      return new Promise<JobStatus>((resolve) => {
        resolvePoll = resolve;
      });
    });
    const onParsed = jest.fn();

    render(<CvUpload session={session()} onParsed={onParsed} />);
    pickFile();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    });

    // Progress region shows the producer's live message.
    await act(async () => {
      emitUpdate?.(terminal({ status: "in_progress", stage: "parsing", message: "Reading your CV…" }));
    });
    expect(await screen.findByTestId("cv-progress")).toHaveTextContent(/reading your cv/i);

    // Poll resolves success → success banner + onParsed called.
    await act(async () => {
      resolvePoll?.(terminal({ status: "success" }));
    });
    expect(await screen.findByTestId("cv-success")).toBeInTheDocument();
    expect(onParsed).toHaveBeenCalledTimes(1);
  });

  it("shows the client-safe error when the parse job fails", async () => {
    mockUploadCv.mockResolvedValue({ taskId: "t1" });
    mockPoll.mockResolvedValue(
      terminal({ status: "failure", error: "We couldn't read that file." }),
    );
    const onParsed = jest.fn();

    render(<CvUpload session={session()} onParsed={onParsed} />);
    pickFile();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    });

    expect(await screen.findByTestId("cv-error")).toHaveTextContent(
      /couldn't read that file/i,
    );
    expect(onParsed).not.toHaveBeenCalled();
  });

  it("surfaces an upload rejection (e.g. 413) as a clear message", async () => {
    mockUploadCv.mockRejectedValue(
      new ProfileApiError(413, "That file is too large. Please upload a smaller CV."),
    );

    render(<CvUpload session={session()} />);
    pickFile();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    });

    expect(await screen.findByTestId("cv-error")).toHaveTextContent(/too large/i);
  });

  it("keeps the upload button disabled until a file is chosen", () => {
    render(<CvUpload session={session()} />);
    expect(screen.getByRole("button", { name: /^upload$/i })).toBeDisabled();
    pickFile();
    expect(screen.getByRole("button", { name: /^upload$/i })).toBeEnabled();
  });

  it("tells guests they can upload one CV per session", () => {
    render(<CvUpload session={session("guest")} />);
    expect(screen.getByText(/one cv per session/i)).toBeInTheDocument();
  });

  it("does not show the guest hint for a signed-in user", () => {
    render(<CvUpload session={session("user")} />);
    expect(screen.queryByText(/one cv per session/i)).not.toBeInTheDocument();
  });

  it("waits for the upload before polling", async () => {
    mockUploadCv.mockResolvedValue({ taskId: "t1" });
    mockPoll.mockResolvedValue(terminal({ status: "success" }));

    render(<CvUpload session={session()} />);
    pickFile();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));
    });

    await waitFor(() => expect(mockPoll).toHaveBeenCalledTimes(1));
    expect(mockUploadCv).toHaveBeenCalledTimes(1);
    expect(mockPoll.mock.calls[0][0]).toBe("t1");
  });
});
