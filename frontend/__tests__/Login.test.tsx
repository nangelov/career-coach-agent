import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import Login from "@/components/Login";
import { beginSsoLogin, createGuestSession, type Session } from "@/lib/auth";

jest.mock("@/lib/auth", () => ({
  __esModule: true,
  beginSsoLogin: jest.fn(),
  createGuestSession: jest.fn(),
}));

const mockBeginSso = beginSsoLogin as jest.MockedFunction<typeof beginSsoLogin>;
const mockCreateGuest = createGuestSession as jest.MockedFunction<
  typeof createGuestSession
>;

beforeEach(() => {
  jest.clearAllMocks();
});

/** Tick the consent checkbox — the gate all buttons sit behind (§6.22). */
function acceptConsent(): void {
  fireEvent.click(screen.getByRole("checkbox"));
}

describe("Login", () => {
  it("renders Google, LinkedIn and guest options", () => {
    render(<Login onAuthenticated={jest.fn()} />);
    expect(
      screen.getByRole("button", { name: /continue with google/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /continue with linkedin/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /continue as guest/i }),
    ).toBeInTheDocument();
  });

  it("shows the optional banner message", () => {
    render(<Login onAuthenticated={jest.fn()} message="Please sign in again" />);
    expect(screen.getByRole("status")).toHaveTextContent(/please sign in again/i);
  });

  it("renders the consent checkbox with ToS + Privacy links", () => {
    render(<Login onAuthenticated={jest.fn()} />);
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /terms of service/i })).toHaveAttribute(
      "href",
      "/terms",
    );
    expect(screen.getByRole("link", { name: /privacy notice/i })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });

  it("disables every button until consent is given (§6.22)", () => {
    render(<Login onAuthenticated={jest.fn()} />);
    const buttons = [
      screen.getByRole("button", { name: /continue with google/i }),
      screen.getByRole("button", { name: /continue with linkedin/i }),
      screen.getByRole("button", { name: /continue as guest/i }),
    ];
    buttons.forEach((b) => expect(b).toBeDisabled());

    acceptConsent();
    buttons.forEach((b) => expect(b).toBeEnabled());
  });

  it("begins SSO login (with consent) for the chosen provider", () => {
    render(<Login onAuthenticated={jest.fn()} />);
    acceptConsent();
    fireEvent.click(screen.getByRole("button", { name: /continue with google/i }));
    expect(mockBeginSso).toHaveBeenCalledWith("google", { consent: true });
  });

  it("does not begin SSO login before consent is given", () => {
    render(<Login onAuthenticated={jest.fn()} />);
    // The button is disabled; clicking it is a no-op.
    fireEvent.click(screen.getByRole("button", { name: /continue with google/i }));
    expect(mockBeginSso).not.toHaveBeenCalled();
  });

  it("creates a guest session and reports it up on the guest button", async () => {
    const session: Session = {
      sessionId: "sid",
      role: "guest",
      expiresAt: null,
    };
    mockCreateGuest.mockResolvedValue(session);
    const onAuthenticated = jest.fn();

    render(<Login onAuthenticated={onAuthenticated} />);
    acceptConsent();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue as guest/i }));
    });

    expect(mockCreateGuest).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(session));
  });

  it("surfaces an error when guest session creation fails", async () => {
    mockCreateGuest.mockRejectedValue(new Error("boom"));

    render(<Login onAuthenticated={jest.fn()} />);
    acceptConsent();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue as guest/i }));
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not start a guest session/i,
    );
  });
});
