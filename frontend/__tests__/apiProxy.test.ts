import {
  DEFAULT_INTERNAL_API_URL,
  buildApiRewrites,
  resolveInternalApiBaseUrl,
} from "@/lib/apiProxy";

describe("resolveInternalApiBaseUrl", () => {
  it("defaults to localhost:8000 when INTERNAL_API_URL is unset", () => {
    expect(resolveInternalApiBaseUrl({})).toBe(DEFAULT_INTERNAL_API_URL);
  });

  it("defaults when INTERNAL_API_URL is blank/whitespace", () => {
    expect(resolveInternalApiBaseUrl({ INTERNAL_API_URL: "   " })).toBe(
      DEFAULT_INTERNAL_API_URL,
    );
  });

  it("uses INTERNAL_API_URL when set (docker-compose service DNS)", () => {
    expect(
      resolveInternalApiBaseUrl({ INTERNAL_API_URL: "http://backend:8000" }),
    ).toBe("http://backend:8000");
  });

  it("trims whitespace and any trailing slash", () => {
    expect(
      resolveInternalApiBaseUrl({ INTERNAL_API_URL: " http://backend:8000/ " }),
    ).toBe("http://backend:8000");
  });
});

describe("buildApiRewrites", () => {
  it("always emits an /api/:path* proxy rule (regression guard: not dev-only)", () => {
    // The FIX-05 bug was that the rewrite was disabled outside `next dev`, so a
    // production `next start` (docker-compose) 404'd every /api/* call. This
    // asserts the proxy is unconditional and points at the resolved backend.
    const rules = buildApiRewrites({ INTERNAL_API_URL: "http://backend:8000" });
    expect(rules).toEqual([
      { source: "/api/:path*", destination: "http://backend:8000/api/:path*" },
    ]);
  });

  it("falls back to the localhost default with no env (bare next dev/start)", () => {
    const rules = buildApiRewrites({});
    expect(rules[0].destination).toBe(`${DEFAULT_INTERNAL_API_URL}/api/:path*`);
  });
});
