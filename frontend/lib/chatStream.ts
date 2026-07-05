/**
 * SSE client for the backend chat endpoint (design §9; backend P1-04/P1-06/P1-07).
 *
 * `POST /api/chat` streams **Server-Sent Events** but is a POST with a JSON body,
 * so the browser's native `EventSource` (GET-only) cannot consume it. We instead
 * `fetch()` the endpoint and read `response.body` incrementally with a
 * `ReadableStream` reader, parsing the `event:`/`data:` frames ourselves via
 * {@link createSSEParser}.
 *
 * The wire contract is the backend's `ChatEvent` union (see
 * `backend/app/schemas/chat.py`). The backend serialises each event as
 * `event: <name>\ndata: <json>\n\n`, where the JSON payload **excludes** the
 * `event` field (it lives on the `event:` line). This module reconstructs the
 * fully-typed event by combining the two.
 *
 * Keeping this transport logic here (thin, reusable) — separate from the React
 * component in `components/` — mirrors the backend's Router→Service split.
 */

// --------------------------------------------------------------------------- //
// Event vocabulary (mirrors backend/app/schemas/chat.py)
// --------------------------------------------------------------------------- //
export interface StartEvent {
  event: "start";
  message_id: string;
}

export interface TokenEvent {
  event: "token";
  content: string;
}

export interface ToolCallEvent {
  event: "tool_call";
  id: string;
  name: string;
  arguments: string;
}

export interface ToolResultEvent {
  event: "tool_result";
  tool_call_id: string;
  name: string;
  content: string;
}

export interface DoneEvent {
  event: "done";
  message_id: string;
  finish_reason: string | null;
}

export interface CancelledEvent {
  event: "cancelled";
  message_id: string;
}

export interface ErrorEvent {
  event: "error";
  message: string;
}

/** Every event the chat stream can yield; discriminated by `event`. */
export type ChatStreamEvent =
  | StartEvent
  | TokenEvent
  | ToolCallEvent
  | ToolResultEvent
  | DoneEvent
  | CancelledEvent
  | ErrorEvent;

// --------------------------------------------------------------------------- //
// Frame parser (pure, unit-testable independent of fetch/DOM)
// --------------------------------------------------------------------------- //
export interface SSEParser {
  /** Feed a chunk of decoded text; returns any events completed by this chunk. */
  push(chunk: string): ChatStreamEvent[];
}

/**
 * Build a stateful parser that buffers partial frames across chunk boundaries.
 *
 * Frames are separated by a blank line (`\n\n`). A complete frame is always
 * followed by the separator, so anything after the last separator is an
 * incomplete frame we retain until more bytes arrive.
 */
export function createSSEParser(): SSEParser {
  let buffer = "";
  return {
    push(chunk: string): ChatStreamEvent[] {
      // Normalize CRLF → LF so frame boundaries are always "\n\n" (the backend
      // emits LF, but be tolerant of proxies that rewrite line endings).
      buffer = (buffer + chunk).replace(/\r\n/g, "\n");
      const events: ChatStreamEvent[] = [];
      const frames = buffer.split("\n\n");
      // The final element is an incomplete (or empty) trailing frame.
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const event = parseFrame(frame);
        if (event) {
          events.push(event);
        }
      }
      return events;
    },
  };
}

function parseFrame(raw: string): ChatStreamEvent | null {
  let eventName: string | undefined;
  const dataLines: string[] = [];
  for (const rawLine of raw.split("\n")) {
    // Tolerate CRLF line endings.
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line === "" || line.startsWith(":")) {
      continue; // blank line inside frame / SSE comment
    }
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      // Per SSE spec a single leading space after the colon is stripped.
      dataLines.push(line.slice("data:".length).replace(/^ /, ""));
    }
  }
  if (!eventName) {
    return null;
  }
  const dataStr = dataLines.join("\n");
  let data: Record<string, unknown> = {};
  if (dataStr) {
    try {
      data = JSON.parse(dataStr) as Record<string, unknown>;
    } catch {
      return null; // malformed frame — skip rather than crash the stream
    }
  }
  return toChatEvent(eventName, data);
}

function str(value: unknown): string {
  return value == null ? "" : String(value);
}

function toChatEvent(
  name: string,
  data: Record<string, unknown>,
): ChatStreamEvent | null {
  switch (name) {
    case "start":
      return { event: "start", message_id: str(data.message_id) };
    case "token":
      return { event: "token", content: str(data.content) };
    case "tool_call":
      return {
        event: "tool_call",
        id: str(data.id),
        name: str(data.name),
        arguments: str(data.arguments),
      };
    case "tool_result":
      return {
        event: "tool_result",
        tool_call_id: str(data.tool_call_id),
        name: str(data.name),
        content: str(data.content),
      };
    case "done":
      return {
        event: "done",
        message_id: str(data.message_id),
        finish_reason:
          data.finish_reason == null ? null : String(data.finish_reason),
      };
    case "cancelled":
      return { event: "cancelled", message_id: str(data.message_id) };
    case "error":
      return { event: "error", message: str(data.message) };
    default:
      return null; // unknown event name — ignore forward-compatibly
  }
}

// --------------------------------------------------------------------------- //
// Transport
// --------------------------------------------------------------------------- //
export interface ChatHistoryMessage {
  role: string;
  content: string | null;
  [key: string]: unknown;
}

export interface ChatRequestPayload {
  session_id: string;
  message: string;
  history?: ChatHistoryMessage[];
}

export interface StreamChatOptions {
  /** Abort the in-flight fetch (e.g. on unmount). */
  signal?: AbortSignal;
  /** Base URL override; defaults to same-origin ("" → dev proxy / prod proxy). */
  baseUrl?: string;
  /** Injected fetch for testing. */
  fetchImpl?: typeof fetch;
}

function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === "AbortError";
}

function networkErrorMessage(err: unknown): string {
  const detail = err instanceof Error ? err.message : String(err);
  return `Could not reach the chat service: ${detail}`;
}

/**
 * Open the chat SSE stream and invoke `onEvent` for every parsed event, in order.
 *
 * Resolves once the stream ends (a terminal `done`/`cancelled`/`error` frame or
 * the connection closing). Network / non-2xx failures are surfaced as a synthetic
 * terminal `error` event (so the caller has a single code path) rather than a
 * thrown rejection. An aborted fetch resolves quietly.
 */
export async function streamChat(
  payload: ChatRequestPayload,
  onEvent: (event: ChatStreamEvent) => void,
  options: StreamChatOptions = {},
): Promise<void> {
  const { signal, baseUrl = "", fetchImpl = fetch } = options;

  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (err) {
    if (isAbortError(err)) {
      return;
    }
    onEvent({ event: "error", message: networkErrorMessage(err) });
    return;
  }

  if (!response.ok || !response.body) {
    onEvent({
      event: "error",
      message: `Chat request failed (HTTP ${response.status}).`,
    });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSSEParser();

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      const chunk = decoder.decode(value, { stream: true });
      for (const event of parser.push(chunk)) {
        onEvent(event);
      }
    }
    // Flush any bytes the decoder was holding for a multi-byte boundary.
    const tail = decoder.decode();
    if (tail) {
      for (const event of parser.push(tail)) {
        onEvent(event);
      }
    }
  } catch (err) {
    if (!isAbortError(err)) {
      onEvent({ event: "error", message: networkErrorMessage(err) });
    }
  } finally {
    reader.releaseLock();
  }
}

export interface CancelChatOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}

/**
 * Ask the backend to stop the in-flight turn for `sessionId`
 * (`POST /api/chat/{session}/cancel`, returns 202). The active stream then emits
 * a terminal `cancelled` event and closes on its own.
 */
export async function cancelChat(
  sessionId: string,
  options: CancelChatOptions = {},
): Promise<void> {
  const { baseUrl = "", fetchImpl = fetch } = options;
  await fetchImpl(
    `${baseUrl}/api/chat/${encodeURIComponent(sessionId)}/cancel`,
    { method: "POST" },
  );
}
