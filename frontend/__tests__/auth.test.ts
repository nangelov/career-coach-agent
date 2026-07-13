import {
  beginSsoLogin,
  createGuestSession,
  fetchSession,
  logout,
  sessionFromState,
  upgradeGuestToSso,
} from "@/lib/auth";

/** A minimal ok/json Response stand-in. */
function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => body } as unknown as Response;
}

describe("sessionFromState", () => {
  it("maps a token-free BFF session state", () => {
    const session = sessionFromState({
      sessionId: "sid-1",
      role: "user",
      expiresAt: 1_700_000_000_000,
    });
    expect(session).toEqual({
      sessionId: "sid-1",
      role: "user",
      expiresAt: 1_700_000_000_000,
    });
  });

  it("returns null when the mandatory sessionId is missing", () => {
    expect(sessionFromState({ role: "guest" })).toBeNull();
  });

  it("defaults an unknown role to guest and a missing expiry to null", () => {
    const session = sessionFromState({ sessionId: "sid", role: "something-else" });
    expect(session).toMatchObject({ role: "guest", expiresAt: null });
  });

  it("never surfaces a token even if the payload smuggles one", () => {
    const session = sessionFromState({
      sessionId: "sid",
      role: "guest",
      // @ts-expect-error — a stray token field must be ignored, not carried through.
      accessToken: "should-not-appear",
    }) as unknown as Record<string, unknown>;
    expect(session.accessToken).toBeUndefined();
  });
});

describe("fetchSession", () => {
  it("returns the session when the BFF reports authenticated", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({
        isAuthenticated: true,
        sessionId: "sid-9",
        role: "user",
        expiresAt: 1_700_000_000_000,
      }),
    );
    const session = await fetchSession({
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/auth/session",
      expect.objectContaining({ method: "GET" }),
    );
    expect(session).toMatchObject({ sessionId: "sid-9", role: "user" });
  });

  it("returns null when the BFF reports unauthenticated", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ isAuthenticated: false }));
    expect(
      await fetchSession({ fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).toBeNull();
  });

  it("returns null on a network failure rather than throwing", async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error("offline"));
    expect(
      await fetchSession({ fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).toBeNull();
  });
});

describe("createGuestSession", () => {
  it("POSTs to the guest endpoint and returns the token-free session", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse(
        { sessionId: "gsid", role: "guest", expiresAt: 1_700_000_000_000 },
        true,
        200,
      ),
    );
    const session = await createGuestSession({
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/auth/guest",
      expect.objectContaining({ method: "POST" }),
    );
    // Consent gate (§6.22): the request carries the consent flag the backend now requires.
    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ consent: true });
    expect(session.sessionId).toBe("gsid");
    // The client model carries no token.
    expect((session as unknown as Record<string, unknown>).accessToken).toBeUndefined();
  });

  it("throws on a non-2xx response", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({}, false, 500));
    await expect(
      createGuestSession({ fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toThrow();
  });
});

describe("beginSsoLogin", () => {
  it("navigates to the BFF login endpoint", () => {
    const navigate = jest.fn();
    beginSsoLogin("google", { navigate });
    expect(navigate).toHaveBeenCalledWith("/api/auth/login/google");
  });

  it("appends the upgrade ticket when provided", () => {
    const navigate = jest.fn();
    beginSsoLogin("linkedin", { navigate, upgradeTicket: "tkt 1" });
    expect(navigate).toHaveBeenCalledWith(
      "/api/auth/login/linkedin?upgrade_ticket=tkt%201",
    );
  });

  it("appends the consent flag when accepted (§6.22)", () => {
    const navigate = jest.fn();
    beginSsoLogin("google", { navigate, consent: true });
    expect(navigate).toHaveBeenCalledWith("/api/auth/login/google?consent=1");
  });

  it("orders upgrade_ticket then consent when both are present", () => {
    const navigate = jest.fn();
    beginSsoLogin("google", { navigate, upgradeTicket: "UPG", consent: true });
    expect(navigate).toHaveBeenCalledWith(
      "/api/auth/login/google?upgrade_ticket=UPG&consent=1",
    );
  });
});

describe("upgradeGuestToSso", () => {
  it("mints an upgrade ticket (no client token) then navigates to login with it", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse({ upgrade_ticket: "UPG", expires_in: 120 }, true, 201),
    );
    const navigate = jest.fn();
    await upgradeGuestToSso("google", {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      navigate,
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/auth/upgrade");
    expect(init.method).toBe("POST");
    // No Authorization header is built client-side — the BFF injects it from the cookie.
    expect(init.headers?.Authorization).toBeUndefined();
    // The upgrading guest already consented at guest-session start, so consent is threaded.
    expect(navigate).toHaveBeenCalledWith(
      "/api/auth/login/google?upgrade_ticket=UPG&consent=1",
    );
  });
});

describe("logout", () => {
  it("POSTs to the logout endpoint (no client token)", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse(null, true, 204));
    await logout({ fetchImpl: fetchImpl as unknown as typeof fetch });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/auth/logout");
    expect(init.method).toBe("POST");
    expect(init.headers).toBeUndefined();
  });

  it("swallows a network failure (best-effort revocation)", async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error("offline"));
    await expect(
      logout({ fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).resolves.toBeUndefined();
  });
});
