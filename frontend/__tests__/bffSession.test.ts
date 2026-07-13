import {
  SESSION_COOKIE,
  clientSessionState,
  decodeSessionToken,
  sessionCookieMaxAge,
} from "@/lib/bffSession";

/** Build a JWT-shaped token (header.payload.sig) with a base64url payload — signature unused. */
function makeToken(payload: Record<string, unknown>): string {
  const seg = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj)).toString("base64url");
  return `${seg({ alg: "HS256" })}.${seg(payload)}.sig`;
}

const NOW = 1_700_000_000_000; // fixed "now" in ms
const nowSec = Math.floor(NOW / 1000);

describe("SESSION_COOKIE", () => {
  it("is the single cookie name for the session token", () => {
    expect(SESSION_COOKIE).toBe("cc_session");
  });
});

describe("decodeSessionToken", () => {
  it("decodes valid claims (unverified)", () => {
    const token = makeToken({
      sub: "u1",
      role: "user",
      sid: "sid-1",
      iat: nowSec,
      exp: nowSec + 3600,
    });
    expect(decodeSessionToken(token)).toEqual({
      sub: "u1",
      role: "user",
      sid: "sid-1",
      iat: nowSec,
      exp: nowSec + 3600,
    });
  });

  it("returns null for a non-3-part token", () => {
    expect(decodeSessionToken("not.a")).toBeNull();
    expect(decodeSessionToken("")).toBeNull();
  });

  it("returns null for an unparseable payload", () => {
    expect(decodeSessionToken("h.###.s")).toBeNull();
  });

  it("rejects missing sid, unknown role, or missing exp", () => {
    expect(
      decodeSessionToken(makeToken({ role: "user", exp: nowSec + 10 })),
    ).toBeNull();
    expect(
      decodeSessionToken(makeToken({ sid: "s", role: "admin", exp: nowSec + 10 })),
    ).toBeNull();
    expect(decodeSessionToken(makeToken({ sid: "s", role: "user" }))).toBeNull();
  });
});

describe("clientSessionState", () => {
  it("is unauthenticated with no token", () => {
    expect(clientSessionState(undefined, NOW)).toEqual({ isAuthenticated: false });
  });

  it("is unauthenticated for an expired token", () => {
    const token = makeToken({ sub: "s", role: "guest", sid: "s", exp: nowSec - 1 });
    expect(clientSessionState(token, NOW)).toEqual({ isAuthenticated: false });
  });

  it("projects the token-free state for a valid token (never a token)", () => {
    const token = makeToken({
      sub: "s",
      role: "guest",
      sid: "sid-9",
      iat: nowSec,
      exp: nowSec + 3600,
    });
    const state = clientSessionState(token, NOW);
    expect(state).toEqual({
      isAuthenticated: true,
      sessionId: "sid-9",
      role: "guest",
      expiresAt: (nowSec + 3600) * 1000,
    });
    expect(JSON.stringify(state)).not.toContain(token);
  });
});

describe("sessionCookieMaxAge", () => {
  it("is the token's remaining lifetime in seconds", () => {
    const token = makeToken({ sub: "s", role: "guest", sid: "s", exp: nowSec + 1200 });
    expect(sessionCookieMaxAge(token, NOW)).toBe(1200);
  });

  it("is undefined for an unreadable token", () => {
    expect(sessionCookieMaxAge("bad", NOW)).toBeUndefined();
  });
});
