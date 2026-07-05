import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import Chat from "@/components/Chat";
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

const mockStreamChat = streamChat as jest.MockedFunction<typeof streamChat>;
const mockCancelChat = cancelChat as jest.MockedFunction<typeof cancelChat>;

beforeEach(() => {
  jest.clearAllMocks();
  window.sessionStorage.clear();
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
      onEvent({ event: "done", message_id: "m1", finish_reason: "stop" });
    });

    render(<Chat />);
    await send("hi");

    expect(await screen.findByText("Hello world")).toBeInTheDocument();
    expect(screen.getByTestId("user-message")).toHaveTextContent("hi");
    // The request carried the client-generated session id + message.
    const [payload] = mockStreamChat.mock.calls[0];
    expect(payload.message).toBe("hi");
    expect(payload.session_id).toEqual(expect.any(String));
    expect(payload.session_id.length).toBeGreaterThan(0);
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
      onEvent({ event: "done", message_id: "m1", finish_reason: "stop" });
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
});
