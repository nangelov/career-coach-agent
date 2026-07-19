import {
  deleteAllMemories,
  deleteMemory,
  getMemory,
  MemoryApiError,
  parseMemoryView,
  updatePreferences,
  type Preferences,
} from "@/lib/memory";

/** A minimal ok/json Response stand-in. */
function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** A 204 No Content stand-in (DELETE) — no JSON body. */
function noContent(): Response {
  return {
    ok: true,
    status: 204,
    json: async () => {
      throw new Error("no body");
    },
  } as unknown as Response;
}

describe("parseMemoryView", () => {
  it("maps a full body verbatim (snake_case)", () => {
    const view = parseMemoryView({
      preferences: {
        tone: "encouraging",
        formality: "casual",
        language: "en",
        focus_areas: ["leadership"],
        avoid: ["jargon"],
      },
      memories: [
        {
          id: "mem1",
          text: "Prefers concise answers",
          memory_type: "preference",
          confidence: 0.9,
          created_at: "2026-07-19T00:00:00Z",
        },
      ],
    });

    expect(view.preferences.tone).toBe("encouraging");
    expect(view.preferences.focus_areas).toEqual(["leadership"]);
    expect(view.memories).toHaveLength(1);
    expect(view.memories[0]).toMatchObject({
      id: "mem1",
      memory_type: "preference",
      confidence: 0.9,
    });
  });

  it("degrades a missing/empty body to a renderable empty shape", () => {
    const view = parseMemoryView({});
    expect(view.preferences).toEqual({
      tone: null,
      formality: null,
      language: null,
      focus_areas: [],
      avoid: [],
    });
    expect(view.memories).toEqual([]);
  });
});

describe("getMemory", () => {
  it("GETs /api/memory and parses the view", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({
        preferences: { tone: "formal" },
        memories: [],
      }),
    );

    const view = await getMemory({ fetchImpl });

    expect(fetchImpl.mock.calls[0][0]).toBe("/api/memory");
    expect(view.preferences.tone).toBe("formal");
  });

  it("throws a typed 403 for a guest", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "Memory requires an account." }, false, 403));

    await expect(getMemory({ fetchImpl })).rejects.toMatchObject({
      name: "MemoryApiError",
      status: 403,
    });
  });
});

describe("updatePreferences", () => {
  it("PUTs the preferences document and returns the stored result", async () => {
    const prefs: Preferences = {
      tone: "warm",
      formality: null,
      language: "en",
      focus_areas: ["ai"],
      avoid: [],
    };
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse(prefs));

    const stored = await updatePreferences(prefs, { fetchImpl });

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/memory/preferences");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual(prefs);
    expect(stored.tone).toBe("warm");
  });
});

describe("deleteMemory", () => {
  it("DELETEs the memory by id (204)", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(noContent());

    await deleteMemory("mem 1", { fetchImpl });

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/memory/mem%201");
    expect(init.method).toBe("DELETE");
  });

  it("throws a typed 404 for an unknown/not-owned id", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ detail: "Memory not found." }, false, 404));

    await expect(deleteMemory("gone", { fetchImpl })).rejects.toMatchObject({
      name: "MemoryApiError",
      status: 404,
    });
  });
});

describe("deleteAllMemories", () => {
  it("DELETEs the whole collection and returns the cleared count", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({ deleted: 3 }));

    const count = await deleteAllMemories({ fetchImpl });

    expect(fetchImpl.mock.calls[0][0]).toBe("/api/memory");
    expect(count).toBe(3);
  });

  it("surfaces a typed error on failure", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({}, false, 500));
    await expect(deleteAllMemories({ fetchImpl })).rejects.toThrow(MemoryApiError);
  });
});
