import { type Session } from "@/lib/auth";
import {
  getProfile,
  isProfileEmpty,
  parseProfile,
  pollJobStatus,
  pollJobUntilTerminal,
  ProfileApiError,
  updateProfile,
  uploadCv,
  type Profile,
} from "@/lib/profile";

function guestSession(overrides: Partial<Session> = {}): Session {
  return {
    accessToken: "tok",
    tokenType: "bearer",
    sessionId: "sid-1",
    role: "guest",
    expiresAt: Date.now() + 3_600_000,
    ...overrides,
  };
}

function userSession(): Session {
  return guestSession({ role: "user", accessToken: "utok" });
}

/** A minimal ok/json Response stand-in. */
function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

// --------------------------------------------------------------------------- //
// parseProfile / isProfileEmpty — defensive wire mapping
// --------------------------------------------------------------------------- //
describe("parseProfile", () => {
  it("maps a full profile body verbatim", () => {
    const parsed = parseProfile({
      skills: ["ts", "react"],
      experience: [
        {
          title: "Engineer",
          company: "Acme",
          start_date: "2020",
          end_date: "Present",
          description: "Built things",
        },
      ],
      education: [
        {
          institution: "Uni",
          degree: "BSc",
          field: "CS",
          start_date: "2015",
          end_date: "2019",
        },
      ],
      goals: ["Become a staff engineer"],
    });
    expect(parsed.skills).toEqual(["ts", "react"]);
    expect(parsed.experience[0]).toMatchObject({ title: "Engineer", company: "Acme" });
    expect(parsed.education[0]).toMatchObject({ institution: "Uni", degree: "BSc" });
    expect(parsed.goals).toEqual(["Become a staff engineer"]);
  });

  it("degrades missing / malformed sections to empty and null-fills partial entries", () => {
    const parsed = parseProfile({ experience: [{ title: "Solo" }] });
    expect(parsed.skills).toEqual([]);
    expect(parsed.education).toEqual([]);
    expect(parsed.goals).toEqual([]);
    expect(parsed.experience[0]).toEqual({
      title: "Solo",
      company: null,
      start_date: null,
      end_date: null,
      description: null,
    });
  });

  it("treats an empty profile as empty", () => {
    const empty: Profile = { skills: [], experience: [], education: [], goals: [] };
    expect(isProfileEmpty(empty)).toBe(true);
    expect(isProfileEmpty({ ...empty, skills: ["x"] })).toBe(false);
  });
});

// --------------------------------------------------------------------------- //
// uploadCv
// --------------------------------------------------------------------------- //
describe("uploadCv", () => {
  function cvFile(): File {
    return new File(["cv bytes"], "cv.pdf", { type: "application/pdf" });
  }

  it("POSTs multipart form data with the bearer token and returns the task id", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ task_id: "task-9", status: "accepted" }, true, 202));
    const handle = await uploadCv(cvFile(), guestSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(handle).toEqual({ taskId: "task-9" });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/profile/cv");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer tok");
    expect(init.body).toBeInstanceOf(FormData);
    // The browser must set the multipart Content-Type/boundary — we must not.
    expect(init.headers["Content-Type"]).toBeUndefined();
  });

  it("throws a ProfileApiError carrying the status and backend detail on 413", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({ detail: "The uploaded file exceeds the maximum size." }, false, 413),
    );
    await expect(
      uploadCv(cvFile(), guestSession(), {
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ status: 413, message: /exceeds the maximum size/i });
  });

  it("uses a friendly fallback when the error body has no detail (415)", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({}, false, 415));
    await expect(
      uploadCv(cvFile(), guestSession(), {
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ status: 415, message: /isn't supported/i });
  });

  it("surfaces the guest over-limit 429 detail", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse(
        { detail: "Guest limit reached: one upload per session. Sign in to upload more." },
        false,
        429,
      ),
    );
    await expect(
      uploadCv(cvFile(), guestSession(), {
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ status: 429, message: /sign in to upload more/i });
  });
});

// --------------------------------------------------------------------------- //
// pollJobStatus / pollJobUntilTerminal
// --------------------------------------------------------------------------- //
describe("pollJobStatus", () => {
  it("GETs the job status endpoint and maps the body", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({
        task_id: "t1",
        status: "in_progress",
        state: "PARSING",
        stage: "parsing",
        message: "Reading your CV…",
      }),
    );
    const status = await pollJobStatus("t 1", guestSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/jobs/status/t%201",
      expect.objectContaining({ method: "GET" }),
    );
    expect(status).toMatchObject({
      status: "in_progress",
      stage: "parsing",
      message: "Reading your CV…",
    });
  });

  it("defaults an unknown status to pending", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ task_id: "t1", status: "WHO_KNOWS" }));
    const status = await pollJobStatus("t1", guestSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(status.status).toBe("pending");
  });
});

describe("pollJobUntilTerminal", () => {
  it("polls until success, invoking onUpdate for each poll", async () => {
    const bodies = [
      { task_id: "t1", status: "pending" },
      { task_id: "t1", status: "in_progress", stage: "parsing" },
      { task_id: "t1", status: "success", result: { persisted: true } },
    ];
    let call = 0;
    const fetchImpl = jest.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse(bodies[Math.min(call++, bodies.length - 1)])),
    );
    const updates: string[] = [];
    const terminal = await pollJobUntilTerminal("t1", guestSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      intervalMs: 0,
      onUpdate: (s) => updates.push(s.status),
    });
    expect(updates).toEqual(["pending", "in_progress", "success"]);
    expect(terminal.status).toBe("success");
    expect(terminal.result).toEqual({ persisted: true });
  });

  it("resolves on a failure terminal state carrying the client-safe error", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({ task_id: "t1", status: "failure", error: "We couldn't read that file." }),
    );
    const terminal = await pollJobUntilTerminal("t1", guestSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      intervalMs: 0,
    });
    expect(terminal.status).toBe("failure");
    expect(terminal.error).toBe("We couldn't read that file.");
  });

  it("stops and rejects with an AbortError when the signal is aborted", async () => {
    const controller = new AbortController();
    const fetchImpl = jest.fn().mockImplementation(() => {
      // Abort after the first poll so the loop aborts during the interval wait.
      controller.abort();
      return Promise.resolve(jsonResponse({ task_id: "t1", status: "in_progress" }));
    });
    await expect(
      pollJobUntilTerminal("t1", guestSession(), {
        fetchImpl: fetchImpl as unknown as typeof fetch,
        intervalMs: 50,
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({ name: "AbortError" });
    // Only the first poll ran; the loop never fetched again after abort.
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});

// --------------------------------------------------------------------------- //
// getProfile / updateProfile
// --------------------------------------------------------------------------- //
describe("getProfile", () => {
  it("GETs the profile with the bearer token and maps the body", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ skills: ["python"], goals: [] }));
    const profile = await getProfile(userSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/profile",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({ Authorization: "Bearer utok" }),
      }),
    );
    expect(profile.skills).toEqual(["python"]);
  });

  it("throws a ProfileApiError on 401", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({}, false, 401));
    await expect(
      getProfile(userSession(), { fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toBeInstanceOf(ProfileApiError);
  });
});

describe("updateProfile", () => {
  const profile: Profile = {
    skills: ["ts"],
    experience: [],
    education: [],
    goals: ["grow"],
  };

  it("PUTs the JSON profile with the bearer token and returns the stored result", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse(profile));
    const stored = await updateProfile(profile, userSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/profile");
    expect(init.method).toBe("PUT");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.headers.Authorization).toBe("Bearer utok");
    expect(JSON.parse(init.body)).toEqual(profile);
    expect(stored.skills).toEqual(["ts"]);
  });

  it("surfaces a guest 403 as a ProfileApiError with the backend sign-in message", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse(
        { detail: "Guests cannot save a profile. Sign in to store and edit your profile." },
        false,
        403,
      ),
    );
    await expect(
      updateProfile(profile, guestSession(), {
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ status: 403, message: /sign in to store and edit/i });
  });
});
