import {
  filenameFromDisposition,
  generatePdp,
  PdpApiError,
} from "@/lib/pdp";

/** A minimal Response stand-in for a binary (PDF) success. */
function pdfResponse(
  headers: Record<string, string>,
  { ok = true, status = 200 }: { ok?: boolean; status?: number } = {},
): Response {
  const blob = new Blob(["%PDF-1.4 fake"], { type: "application/pdf" });
  return {
    ok,
    status,
    blob: async () => blob,
    headers: { get: (name: string) => headers[name] ?? headers[name.toLowerCase()] ?? null },
  } as unknown as Response;
}

/** A minimal JSON error Response stand-in (FastAPI `{detail}`). */
function errorResponse(body: unknown, status: number): Response {
  return {
    ok: false,
    status,
    json: async () => body,
    headers: { get: () => null },
  } as unknown as Response;
}

// --------------------------------------------------------------------------- //
// filenameFromDisposition
// --------------------------------------------------------------------------- //
describe("filenameFromDisposition", () => {
  it("extracts the filename from an attachment disposition", () => {
    expect(
      filenameFromDisposition("attachment; filename=PDP_Senior-Engineer.pdf"),
    ).toBe("PDP_Senior-Engineer.pdf");
  });

  it("handles a quoted / UTF-8 filename", () => {
    expect(
      filenameFromDisposition("attachment; filename*=UTF-8''PDP_Data%20Scientist.pdf"),
    ).toBe("PDP_Data Scientist.pdf");
  });

  it("falls back to PDP.pdf when absent or unparseable", () => {
    expect(filenameFromDisposition(null)).toBe("PDP.pdf");
    expect(filenameFromDisposition("attachment")).toBe("PDP.pdf");
  });
});

// --------------------------------------------------------------------------- //
// generatePdp — success
// --------------------------------------------------------------------------- //
describe("generatePdp", () => {
  it("POSTs the goal (no client Authorization) and returns the PDF blob + ok status + filename", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      pdfResponse({
        "Content-Disposition": "attachment; filename=PDP_AI-Architect.pdf",
        "X-PDP-Status": "ok",
      }),
    );
    const result = await generatePdp(
      { careerGoal: "AI Architect", targetDate: "2027-01-01", additionalContext: "remote only" },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/pdp");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBeUndefined();
    expect(JSON.parse(init.body)).toEqual({
      career_goal: "AI Architect",
      target_date: "2027-01-01",
      additional_context: "remote only",
    });

    expect(result.status).toBe("ok");
    expect(result.filename).toBe("PDP_AI-Architect.pdf");
    expect(result.blob.type).toBe("application/pdf");
  });

  it("omits optional fields from the body when not provided", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(pdfResponse({ "X-PDP-Status": "ok" }));
    await generatePdp(
      { careerGoal: "Data Scientist" },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({
      career_goal: "Data Scientist",
    });
  });

  it("surfaces the role_profile_missing delivery status from the header", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(pdfResponse({ "X-PDP-Status": "role_profile_missing" }));
    const result = await generatePdp(
      { careerGoal: "Novel Role" },
      { fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(result.status).toBe("role_profile_missing");
    expect(result.filename).toBe("PDP.pdf");
  });

  // --------------------------------------------------------------------------- //
  // generatePdp — error branches
  // --------------------------------------------------------------------------- //
  it("throws a PdpApiError with the backend detail on 422 (no profile)", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(errorResponse({ detail: "No profile found. Please upload your CV first." }, 422));
    await expect(
      generatePdp({ careerGoal: "x" }, { fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toMatchObject({ status: 422, message: /upload your cv first/i });
  });

  it.each([
    [401, /session has expired/i],
    [429, /reached your limit/i],
    [502, /couldn't generate your plan right now/i],
  ])("maps status %i to a distinct fallback message", async (status, pattern) => {
    const fetchImpl = jest.fn().mockResolvedValue(errorResponse({}, status));
    await expect(
      generatePdp({ careerGoal: "x" }, { fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toMatchObject({ status, message: pattern });
  });

  it("throws a PdpApiError instance carrying the status on an unexpected error", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(errorResponse("nope", 500));
    await expect(
      generatePdp({ careerGoal: "x" }, { fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toBeInstanceOf(PdpApiError);
  });
});
