import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("identifies Sky Bridge Jet and its product positioning", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { name: "Sky Bridge Jet" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Premium Private Aviation Marketplace"),
    ).toBeInTheDocument();
  });
});
