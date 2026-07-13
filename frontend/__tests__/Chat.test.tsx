import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import Chat from "@/components/Chat";
import { fetchSession } from "@/lib/auth";
import {
  cancelChat,
  streamChat,
  type ChatStreamEvent,
} from "@/lib/chatStream";

jest.mock("@/lib/chatStream", () => ({
  __esModule: true,
  streamChat: jest.fn(),
  cancelChat: jest.fn(),
}));

// The session is hydrated from the httpOnly cookie via the BFF (SEC-04). Mock that hydration
// (and logout) but keep the real login/upgrade flows for the screens that render on sign-out.
jest.mock("@/lib/auth", () => {
  const actual = jest.requireActual("@/lib/auth");
  return {
    __esModule: true,
    ...actual,
    fetchSession: jest.fn(),
    logout: jest.fn().mockResolvedValue(undefined),
  };
});

const mockStreamChat = streamChat as jest.MockedFunction<typeof streamChat>;
const mockCancelChat = cancelChat as jest.MockedFunction<typeof cancelChat>;
const mockFetchSession = fetchSession as jest.MockedFunction<typeof fetchSession>;

beforeEach(() => {
  jest.clearAllMocks();
  // Chat is auth-gated (P3-06): resolve a valid guest session so the chat UI renders.
  mockFetchSession.mockResolvedValue({
    sessionId: "guest-session-1",
    role: "guest",
    expiresAt: Date.now() + 3_600_000,
  });
});

async function send(text: string) {
  const textarea = await screen.findByLabelText(/message/i);
  fireEvent.change(textarea, { target: { value: text } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
  });
}

describe("Chat", () => {
  it("renders streamed assistant tokens incrementally", async () => {
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({ event: "start", message_id: "m1" });
      onEvent({ event: "token", content: "Hello" });
      onEvent({ event: "token", content: " world" });
      onEvent({
        event: "done",
        message_id: "m1",
        finish_reason: "stop",
        citations: [],
      });
    });

    render(<Chat />);
    await send("hi");

    expect(await screen.findByText("Hello world")).toBeInTheDocument();
    expect(screen.getByTestId("user-message")).toHaveTextContent("hi");
    // A no-worker / no-citation turn (e.g. smalltalk) shows no plan or citation UI.
    expect(screen.queryByTestId("plan-step")).not.toBeInTheDocument();
    expect(screen.queryByTestId("citations")).not.toBeInTheDocument();
    // The request carried the client-generated session id + message.
    const [payload] = mockStreamChat.mock.calls[0];
    expect(payload.message).toBe("hi");
    expect(payload.session_id).toEqual(expect.any(String));
    expect(payload.session_id.length).toBeGreaterThan(0);
  });

  it("renders the planner/worker step indicator while a turn is in flight", async () => {
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({ event: "start", message_id: "m1" });
      onEvent({
        event: "plan",
        intent: "job_search",
        steps: ["Search for matching roles"],
        workers: ["job_search"],
      });
      onEvent({ event: "token", content: "Here are some roles." });
      onEvent({
        event: "done",
        message_id: "m1",
        finish_reason: "stop",
        citations: [],
      });
    });

    render(<Chat />);
    await send("find me a job");

    const plan = await screen.findByTestId("plan-step");
    expect(plan).toHaveTextContent(/job_search/);
    expect(plan).toHaveTextContent(/Search for matching roles/);
    expect(await screen.findByText("Here are some roles.")).toBeInTheDocument();
  });

  it("does not render a plan indicator for a turn that ran no workers", async () => {
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({ event: "start", message_id: "m1" });
      onEvent({ event: "plan", intent: "chat", steps: [], workers: [] });
      onEvent({ event: "token", content: "Hi there!" });
      onEvent({
        event: "done",
        message_id: "m1",
        finish_reason: "stop",
        citations: [],
      });
    });

    render(<Chat />);
    await send("hello");

    expect(await screen.findByText("Hi there!")).toBeInTheDocument();
    expect(screen.queryByTestId("plan-step")).not.toBeInTheDocument();
  });

  it("renders a citation list under the finished answer", async () => {
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({ event: "start", message_id: "m1" });
      onEvent({ event: "token", content: "Based on the sources…" });
      onEvent({
        event: "done",
        message_id: "m1",
        finish_reason: "stop",
        citations: [
          {
            source_id: "s1",
            title: "Senior Engineer at Acme",
            url: "https://jobs.example/1",
            snippet: null,
            worker: "job_search",
          },
          {
            source_id: "s2",
            title: null,
            url: null,
            snippet: "A relevant knowledge-base excerpt.",
            worker: "rag",
          },
        ],
      });
    });

    render(<Chat />);
    await send("what roles fit me");

    const citations = await screen.findByTestId("citations");
    // A linked title when a url is present…
    const link = screen.getByRole("link", { name: /Senior Engineer at Acme/ });
    expect(link).toHaveAttribute("href", "https://jobs.example/1");
    // …and a plain snippet fallback when there is no url/title.
    expect(citations).toHaveTextContent(/A relevant knowledge-base excerpt\./);
  });

  it("degrades an unsafe-scheme citation url to non-link text", async () => {
    // A poisoned search result could carry a `javascript:` (or `data:`) url;
    // React does not sanitize `href`, so it must never become a clickable anchor.
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({ event: "start", message_id: "m1" });
      onEvent({ event: "token", content: "Answer." });
      onEvent({
        event: "done",
        message_id: "m1",
        finish_reason: "stop",
        citations: [
          {
            source_id: "evil",
            title: "Click me",
            // eslint-disable-next-line no-script-url
            url: "javascript:alert(document.cookie)",
            snippet: null,
            worker: "web_search",
          },
        ],
      });
    });

    render(<Chat />);
    await send("find me something");

    const citations = await screen.findByTestId("citations");
    // The label is still shown as provenance…
    expect(citations).toHaveTextContent(/Click me/);
    // …but never as a link (no anchor rendered for the unsafe scheme).
    expect(
      screen.queryByRole("link", { name: /Click me/ }),
    ).not.toBeInTheDocument();
  });

  it("renders no citation list when the answer has no sources", async () => {
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({ event: "start", message_id: "m1" });
      onEvent({ event: "token", content: "Just chatting." });
      onEvent({
        event: "done",
        message_id: "m1",
        finish_reason: "stop",
        citations: [],
      });
    });

    render(<Chat />);
    await send("hi");

    expect(await screen.findByText("Just chatting.")).toBeInTheDocument();
    expect(screen.queryByTestId("citations")).not.toBeInTheDocument();
  });

  it("shows a visible tool-step indicator distinct from the answer text", async () => {
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({ event: "start", message_id: "m1" });
      onEvent({
        event: "tool_call",
        id: "c1",
        name: "current_date_and_time",
        arguments: "{}",
      });
      onEvent({
        event: "tool_result",
        tool_call_id: "c1",
        name: "current_date_and_time",
        content: '{"now":"noon"}',
      });
      onEvent({ event: "token", content: "It is noon." });
      onEvent({
        event: "done",
        message_id: "m1",
        finish_reason: "stop",
        citations: [],
      });
    });

    render(<Chat />);
    await send("what time is it");

    const step = await screen.findByTestId("tool-step");
    expect(step).toHaveTextContent(/current_date_and_time/);
    // Tool step marked done, and the answer text renders separately.
    await waitFor(() =>
      expect(screen.getByTestId("tool-step")).toHaveTextContent(/done/i),
    );
    expect(await screen.findByText("It is noon.")).toBeInTheDocument();
  });

  it("stop button calls the cancel endpoint and reflects the cancelled event", async () => {
    let capturedOnEvent: ((event: ChatStreamEvent) => void) | undefined;
    let resolveStream: (() => void) | undefined;
    mockStreamChat.mockImplementation((_payload, onEvent) => {
      capturedOnEvent = onEvent;
      onEvent({ event: "start", message_id: "m1" });
      onEvent({ event: "token", content: "partial" });
      return new Promise<void>((resolve) => {
        resolveStream = resolve;
      });
    });
    mockCancelChat.mockResolvedValue(undefined);

    render(<Chat />);
    await send("long question");

    // While streaming, the Stop button is shown; Send is hidden.
    const stop = await screen.findByRole("button", { name: /stop/i });
    fireEvent.click(stop);

    await waitFor(() => expect(mockCancelChat).toHaveBeenCalledTimes(1));
    expect(mockCancelChat.mock.calls[0][0]).toEqual(expect.any(String));

    // Backend responds by emitting the terminal cancelled event, then closing.
    await act(async () => {
      capturedOnEvent?.({ event: "cancelled", message_id: "m1" });
      resolveStream?.();
    });

    expect(await screen.findByTestId("stopped-note")).toHaveTextContent(
      /stopped/i,
    );
    // Partial answer is preserved as-is.
    expect(screen.getByText("partial")).toBeInTheDocument();
  });

  it("renders a visible error state on an error event", async () => {
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({ event: "start", message_id: "m1" });
      onEvent({ event: "error", message: "All models are unavailable." });
    });

    render(<Chat />);
    await send("hi");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/all models are unavailable/i);
  });

  it("carries the hydrated session id and no client-side token on the request", async () => {
    mockStreamChat.mockResolvedValue(undefined);

    render(<Chat />);
    await send("hi");

    const [payload, , options] = mockStreamChat.mock.calls[0];
    expect(payload.session_id).toBe("guest-session-1");
    // No token is passed client-side — the BFF injects Authorization from the cookie.
    expect(options).toBeUndefined();
  });

  it("shows an upgrade prompt (not a raw error) when rate-limited", async () => {
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({
        event: "rate_limited",
        message: "Guest limit reached: at most 10 messages. Sign in to continue.",
        retryAfter: null,
      });
    });

    render(<Chat />);
    await send("hi");

    const prompt = await screen.findByTestId("upgrade-prompt");
    expect(prompt).toHaveTextContent(/sign in to continue/i);
    // Guests get sign-in options to upgrade rather than a dead-end error.
    expect(
      screen.getByRole("button", { name: /sign in with google/i }),
    ).toBeInTheDocument();
  });

  it("falls back to the login screen when the session expires (401)", async () => {
    mockStreamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({
        event: "auth_error",
        message: "Your session has expired. Please sign in again.",
      });
    });

    render(<Chat />);
    await send("hi");

    expect(
      await screen.findByRole("button", { name: /continue as guest/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/expired/i);
  });
});
