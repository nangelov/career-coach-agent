import {
  authHeaders,
  beginSsoLogin,
  clearSession,
  createGuestSession,
  loadSession,
  logout,
  saveSession,
  sessionFromFragment,
  sessionFromPayload,
  upgradeGuestToSso,
  type Session,
} from "@/lib/auth";

beforeEach(() => {
  window.localStorage.clear();
});

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

describe("sessionFromPayload", () => {
  it("maps a well-formed backend token payload", () => {
    const before = Date.now();
    const session = sessionFromPayload({
      access_token: "tok",
      token_type: "bearer",
      session_id: "sid-1",
      role: "user",
      expires_in: 3600,
    });
    expect(session).not.toBeNull();
    expect(session?.accessToken).toBe("tok");
    expect(session?.sessionId).toBe("sid-1");
    expect(session?.role).toBe("user");
    expect(session?.expiresAt).toBeGreaterThanOrEqual(before + 3600 * 1000);
  });

  it("returns null when the mandatory token / session id are missing", () => {
    expect(sessionFromPayload({ session_id: "sid" })).toBeNull();
    expect(sessionFromPayload({ access_token: "tok" })).toBeNull();
  });

  it("defaults an unknown role to guest", () => {
    const session = sessionFromPayload({
      access_token: "tok",
      session_id: "sid",
      role: "something-else",
    });
    expect(session?.role).toBe("guest");
  });
});

describe("sessionFromFragment", () => {
  it("parses the SSO callback fragment (with leading #)", () => {
    const session = sessionFromFragment(
      "#access_token=abc&token_type=bearer&session_id=sid-9&role=user&expires_in=1800",
    );
    expect(session).toMatchObject({
      accessToken: "abc",
      sessionId: "sid-9",
      role: "user",
    });
  });

  it("returns null for an empty / tokenless fragment", () => {
    expect(sessionFromFragment("")).toBeNull();
    expect(sessionFromFragment("#")).toBeNull();
    expect(sessionFromFragment("#state=xyz")).toBeNull();
  });
});

describe("persistence", () => {
  it("round-trips save → load", () => {
    const session = guestSession();
    saveSession(session);
    expect(loadSession()).toEqual(session);
  });

  it("clears and returns null after clearSession", () => {
    saveSession(guestSession());
    clearSession();
    expect(loadSession()).toBeNull();
  });

  it("drops an expired session on load", () => {
    saveSession(guestSession({ expiresAt: Date.now() - 1000 }));
    expect(loadSession()).toBeNull();
    // Proactively cleared, so the raw key is gone too.
    expect(window.localStorage.getItem("cc.session")).toBeNull();
  });

  it("returns null for a malformed stored value", () => {
    window.localStorage.setItem("cc.session", "{not json");
    expect(loadSession()).toBeNull();
  });
});

describe("authHeaders", () => {
  it("builds the bearer header from a session", () => {
    expect(authHeaders(guestSession())).toEqual({ Authorization: "Bearer tok" });
  });

  it("is empty when unauthenticated", () => {
    expect(authHeaders(null)).toEqual({});
  });
});

describe("createGuestSession", () => {
  it("POSTs to the guest endpoint and persists the session", async () => {
    const fetchImpl = jest.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({
        access_token: "gtok",
        token_type: "bearer",
        session_id: "gsid",
        role: "guest",
        expires_in: 3600,
      }),
    });
    const session = await createGuestSession({
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/auth/guest",
      expect.objectContaining({ method: "POST" }),
    );
    expect(session.sessionId).toBe("gsid");
    expect(loadSession()?.accessToken).toBe("gtok");
  });

  it("throws on a non-2xx response", async () => {
    const fetchImpl = jest.fn().mockResolvedValue({ ok: false, status: 500 });
    await expect(
      createGuestSession({ fetchImpl: fetchImpl as unknown as typeof fetch }),
    ).rejects.toThrow();
  });
});

describe("beginSsoLogin", () => {
  it("navigates to the backend login endpoint", () => {
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
});

describe("upgradeGuestToSso", () => {
  it("mints an upgrade ticket then navigates to login with it", async () => {
    const fetchImpl = jest.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ upgrade_ticket: "UPG", expires_in: 120 }),
    });
    const navigate = jest.fn();
    await upgradeGuestToSso("google", guestSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      navigate,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/auth/upgrade",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer tok" }),
      }),
    );
    expect(navigate).toHaveBeenCalledWith("/api/auth/login/google?upgrade_ticket=UPG");
  });
});

describe("logout", () => {
  it("POSTs to the logout endpoint and clears the stored session", async () => {
    saveSession(guestSession());
    const fetchImpl = jest.fn().mockResolvedValue({ ok: true, status: 204 });
    await logout(guestSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/auth/logout",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer tok" }),
      }),
    );
    expect(loadSession()).toBeNull();
  });

  it("clears the session even if the network call fails", async () => {
    saveSession(guestSession());
    const fetchImpl = jest.fn().mockRejectedValue(new Error("offline"));
    await logout(guestSession(), {
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(loadSession()).toBeNull();
  });
});
