import { render, screen } from "@testing-library/react";

import Home from "@/app/page";
import { saveSession } from "@/lib/auth";

beforeEach(() => {
  window.localStorage.clear();
  // The chat is auth-gated (P3-06): seed a session so Home renders the chat, not login.
  saveSession({
    accessToken: "test-token",
    tokenType: "bearer",
    sessionId: "guest-session-1",
    role: "guest",
    expiresAt: Date.now() + 3_600_000,
  });
});

describe("Home page", () => {
  it("renders the chat page with the 'Career Coach' heading", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { name: /career coach/i }),
    ).toBeInTheDocument();
  });

  it("shows the empty-state prompt before any messages", () => {
    render(<Home />);

    expect(
      screen.getByText(/ask anything about your career/i),
    ).toBeInTheDocument();
  });

  it("shows the login screen when there is no session", () => {
    window.localStorage.clear();
    render(<Home />);

    expect(
      screen.getByRole("button", { name: /continue as guest/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /continue with google/i }),
    ).toBeInTheDocument();
  });
});
