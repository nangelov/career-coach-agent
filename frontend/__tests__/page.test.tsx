import { render, screen } from "@testing-library/react";

import Home from "@/app/page";

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
});
