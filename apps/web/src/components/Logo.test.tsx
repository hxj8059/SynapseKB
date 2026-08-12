import { render, screen } from "@testing-library/react";

import { Logo } from "./Logo";

describe("Logo", () => {
  it("renders both product names", () => {
    render(<Logo />);
    expect(screen.getByText("SynapseKB")).toBeInTheDocument();
    expect(screen.getByText("触智")).toBeInTheDocument();
  });
});
