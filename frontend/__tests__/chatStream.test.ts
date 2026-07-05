import {
  cancelChat,
  createSSEParser,
  streamChat,
  type ChatStreamEvent,
} from "@/lib/chatStream";

// --------------------------------------------------------------------------- //
// createSSEParser — pure frame parsing, independent of fetch/DOM
// --------------------------------------------------------------------------- //
describe("createSSEParser", () => {
  it("parses a single complete frame (event on its own line, data JSON)", () => {
    const parser = createSSEParser();
    const events = parser.push('event: start\ndata: {"message_id": "m1"}\n\n');
    expect(events).toEqual([{ event: "start", message_id: "m1" }]);
  });

  it("parses each SSE event type in the vocabulary", () => {
    const parser = createSSEParser();
    const frames = [
      'event: start\ndata: {"message_id": "m1"}\n\n',
      'event: token\ndata: {"content": "Hel"}\n\n',
      'event: tool_call\ndata: {"id": "c1", "name": "clock", "arguments": "{}"}\n\n',
      'event: tool_result\ndata: {"tool_call_id": "c1", "name": "clock", "content": "{\\"now\\":\\"noon\\"}"}\n\n',
      'event: done\ndata: {"message_id": "m1", "finish_reason": "stop"}\n\n',
      'event: cancelled\ndata: {"message_id": "m1"}\n\n',
      'event: error\ndata: {"message": "boom"}\n\n',
    ].join("");
    expect(parser.push(frames)).toEqual([
      { event: "start", message_id: "m1" },
      { event: "token", content: "Hel" },
      { event: "tool_call", id: "c1", name: "clock", arguments: "{}" },
      {
        event: "tool_result",
        tool_call_id: "c1",
        name: "clock",
        content: '{"now":"noon"}',
      },
      { event: "done", message_id: "m1", finish_reason: "stop" },
      { event: "cancelled", message_id: "m1" },
      { event: "error", message: "boom" },
    ]);
  });

  it("reassembles a frame split across arbitrary chunk boundaries", () => {
    const parser = createSSEParser();
    const whole = 'event: token\ndata: {"content": "hello world"}\n\n';
    const collected: ChatStreamEvent[] = [];
    for (const ch of whole) {
      collected.push(...parser.push(ch));
    }
    expect(collected).toEqual([{ event: "token", content: "hello world" }]);
  });

  it("emits multiple events that arrive in one chunk and buffers a partial tail", () => {
    const parser = createSSEParser();
    const first = parser.push(
      'event: token\ndata: {"content": "a"}\n\nevent: token\ndata: {"content": "b"}\n\nevent: tok',
    );
    expect(first).toEqual([
      { event: "token", content: "a" },
      { event: "token", content: "b" },
    ]);
    // The partial "event: tok..." frame is retained until completed.
    const second = parser.push('en\ndata: {"content": "c"}\n\n');
    expect(second).toEqual([{ event: "token", content: "c" }]);
  });

  it("tolerates CRLF line endings", () => {
    const parser = createSSEParser();
    const events = parser.push(
      'event: token\r\ndata: {"content": "x"}\r\n\r\n',
    );
    expect(events).toEqual([{ event: "token", content: "x" }]);
  });

  it("skips malformed JSON without crashing the stream", () => {
    const parser = createSSEParser();
    const events = parser.push(
      "event: token\ndata: {not json}\n\nevent: token\ndata: {\"content\": \"ok\"}\n\n",
    );
    expect(events).toEqual([{ event: "token", content: "ok" }]);
  });

  it("ignores unknown event names forward-compatibly", () => {
    const parser = createSSEParser();
    const events = parser.push('event: future\ndata: {"x": 1}\n\n');
    expect(events).toEqual([]);
  });
});

// --------------------------------------------------------------------------- //
// streamChat — fetch + ReadableStream reader
// --------------------------------------------------------------------------- //
function encode(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

/** Build a fake Response whose body yields the given text chunks in order. */
function fakeStreamResponse(chunks: string[], ok = true, status = 200): Response {
  let i = 0;
  const body = {
    getReader() {
      return {
        read(): Promise<{ done: boolean; value?: Uint8Array }> {
          if (i < chunks.length) {
            const value = encode(chunks[i]);
            i += 1;
            return Promise.resolve({ done: false, value });
          }
          return Promise.resolve({ done: true, value: undefined });
        },
        releaseLock() {},
      };
    },
  };
  return { ok, status, body } as unknown as Response;
}

describe("streamChat", () => {
  it("POSTs the payload and yields parsed events in order", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      fakeStreamResponse([
        'event: start\ndata: {"message_id": "m1"}\n\n',
        'event: token\ndata: {"content": "Hi"}\n\n',
        'event: done\ndata: {"message_id": "m1", "finish_reason": "stop"}\n\n',
      ]),
    );
    const events: ChatStreamEvent[] = [];
    await streamChat(
      { session_id: "s1", message: "hello" },
      (e) => events.push(e),
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/chat");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      session_id: "s1",
      message: "hello",
    });
    expect(events).toEqual([
      { event: "start", message_id: "m1" },
      { event: "token", content: "Hi" },
      { event: "done", message_id: "m1", finish_reason: "stop" },
    ]);
  });

  it("surfaces a non-2xx response as a terminal error event", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(fakeStreamResponse([], false, 500));
    const events: ChatStreamEvent[] = [];
    await streamChat(
      { session_id: "s1", message: "hi" },
      (e) => events.push(e),
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("error");
  });

  it("surfaces a rejected fetch (network failure) as a terminal error event", async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error("offline"));
    const events: ChatStreamEvent[] = [];
    await streamChat(
      { session_id: "s1", message: "hi" },
      (e) => events.push(e),
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ event: "error" });
  });

  it("stays quiet when the fetch is aborted", async () => {
    const abortError = new Error("aborted");
    abortError.name = "AbortError";
    const fetchImpl = jest.fn().mockRejectedValue(abortError);
    const events: ChatStreamEvent[] = [];
    await streamChat(
      { session_id: "s1", message: "hi" },
      (e) => events.push(e),
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(events).toEqual([]);
  });
});

// --------------------------------------------------------------------------- //
// cancelChat
// --------------------------------------------------------------------------- //
describe("cancelChat", () => {
  it("POSTs to the session cancel endpoint", async () => {
    const fetchImpl = jest.fn().mockResolvedValue({ ok: true, status: 202 });
    await cancelChat("s 1", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl).toHaveBeenCalledWith("/api/chat/s%201/cancel", {
      method: "POST",
    });
  });
});
