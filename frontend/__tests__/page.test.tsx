import { render, screen } from "@testing-library/react";

import Home from "@/app/page";

describe("Home page", () => {
  it("renders the 'Career Coach v2' heading", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { name: /career coach v2/i }),
    ).toBeInTheDocument();
  });
});
