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

  it("begins SSO login for the chosen provider", () => {
    render(<Login onAuthenticated={jest.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /continue with google/i }));
    expect(mockBeginSso).toHaveBeenCalledWith("google");
  });

  it("creates a guest session and reports it up on the guest button", async () => {
    const session: Session = {
      accessToken: "tok",
      tokenType: "bearer",
      sessionId: "sid",
      role: "guest",
      expiresAt: null,
    };
    mockCreateGuest.mockResolvedValue(session);
    const onAuthenticated = jest.fn();

    render(<Login onAuthenticated={onAuthenticated} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue as guest/i }));
    });

    expect(mockCreateGuest).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(session));
  });

  it("surfaces an error when guest session creation fails", async () => {
    mockCreateGuest.mockRejectedValue(new Error("boom"));

    render(<Login onAuthenticated={jest.fn()} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /continue as guest/i }));
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not start a guest session/i,
    );
  });
});
