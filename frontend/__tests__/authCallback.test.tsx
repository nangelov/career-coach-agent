import { render, screen, waitFor } from "@testing-library/react";

import AuthCallbackPage from "@/app/auth/callback/page";
import { loadSession } from "@/lib/auth";

const mockReplace = jest.fn();
jest.mock("next/navigation", () => ({
  __esModule: true,
  useRouter: () => ({ replace: mockReplace }),
}));

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  window.location.hash = "";
});

describe("AuthCallbackPage", () => {
  it("persists the fragment session and routes to the chat", async () => {
    window.location.hash =
      "#access_token=abc&token_type=bearer&session_id=sid-9&role=user&expires_in=1800";

    render(<AuthCallbackPage />);

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/"));
    const stored = loadSession();
    expect(stored?.accessToken).toBe("abc");
    expect(stored?.role).toBe("user");
  });

  it("shows a failure state (no redirect) when the fragment has no token", async () => {
    window.location.hash = "#state=only";

    render(<AuthCallbackPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/sign-in failed/i);
    expect(mockReplace).not.toHaveBeenCalled();
    expect(loadSession()).toBeNull();
  });
});
