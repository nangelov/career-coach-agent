/**
 * Unit tests for the GA4 helper (lib/analytics.ts). Covers the two invariants that matter for the
 * P11-03 acceptance criteria:
 *   1. With no Measurement ID, analytics is fully disabled — `trackEvent` never touches `gtag`.
 *   2. Event parameters are non-content metadata: a free-text-shaped value (a chat message / CV
 *      snippet accidentally passed by a future dev) is dropped before reaching `gtag`.
 *
 * The Measurement ID is read at module load, so each block re-imports the module under a controlled
 * `process.env` via `jest.resetModules()`.
 */

const OLD_ENV = process.env;

afterEach(() => {
  process.env = OLD_ENV;
  delete (window as unknown as { gtag?: unknown }).gtag;
  jest.resetModules();
});

async function loadWithMeasurementId(id?: string) {
  jest.resetModules();
  process.env = { ...OLD_ENV };
  if (id === undefined) {
    delete process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID;
  } else {
    process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID = id;
  }
  return import("@/lib/analytics");
}

describe("sanitizeParams (PII backstop)", () => {
  it("keeps short primitive metadata and drops free-text-shaped strings", async () => {
    const { sanitizeParams } = await loadWithMeasurementId("G-TEST123");
    const cleaned = sanitizeParams({
      role: "guest",
      count: 3,
      flag: true,
      message_id: "550e8400-e29b-41d4-a716-446655440000", // UUID (36) — allowed
      omitted: undefined,
      // A future dev accidentally forwards raw chat content — must be scrubbed.
      note: "The user asked a very long and private question about their salary and health history",
    });
    expect(cleaned).toEqual({
      role: "guest",
      count: 3,
      flag: true,
      message_id: "550e8400-e29b-41d4-a716-446655440000",
    });
    expect(JSON.stringify(cleaned)).not.toContain("private question");
  });
});

describe("trackEvent", () => {
  it("is a no-op (no gtag call) when no Measurement ID is configured", async () => {
    const analytics = await loadWithMeasurementId(undefined);
    const gtag = jest.fn();
    (window as unknown as { gtag?: unknown }).gtag = gtag;

    expect(analytics.isAnalyticsEnabled()).toBe(false);
    analytics.trackEvent("send_message", { role: "guest" });

    expect(gtag).not.toHaveBeenCalled();
  });

  it("forwards a named event with sanitized (content-free) params when configured", async () => {
    const analytics = await loadWithMeasurementId("G-TEST123");
    const gtag = jest.fn();
    (window as unknown as { gtag?: unknown }).gtag = gtag;

    expect(analytics.isAnalyticsEnabled()).toBe(true);
    analytics.trackEvent("message_feedback", {
      rating: "down",
      has_reason: true,
      // Simulated accidental raw content — the guard must strip it.
      reason_text: "I did not like the answer because it mentioned my private medical condition",
    });

    expect(gtag).toHaveBeenCalledTimes(1);
    const [type, name, params] = gtag.mock.calls[0];
    expect(type).toBe("event");
    expect(name).toBe("message_feedback");
    expect(params).toEqual({ rating: "down", has_reason: true });
    // Guard against a future dev leaking message/CV text through a parameter.
    expect(JSON.stringify(params)).not.toContain("medical condition");
  });

  it("does not throw when gtag is undefined (optional-chaining safety)", async () => {
    const analytics = await loadWithMeasurementId("G-TEST123");
    delete (window as unknown as { gtag?: unknown }).gtag;
    expect(() => analytics.trackEvent("stop_generation")).not.toThrow();
  });

  // P11-04 exit-gate proxy for "GA4 real-time shows ≥1 custom event": assert that several
  // of the required product actions each fire gtag('event', <name>) with the correct GA4
  // event name (the human-owner runbook covers confirming these land in the GA4 real-time
  // report against a real Measurement ID).
  it("fires gtag('event', <name>) with the right name for the required product actions", async () => {
    const analytics = await loadWithMeasurementId("G-TEST123");
    const gtag = jest.fn();
    (window as unknown as { gtag?: unknown }).gtag = gtag;

    const actions: { event: Parameters<typeof analytics.trackEvent>[0]; params: Record<string, string | boolean> }[] = [
      { event: "send_message", params: { role: "guest" } },
      { event: "upload_cv", params: { role: "user", file_type: "application/pdf" } },
      { event: "generate_pdp", params: { has_target_date: true, has_context: false } },
    ];

    for (const { event, params } of actions) {
      analytics.trackEvent(event, params);
    }

    expect(gtag).toHaveBeenCalledTimes(actions.length);
    const firedNames = gtag.mock.calls.map(([type, name]) => {
      expect(type).toBe("event");
      return name;
    });
    expect(firedNames).toEqual(["send_message", "upload_cv", "generate_pdp"]);
  });
});
