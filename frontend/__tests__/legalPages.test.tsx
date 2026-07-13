import { render, screen } from "@testing-library/react";

import PrivacyPage from "@/app/privacy/page";
import TermsPage from "@/app/terms/page";
import { POLICY_VERSION } from "@/lib/policy";

/**
 * SEC-07 — Privacy Notice + Terms of Service pages.
 *
 * These are static server components with no auth dependency (no `fetchSession`, no
 * cookies) — the fact that they render here from a bare `render()` with nothing mocked is
 * itself the "reachable unauthenticated" guarantee. The assertions pin the required GDPR
 * disclosures and product-scope statements so the legal copy can't silently regress.
 */

describe("Privacy Notice page", () => {
  beforeEach(() => render(<PrivacyPage />));

  it("renders without a session (public, no auth wiring)", () => {
    expect(
      screen.getByRole("heading", { level: 1, name: /privacy notice/i }),
    ).toBeInTheDocument();
  });

  it("shows the policy version consistent with the backend constant", () => {
    expect(screen.getByText(new RegExp(`Version ${POLICY_VERSION}`))).toBeInTheDocument();
    expect(screen.getByText(/last updated/i)).toBeInTheDocument();
  });

  it("discloses CV text is sent to a third-party LLM provider with contact details redacted", () => {
    expect(screen.getByText(/large-language-model \(LLM\) provider/i)).toBeInTheDocument();
    expect(
      screen.getByText(/your contact details are redacted/i),
    ).toBeInTheDocument();
  });

  it("states the retention rules (≤30 days SSO, session-only guest)", () => {
    expect(screen.getByText(/30 days after your last activity/i)).toBeInTheDocument();
    expect(screen.getByText(/session-only/i)).toBeInTheDocument();
  });

  it("warns data may be lost on restart", () => {
    expect(screen.getByText(/your data may be lost/i)).toBeInTheDocument();
    expect(screen.getByText(/no backups/i)).toBeInTheDocument();
  });

  it("explains export and erasure endpoints", () => {
    expect(screen.getByText("GET /api/me/export")).toBeInTheDocument();
    expect(screen.getByText("DELETE /api/me")).toBeInTheDocument();
  });

  it("states SSO-only, no passwords", () => {
    expect(screen.getByText(/never/i)).toBeInTheDocument();
    expect(screen.getByText(/single-sign-on only/i)).toBeInTheDocument();
  });
});

describe("Terms of Service page", () => {
  beforeEach(() => render(<TermsPage />));

  it("renders without a session (public, no auth wiring)", () => {
    expect(
      screen.getByRole("heading", { level: 1, name: /terms of service/i }),
    ).toBeInTheDocument();
  });

  it("shows the policy version consistent with the backend constant", () => {
    expect(screen.getByText(new RegExp(`Version ${POLICY_VERSION}`))).toBeInTheDocument();
  });

  it("states the actual product scope and what it is not", () => {
    expect(screen.getByText(/career coaching and personal development/i)).toBeInTheDocument();
    expect(screen.getByText(/job board or job-hunting tool/i)).toBeInTheDocument();
    expect(
      screen.getByText(/medical, legal, financial, or therapeutic advice/i),
    ).toBeInTheDocument();
  });

  it("states no warranty and termination terms", () => {
    expect(screen.getByText(/no warranties/i)).toBeInTheDocument();
    expect(screen.getByText(/suspend or terminate access/i)).toBeInTheDocument();
  });

  it("links to the privacy notice", () => {
    const links = screen.getAllByRole("link", { name: /privacy notice/i });
    expect(links.some((a) => a.getAttribute("href") === "/privacy")).toBe(true);
  });
});
