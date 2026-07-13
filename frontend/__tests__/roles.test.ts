import {
  getRoleGap,
  getRoleRequirements,
  parseRoleRequirements,
  parseSkillsGap,
  RolesApiError,
} from "@/lib/roles";

/** A minimal ok/json Response stand-in. */
function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

// --------------------------------------------------------------------------- //
// parseRoleRequirements / parseSkillsGap — defensive wire mapping
// --------------------------------------------------------------------------- //
describe("parseRoleRequirements", () => {
  it("maps a full requirements body verbatim (snake_case)", () => {
    const parsed = parseRoleRequirements({
      role: "AI Solution Architect",
      requirements: [
        {
          skill: "Python",
          frequency: 0.78,
          weight: 0.9,
          evidence: ["https://jobs.example/1", "taxonomy"],
        },
      ],
      evidence_count: 12,
      refreshed_at: "2026-07-01T00:00:00Z",
    });
    expect(parsed.role).toBe("AI Solution Architect");
    expect(parsed.requirements[0]).toEqual({
      skill: "Python",
      frequency: 0.78,
      weight: 0.9,
      evidence: ["https://jobs.example/1", "taxonomy"],
    });
    expect(parsed.evidence_count).toBe(12);
    expect(parsed.refreshed_at).toBe("2026-07-01T00:00:00Z");
  });

  it("degrades missing / malformed fields defensively", () => {
    const parsed = parseRoleRequirements({ requirements: [{ skill: "SQL" }] });
    expect(parsed.role).toBe("");
    expect(parsed.evidence_count).toBe(0);
    expect(parsed.refreshed_at).toBeNull();
    expect(parsed.requirements[0]).toEqual({
      skill: "SQL",
      frequency: 0,
      weight: 0,
      evidence: [],
    });
  });
});

describe("parseSkillsGap", () => {
  it("maps an ok gap and defaults an unknown status to ok", () => {
    const parsed = parseSkillsGap({
      role: "AI Solution Architect",
      status: "ok",
      matched: ["Python"],
      gap: [{ skill: "Kubernetes", frequency: 0.5, weight: 0.5, evidence: [] }],
    });
    expect(parsed.status).toBe("ok");
    expect(parsed.matched).toEqual(["Python"]);
    expect(parsed.gap?.[0].skill).toBe("Kubernetes");

    expect(parseSkillsGap({ status: "WHO_KNOWS" }).status).toBe("ok");
  });

  it("keeps gap null when absent (missing-state contract)", () => {
    const parsed = parseSkillsGap({ status: "profile_missing", matched: [] });
    expect(parsed.status).toBe("profile_missing");
    expect(parsed.gap).toBeNull();
  });
});

// --------------------------------------------------------------------------- //
// getRoleRequirements
// --------------------------------------------------------------------------- //
describe("getRoleRequirements", () => {
  it("GETs the requirements endpoint (no client Authorization) and returns the ranked list", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({
        role: "AI Solution Architect",
        requirements: [{ skill: "Python", frequency: 0.8, weight: 0.9, evidence: [] }],
        evidence_count: 3,
        refreshed_at: null,
      }),
    );
    const outcome = await getRoleRequirements("AI Solution Architect", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/roles/AI%20Solution%20Architect/requirements");
    expect(init.method).toBe("GET");
    expect(init.headers.Authorization).toBeUndefined();
    expect(outcome).toMatchObject({ kind: "requirements" });
    if (outcome.kind === "requirements") {
      expect(outcome.requirements.requirements[0].skill).toBe("Python");
    }
  });

  it("returns a mining handle on a 202 cold role", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ task_id: "mine-1", status: "accepted" }, true, 202));
    const outcome = await getRoleRequirements("Novel Role", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(outcome).toEqual({ kind: "mining", taskId: "mine-1" });
  });

  it("throws a RolesApiError carrying the status on 429", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "Too many requests." }, false, 429));
    await expect(
      getRoleRequirements("x", { fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toMatchObject({ status: 429, message: /too many requests/i });
  });

  it("throws when a 202 handle is malformed", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({}, true, 202));
    await expect(
      getRoleRequirements("x", { fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toBeInstanceOf(RolesApiError);
  });
});

// --------------------------------------------------------------------------- //
// getRoleGap
// --------------------------------------------------------------------------- //
describe("getRoleGap", () => {
  it("GETs the gap endpoint and returns the parsed gap", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({
        role: "AI Solution Architect",
        status: "ok",
        matched: ["Python"],
        gap: [{ skill: "Kubernetes", frequency: 0.5, weight: 0.5, evidence: [] }],
      }),
    );
    const outcome = await getRoleGap("AI Solution Architect", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/roles/AI%20Solution%20Architect/gap");
    expect(outcome).toMatchObject({ kind: "gap" });
    if (outcome.kind === "gap") {
      expect(outcome.gap.matched).toEqual(["Python"]);
    }
  });

  it("returns a mining handle on a 202 cold role", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ task_id: "mine-2" }, true, 202));
    const outcome = await getRoleGap("Novel Role", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(outcome).toEqual({ kind: "mining", taskId: "mine-2" });
  });

  it("surfaces a guest 403 as a RolesApiError with a sign-in message", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse(
        { detail: "Guests cannot compute a skills gap. Sign in and upload a CV first." },
        false,
        403,
      ),
    );
    await expect(
      getRoleGap("x", { fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toMatchObject({ status: 403, message: /sign in and upload a cv/i });
  });
});
