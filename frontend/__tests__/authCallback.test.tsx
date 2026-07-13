import { render, screen, waitFor } from "@testing-library/react";

import AuthCallbackPage from "@/app/auth/callback/page";
import { fetchSession } from "@/lib/auth";

jest.mock("@/lib/auth", () => ({
  __esModule: true,
  fetchSession: jest.fn(),
}));

const mockFetchSession = fetchSession as jest.MockedFunction<typeof fetchSession>;

const mockReplace = jest.fn();
jest.mock("next/navigation", () => ({
  __esModule: true,
  useRouter: () => ({ replace: mockReplace }),
}));

beforeEach(() => {
  jest.clearAllMocks();
});

describe("AuthCallbackPage", () => {
  it("hydrates the cookie session and routes to the chat", async () => {
    mockFetchSession.mockResolvedValue({
      sessionId: "sid-9",
      role: "user",
      expiresAt: Date.now() + 3_600_000,
    });

    render(<AuthCallbackPage />);

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/"));
  });

  it("shows a failure state (no redirect) when there is no session", async () => {
    mockFetchSession.mockResolvedValue(null);

    render(<AuthCallbackPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/sign-in failed/i);
    expect(mockReplace).not.toHaveBeenCalled();
  });
});
