"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import Login from "@/components/Login";
import UpgradePrompt from "@/components/UpgradePrompt";
import { fetchSession, logout, type Session } from "@/lib/auth";
import { safeHttpUrl } from "@/lib/url";
import {
  cancelChat,
  streamChat,
  type ChatStreamEvent,
  type SourceCitation,
} from "@/lib/chatStream";
import {
  MessageFeedbackApiError,
  submitMessageFeedback,
  type MessageRating,
} from "@/lib/messageFeedback";

type Role = "user" | "assistant";
type TurnStatus = "streaming" | "done" | "cancelled" | "error";

interface ToolStep {
  id: string;
  name: string;
  status: "calling" | "done";
  result?: string;
}

interface TurnPlan {
  intent: string;
  steps: string[];
  workers: string[];
}

interface ChatMessageView {
  key: string;
  role: Role;
  content: string;
  status: TurnStatus;
  toolSteps: ToolStep[];
  plan?: TurnPlan;
  citations: SourceCitation[];
  errorMessage?: string;
  /**
   * The turn's stable backend message id, stamped from the `start`/`done`/`cancelled` stream
   * events (P9-01). Present once the backend has assigned it; the per-message 👍/👎 controls
   * address this id (a turn that never received one shows no feedback controls).
   */
  messageId?: string;
}

// Friendly messages for the `?login_error=<reason>` the SSO login BFF redirects back with
// when a login could not start (FIX-12). Keyed by the reason codes emitted in
// `app/api/auth/login/[provider]/route.ts`; `default` covers any unmapped reason.
const LOGIN_ERROR_MESSAGES: Record<string, string> = {
  provider_unavailable:
    "That sign-in option isn't available right now. Please try another provider or continue as a guest.",
  unknown_provider:
    "That sign-in option isn't supported. Please try another provider or continue as a guest.",
  consent_required:
    "Please accept the Terms of Service and Privacy Notice to sign in.",
  default: "Sign-in could not be completed. Please try again or continue as a guest.",
};

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
  const [session, setSession] = useState<Session | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginMessage, setLoginMessage] = useState<string | null>(null);
  const [rateLimit, setRateLimit] = useState<{ message: string } | null>(null);
  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);

  // Hydrate the session from the httpOnly cookie via the BFF `GET /api/auth/session`
  // (SEC-04 — no localStorage). The token never reaches the browser; we only learn the
  // token-free session state (sessionId/role/expiry) needed to render.
  useEffect(() => {
    let cancelled = false;
    void fetchSession()
      .then((next) => {
        if (!cancelled) {
          setSession(next);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setAuthChecked(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Surface a login failure the SSO BFF signalled via `?login_error=...` (FIX-12): an
  // unconfigured provider now fails in-stack and redirects back here with a reason instead
  // of dumping the user on the provider's own error page. Show it once on the login screen,
  // then strip the param so a refresh is clean.
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const reason = params.get("login_error");
    if (!reason) {
      return;
    }
    setLoginMessage(LOGIN_ERROR_MESSAGES[reason] ?? LOGIN_ERROR_MESSAGES.default);
    params.delete("login_error");
    const query = params.toString();
    const cleanUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", cleanUrl);
  }, []);

  useEffect(() => {
    // Optional-chain the method itself: jsdom does not implement scrollIntoView.
    scrollAnchorRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages]);

  const handleAuthenticated = useCallback((next: Session) => {
    setLoginMessage(null);
    setSession(next);
  }, []);

  const handleLogout = useCallback(async () => {
    await logout();
    setSession(null);
    setMessages([]);
    setRateLimit(null);
  }, []);

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

  // Remove the trailing empty assistant placeholder (used when a turn never streams —
  // e.g. rate-limited/expired before the first token).
  const dropPendingAssistant = useCallback(() => {
    setMessages((prev) => {
      const last = prev.length - 1;
      if (
        last >= 0 &&
        prev[last].role === "assistant" &&
        prev[last].content === "" &&
        prev[last].status === "streaming"
      ) {
        return prev.slice(0, last);
      }
      return prev;
    });
  }, []);

  const handleEvent = useCallback(
    (event: ChatStreamEvent) => {
      switch (event.event) {
        case "start":
          // Stamp the turn's stable message id as early as it's known (also on done/cancelled).
          updateAssistant((m) => ({ ...m, messageId: event.message_id }));
          break;
        case "plan":
          updateAssistant((m) => ({
            ...m,
            plan: {
              intent: event.intent,
              steps: event.steps,
              workers: event.workers,
            },
          }));
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
          updateAssistant((m) => ({
            ...m,
            status: "done",
            citations: event.citations,
            messageId: event.message_id,
          }));
          break;
        case "cancelled":
          updateAssistant((m) => ({
            ...m,
            status: "cancelled",
            messageId: event.message_id,
          }));
          break;
        case "error":
          updateAssistant((m) => ({
            ...m,
            status: "error",
            errorMessage: event.message,
          }));
          break;
        case "auth_error":
          // Expired/invalid session: clear the cookie (best-effort) and fall back to login.
          void logout();
          dropPendingAssistant();
          setLoginMessage(event.message);
          setSession(null);
          break;
        case "rate_limited":
          // Show the upgrade prompt (not a raw error); the turn never started.
          dropPendingAssistant();
          setRateLimit({ message: event.message });
          break;
      }
    },
    [dropPendingAssistant, updateAssistant],
  );

  // Send one turn through the streaming path. Shared by the composer (`handleSend`) and the
  // down-vote "Try again?" affordance (§5.5) — a regenerate is just re-sending the same user text.
  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming || !session) {
        return;
      }
      setRateLimit(null);
      const userMessage: ChatMessageView = {
        key: randomId(),
        role: "user",
        content: trimmed,
        status: "done",
        toolSteps: [],
        citations: [],
      };
      const assistantMessage: ChatMessageView = {
        key: randomId(),
        role: "assistant",
        content: "",
        status: "streaming",
        toolSteps: [],
        citations: [],
      };
      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsStreaming(true);
      try {
        await streamChat(
          { session_id: session.sessionId, message: trimmed },
          handleEvent,
        );
      } finally {
        setIsStreaming(false);
      }
    },
    [handleEvent, isStreaming, session],
  );

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text) {
      return;
    }
    setInput("");
    await sendMessage(text);
  }, [input, sendMessage]);

  const handleStop = useCallback(async () => {
    if (!session || !isStreaming) {
      return;
    }
    // The backend sets a cancel flag and returns 202; the active stream then
    // emits a terminal `cancelled` event and closes on its own.
    await cancelChat(session.sessionId);
  }, [isStreaming, session]);

  const onInputKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  };

  // Avoid a hydration flash / premature login screen before the session is resolved.
  if (!authChecked) {
    return null;
  }

  if (!session) {
    return (
      <Login onAuthenticated={handleAuthenticated} message={loginMessage ?? undefined} />
    );
  }

  return (
    <div className="mx-auto flex h-screen w-full max-w-3xl flex-col p-4">
      <header className="flex items-center justify-between border-b border-gray-200 pb-3">
        <h1 className="text-xl font-semibold">Career Coach</h1>
        <div className="flex items-center gap-3 text-sm text-gray-500">
          <span data-testid="session-role">
            {session.role === "guest" ? "Guest" : "Signed in"}
          </span>
          <Link
            href="/dashboard"
            className="rounded-md border border-gray-300 px-3 py-1 font-medium text-gray-700 hover:bg-gray-50"
          >
            Dashboard
          </Link>
          <Link
            href="/roles"
            className="rounded-md border border-gray-300 px-3 py-1 font-medium text-gray-700 hover:bg-gray-50"
          >
            Roles
          </Link>
          <Link
            href="/profile"
            className="rounded-md border border-gray-300 px-3 py-1 font-medium text-gray-700 hover:bg-gray-50"
          >
            Profile
          </Link>
          <Link
            href="/pdp"
            className="rounded-md border border-gray-300 px-3 py-1 font-medium text-gray-700 hover:bg-gray-50"
          >
            Plan
          </Link>
          <Link
            href="/memory"
            className="rounded-md border border-gray-300 px-3 py-1 font-medium text-gray-700 hover:bg-gray-50"
          >
            Memory
          </Link>
          <button
            type="button"
            className="rounded-md border border-gray-300 px-3 py-1 font-medium text-gray-700 hover:bg-gray-50"
            onClick={() => void handleLogout()}
          >
            Log out
          </button>
        </div>
      </header>

      <div
        className="flex-1 space-y-4 overflow-y-auto py-4"
        role="log"
        aria-live="polite"
      >
        {messages.length === 0 ? (
          <p className="text-gray-400">Ask anything about your career.</p>
        ) : null}
        {messages.map((message, index) =>
          message.role === "user" ? (
            <UserBubble key={message.key} content={message.content} />
          ) : (
            <AssistantBubble
              key={message.key}
              message={message}
              onTryAgain={() => {
                const prior = messages[index - 1];
                if (prior && prior.role === "user") {
                  void sendMessage(prior.content);
                }
              }}
            />
          ),
        )}
        <div ref={scrollAnchorRef} />
      </div>

      {rateLimit ? (
        <div className="pt-3">
          <UpgradePrompt
            session={session}
            message={rateLimit.message}
            onDismiss={() => setRateLimit(null)}
          />
        </div>
      ) : null}

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
            disabled={!input.trim()}
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

function AssistantBubble({
  message,
  onTryAgain,
}: {
  message: ChatMessageView;
  onTryAgain?: () => void;
}) {
  return (
    <div className="flex justify-start" data-testid="assistant-message">
      <div className="max-w-[80%] space-y-2">
        {message.plan && message.plan.workers.length > 0 ? (
          <PlanIndicator plan={message.plan} />
        ) : null}
        {message.toolSteps.map((step) => (
          <ToolStepIndicator key={step.id} step={step} />
        ))}
        {message.content ? (
          <div className="whitespace-pre-wrap rounded-lg bg-gray-100 px-4 py-2 text-gray-900">
            {message.content}
          </div>
        ) : null}
        {message.citations.length > 0 ? (
          <CitationList citations={message.citations} />
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
        {/* Per-message 👍/👎 (+ inline "Try again?") — only on a completed, id-stamped turn (§5.5). */}
        {message.status === "done" && message.messageId ? (
          <MessageFeedbackControls
            messageId={message.messageId}
            onTryAgain={onTryAgain}
          />
        ) : null}
      </div>
    </div>
  );
}

// Per-message feedback widget (§5.5): 👍/👎 on a completed assistant turn. A thumbs-down submits
// immediately, then reveals an optional one-line "why" input and an inline "Try again?" affordance
// that re-runs the same user turn. Submissions are idempotent upserts (backend P9-01) — toggling
// or resubmitting updates the stored row, so we simply reflect the last confirmed rating.
function MessageFeedbackControls({
  messageId,
  onTryAgain,
}: {
  messageId: string;
  onTryAgain?: () => void;
}) {
  const [rating, setRating] = useState<MessageRating | null>(null);
  const [reason, setReason] = useState("");
  const [showReason, setShowReason] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(
    async (next: MessageRating, reasonText?: string) => {
      setPending(true);
      setError(null);
      try {
        const stored = await submitMessageFeedback(messageId, next, reasonText);
        setRating(stored.rating);
      } catch (err) {
        setError(
          err instanceof MessageFeedbackApiError
            ? err.message
            : "Couldn't save your feedback. Please try again.",
        );
      } finally {
        setPending(false);
      }
    },
    [messageId],
  );

  const handleUp = useCallback(() => {
    setShowReason(false);
    void submit("up");
  }, [submit]);

  const handleDown = useCallback(() => {
    setShowReason(true);
    void submit("down");
  }, [submit]);

  return (
    <div
      className="flex flex-col gap-1.5 text-sm text-gray-500"
      data-testid="message-feedback"
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label="Good response"
          aria-pressed={rating === "up"}
          disabled={pending}
          className={`rounded-md border px-2 py-1 hover:bg-gray-50 disabled:opacity-50 ${
            rating === "up"
              ? "border-green-400 bg-green-50 text-green-700"
              : "border-gray-300"
          }`}
          onClick={handleUp}
        >
          👍
        </button>
        <button
          type="button"
          aria-label="Bad response"
          aria-pressed={rating === "down"}
          disabled={pending}
          className={`rounded-md border px-2 py-1 hover:bg-gray-50 disabled:opacity-50 ${
            rating === "down"
              ? "border-red-400 bg-red-50 text-red-700"
              : "border-gray-300"
          }`}
          onClick={handleDown}
        >
          👎
        </button>
        {rating === "down" && onTryAgain ? (
          <button
            type="button"
            className="rounded-md border border-blue-300 px-2 py-1 font-medium text-blue-700 hover:bg-blue-50"
            data-testid="try-again"
            onClick={onTryAgain}
          >
            Try again?
          </button>
        ) : null}
      </div>

      {showReason ? (
        <div className="flex items-center gap-2">
          <input
            type="text"
            className="flex-1 rounded-md border border-gray-300 p-1.5 text-sm"
            placeholder="What was wrong? (optional)"
            aria-label="Why was this response unhelpful?"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <button
            type="button"
            className="rounded-md border border-gray-300 px-2 py-1 hover:bg-gray-50 disabled:opacity-50"
            disabled={pending || !reason.trim()}
            onClick={() => void submit("down", reason)}
          >
            Send
          </button>
        </div>
      ) : null}

      {error ? (
        <p
          className="text-xs text-red-600"
          role="alert"
          data-testid="feedback-error"
        >
          {error}
        </p>
      ) : null}
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

// The planner/worker "visible thinking" strip (design §3): the classified intent, which workers
// ran, and — if the planner produced them — the human-readable steps. Reuses the amber tool-step
// visual language. Only rendered when at least one worker ran (see AssistantBubble).
function PlanIndicator({ plan }: { plan: TurnPlan }) {
  return (
    <div
      className="rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-sm text-amber-800"
      data-testid="plan-step"
    >
      <span>
        🧭 Planning: <code className="font-mono">{plan.intent}</code> → running{" "}
        {plan.workers.join(", ")}
      </span>
      {plan.steps.length > 0 ? (
        <ul className="mt-1 list-disc pl-5 text-xs">
          {plan.steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// Compact grounding-source list rendered under a finished answer (design §3 "cite sources").
// Every field is optional, so each entry degrades: a linked title when a url+title exist, else a
// plain title/snippet/source_id — whatever provenance the worker supplied.
function CitationList({ citations }: { citations: SourceCitation[] }) {
  return (
    <div
      className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600"
      data-testid="citations"
    >
      <p className="mb-1 font-medium text-gray-500">Sources</p>
      <ol className="list-decimal space-y-0.5 pl-5">
        {citations.map((citation, i) => (
          <li
            key={`${citation.source_id ?? citation.url ?? "src"}-${i}`}
            data-testid="citation"
          >
            <CitationEntry citation={citation} />
          </li>
        ))}
      </ol>
    </div>
  );
}

// Citation urls come from untrusted third-party content (search-result / crawled-page urls the
// web-search worker forwards verbatim); {@link safeHttpUrl} (lib/url) gates them so only parseable
// http(s) links become clickable anchors — anything else degrades to plain text below.
function CitationEntry({ citation }: { citation: SourceCitation }) {
  const label =
    citation.title || citation.snippet || citation.url || citation.source_id;
  const href = safeHttpUrl(citation.url);
  if (href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 underline hover:text-blue-800"
      >
        {label || href}
      </a>
    );
  }
  return <span>{label || "Untitled source"}</span>;
}
