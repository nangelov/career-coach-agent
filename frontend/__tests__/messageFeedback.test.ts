import {
  MessageFeedbackApiError,
  submitMessageFeedback,
} from "@/lib/messageFeedback";

/** A minimal ok/json Response stand-in. */
function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("submitMessageFeedback", () => {
  it("POSTs the rating to the message's feedback endpoint and parses the stored row", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(
        jsonResponse({
          message_id: "m1",
          rating: "up",
          reason: null,
          created_at: "2026-07-19T00:00:00Z",
        }),
      );

    const stored = await submitMessageFeedback("m1", "up", undefined, { fetchImpl });

    expect(stored).toEqual({
      message_id: "m1",
      rating: "up",
      reason: null,
      created_at: "2026-07-19T00:00:00Z",
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/messages/m1/feedback");
    expect(init.method).toBe("POST");
    // No reason → omitted from the body (not sent as an empty string).
    expect(JSON.parse(init.body)).toEqual({ rating: "up" });
  });

  it("includes a trimmed reason on a thumbs-down", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({
        message_id: "m2",
        rating: "down",
        reason: "Too vague",
        created_at: "2026-07-19T00:00:00Z",
      }),
    );

    const stored = await submitMessageFeedback("m2", "down", "  Too vague  ", {
      fetchImpl,
    });

    expect(stored.rating).toBe("down");
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({
      rating: "down",
      reason: "Too vague",
    });
  });

  it("encodes the message id in the path", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(
        jsonResponse({ message_id: "a/b", rating: "up", reason: null, created_at: "" }),
      );

    await submitMessageFeedback("a/b", "up", undefined, { fetchImpl });

    expect(fetchImpl.mock.calls[0][0]).toBe("/api/messages/a%2Fb/feedback");
  });

  it("throws a typed error carrying the HTTP status on a 404", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "Message not found." }, false, 404));

    await expect(
      submitMessageFeedback("gone", "down", undefined, { fetchImpl }),
    ).rejects.toMatchObject({ name: "MessageFeedbackApiError", status: 404 });
  });

  it("surfaces a fallback message when the error body is not JSON", async () => {
    const fetchImpl = jest.fn().mockResolvedValue({
      ok: false,
      status: 429,
      json: async () => {
        throw new Error("no body");
      },
    } as unknown as Response);

    await expect(
      submitMessageFeedback("m1", "up", undefined, { fetchImpl }),
    ).rejects.toThrow(MessageFeedbackApiError);
  });
});
