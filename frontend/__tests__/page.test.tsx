import { render, screen } from "@testing-library/react";

import Home from "@/app/page";
import { fetchSession } from "@/lib/auth";

// The chat hydrates the session from the httpOnly cookie via the BFF (SEC-04). Mock that
// hydration; keep the real login flow for the signed-out screen.
jest.mock("@/lib/auth", () => {
  const actual = jest.requireActual("@/lib/auth");
  return {
    __esModule: true,
    ...actual,
    fetchSession: jest.fn(),
    logout: jest.fn().mockResolvedValue(undefined),
  };
});

const mockFetchSession = fetchSession as jest.MockedFunction<typeof fetchSession>;

beforeEach(() => {
  jest.clearAllMocks();
  // Auth-gated (P3-06): resolve a guest session so Home renders the chat, not login.
  mockFetchSession.mockResolvedValue({
    sessionId: "guest-session-1",
    role: "guest",
    expiresAt: Date.now() + 3_600_000,
  });
});

describe("Home page", () => {
  it("renders the chat page with the 'Career Coach' heading", async () => {
    render(<Home />);

    expect(
      await screen.findByRole("heading", { name: /career coach/i }),
    ).toBeInTheDocument();
  });

  it("shows the empty-state prompt before any messages", async () => {
    render(<Home />);

    expect(
      await screen.findByText(/ask anything about your career/i),
    ).toBeInTheDocument();
  });

  it("shows the login screen when there is no session", async () => {
    mockFetchSession.mockResolvedValue(null);
    render(<Home />);

    expect(
      await screen.findByRole("button", { name: /continue as guest/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /continue with google/i }),
    ).toBeInTheDocument();
  });
});
