"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelChat,
  streamChat,
  type ChatStreamEvent,
} from "@/lib/chatStream";

const SESSION_STORAGE_KEY = "cc.session_id";

type Role = "user" | "assistant";
type TurnStatus = "streaming" | "done" | "cancelled" | "error";

interface ToolStep {
  id: string;
  name: string;
  status: "calling" | "done";
  result?: string;
}

interface ChatMessageView {
  key: string;
  role: Role;
  content: string;
  status: TurnStatus;
  toolSteps: ToolStep[];
  errorMessage?: string;
}

function randomId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export default function Chat() {
  const [messages, setMessages] = useState<ChatMessageView[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);

  // Generate/persist a client-side session id. There is no auth/session-creation
  // endpoint yet (that is P3), so the frontend owns id generation for now.
  useEffect(() => {
    let sid = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!sid) {
      sid = randomId();
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, sid);
    }
    setSessionId(sid);
  }, []);

  useEffect(() => {
    // Optional-chain the method itself: jsdom does not implement scrollIntoView.
    scrollAnchorRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages]);

  // Update the assistant message of the turn in flight (always the last message).
  const updateAssistant = useCallback(
    (updater: (message: ChatMessageView) => ChatMessageView) => {
      setMessages((prev) => {
        const last = prev.length - 1;
        if (last < 0 || prev[last].role !== "assistant") {
          return prev;
        }
        const next = [...prev];
        next[last] = updater(next[last]);
        return next;
      });
    },
    [],
  );

  const handleEvent = useCallback(
    (event: ChatStreamEvent) => {
      switch (event.event) {
        case "start":
          break;
        case "token":
          updateAssistant((m) => ({ ...m, content: m.content + event.content }));
          break;
        case "tool_call":
          updateAssistant((m) => ({
            ...m,
            toolSteps: [
              ...m.toolSteps,
              { id: event.id, name: event.name, status: "calling" },
            ],
          }));
          break;
        case "tool_result":
          updateAssistant((m) => ({
            ...m,
            toolSteps: m.toolSteps.map((step) =>
              step.id === event.tool_call_id
                ? { ...step, status: "done", result: event.content }
                : step,
            ),
          }));
          break;
        case "done":
          updateAssistant((m) => ({ ...m, status: "done" }));
          break;
        case "cancelled":
          updateAssistant((m) => ({ ...m, status: "cancelled" }));
          break;
        case "error":
          updateAssistant((m) => ({
            ...m,
            status: "error",
            errorMessage: event.message,
          }));
          break;
      }
    },
    [updateAssistant],
  );

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming || !sessionId) {
      return;
    }
    const userMessage: ChatMessageView = {
      key: randomId(),
      role: "user",
      content: text,
      status: "done",
      toolSteps: [],
    };
    const assistantMessage: ChatMessageView = {
      key: randomId(),
      role: "assistant",
      content: "",
      status: "streaming",
      toolSteps: [],
    };
    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setInput("");
    setIsStreaming(true);
    try {
      await streamChat(
        { session_id: sessionId, message: text },
        handleEvent,
      );
    } finally {
      setIsStreaming(false);
    }
  }, [handleEvent, input, isStreaming, sessionId]);

  const handleStop = useCallback(async () => {
    if (!sessionId || !isStreaming) {
      return;
    }
    // The backend sets a cancel flag and returns 202; the active stream then
    // emits a terminal `cancelled` event and closes on its own.
    await cancelChat(sessionId);
  }, [isStreaming, sessionId]);

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  };

  return (
    <div className="mx-auto flex h-screen w-full max-w-3xl flex-col p-4">
      <header className="border-b border-gray-200 pb-3">
        <h1 className="text-xl font-semibold">Career Coach</h1>
      </header>

      <div
        className="flex-1 space-y-4 overflow-y-auto py-4"
        role="log"
        aria-live="polite"
      >
        {messages.length === 0 ? (
          <p className="text-gray-400">Ask anything about your career.</p>
        ) : null}
        {messages.map((message) =>
          message.role === "user" ? (
            <UserBubble key={message.key} content={message.content} />
          ) : (
            <AssistantBubble key={message.key} message={message} />
          ),
        )}
        <div ref={scrollAnchorRef} />
      </div>

      <form
        className="flex items-end gap-2 border-t border-gray-200 pt-3"
        onSubmit={(event) => {
          event.preventDefault();
          void handleSend();
        }}
      >
        <textarea
          className="flex-1 resize-none rounded-md border border-gray-300 p-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          rows={2}
          placeholder="Type your message…"
          aria-label="Message"
          value={input}
          disabled={isStreaming}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={onInputKeyDown}
        />
        {isStreaming ? (
          <button
            type="button"
            className="rounded-md bg-red-600 px-4 py-2 font-medium text-white hover:bg-red-700"
            onClick={() => void handleStop()}
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            disabled={!input.trim() || !sessionId}
          >
            Send
          </button>
        )}
      </form>
    </div>
  );
}

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end" data-testid="user-message">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-lg bg-blue-600 px-4 py-2 text-white">
        {content}
      </div>
    </div>
  );
}

function AssistantBubble({ message }: { message: ChatMessageView }) {
  return (
    <div className="flex justify-start" data-testid="assistant-message">
      <div className="max-w-[80%] space-y-2">
        {message.toolSteps.map((step) => (
          <ToolStepIndicator key={step.id} step={step} />
        ))}
        {message.content ? (
          <div className="whitespace-pre-wrap rounded-lg bg-gray-100 px-4 py-2 text-gray-900">
            {message.content}
          </div>
        ) : null}
        {message.status === "streaming" && !message.content ? (
          <div
            className="rounded-lg bg-gray-100 px-4 py-2 text-gray-400"
            data-testid="thinking"
          >
            Thinking…
          </div>
        ) : null}
        {message.status === "cancelled" ? (
          <p className="text-sm italic text-gray-500" data-testid="stopped-note">
            Stopped
          </p>
        ) : null}
        {message.status === "error" ? (
          <div
            className="rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700"
            role="alert"
            data-testid="error-note"
          >
            {message.errorMessage ?? "Something went wrong."}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ToolStepIndicator({ step }: { step: ToolStep }) {
  return (
    <div
      className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-sm text-amber-800"
      data-testid="tool-step"
    >
      {step.status === "calling" ? (
        <span>
          🔧 calling <code className="font-mono">{step.name}</code>…
        </span>
      ) : (
        <span>
          ✓ <code className="font-mono">{step.name}</code> done
        </span>
      )}
    </div>
  );
}
