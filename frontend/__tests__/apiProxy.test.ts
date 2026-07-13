import {
  DEFAULT_INTERNAL_API_URL,
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
