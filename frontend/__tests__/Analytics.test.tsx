import { render, screen, waitFor } from "@testing-library/react";

import Analytics from "@/components/Analytics";
import { fetchSession, type Session } from "@/lib/auth";
import { isAnalyticsEnabled } from "@/lib/analytics";

// next/script → a plain <script> marker so we can assert what (if anything) got injected.
jest.mock("next/script", () => ({
  __esModule: true,
  default: ({
    id,
    src,
    children,
  }: {
    id?: string;
    src?: string;
    children?: React.ReactNode;
  }) => (
    <script data-testid={`script-${id}`} data-src={src ?? ""}>
      {children}
    </script>
  ),
}));

jest.mock("next/navigation", () => ({
  __esModule: true,
  usePathname: () => "/dashboard",
}));

jest.mock("@/lib/auth", () => ({
  __esModule: true,
  fetchSession: jest.fn(),
}));

// Keep the real sanitize/track logic out of scope; drive the gate via isAnalyticsEnabled.
jest.mock("@/lib/analytics", () => ({
  __esModule: true,
  GA_MEASUREMENT_ID: "G-TEST123",
  isAnalyticsEnabled: jest.fn(() => true),
  trackPageview: jest.fn(),
}));

const mockFetchSession = fetchSession as jest.MockedFunction<typeof fetchSession>;
const mockEnabled = isAnalyticsEnabled as jest.MockedFunction<typeof isAnalyticsEnabled>;

function session(): Session {
  return { sessionId: "sid", role: "guest", expiresAt: Date.now() + 3_600_000 };
}

afterEach(() => {
  jest.clearAllMocks();
});

describe("Analytics (GA4 loader gate)", () => {
  it("injects no script and never checks the session when disabled (no Measurement ID)", async () => {
    mockEnabled.mockReturnValue(false);
    render(<Analytics />);
    expect(screen.queryByTestId("script-ga4-src")).not.toBeInTheDocument();
    expect(mockFetchSession).not.toHaveBeenCalled();
  });

  it("injects no script before a session exists (pre-login / consent screen)", async () => {
    mockEnabled.mockReturnValue(true);
    mockFetchSession.mockResolvedValue(null);
    render(<Analytics />);
    await waitFor(() => expect(mockFetchSession).toHaveBeenCalled());
    expect(screen.queryByTestId("script-ga4-src")).not.toBeInTheDocument();
  });

  it("injects the gtag.js script once a session is present", async () => {
    mockEnabled.mockReturnValue(true);
    mockFetchSession.mockResolvedValue(session());
    render(<Analytics />);
    const script = await screen.findByTestId("script-ga4-src");
    expect(script).toHaveAttribute(
      "data-src",
      "https://www.googletagmanager.com/gtag/js?id=G-TEST123",
    );
    // The inline init/config script is also present.
    expect(screen.getByTestId("script-ga4-init")).toBeInTheDocument();
  });
});
