import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IconButton } from "../../../shared/ui";

describe("IconButton", () => {
  it("renders with an accessible label", () => {
    render(<IconButton label="Close">x</IconButton>);
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("renders children", () => {
    render(<IconButton label="Search">S</IconButton>);
    expect(screen.getByText("S")).toBeInTheDocument();
  });

  it("fires onClick", () => {
    let fired = false;
    render(
      <IconButton label="Click" onClick={() => (fired = true)}>
        C
      </IconButton>,
    );
    screen.getByRole("button").click();
    expect(fired).toBe(true);
  });

  it("uses title attribute for native tooltip", () => {
    render(<IconButton label="Delete">D</IconButton>);
    expect(screen.getByRole("button")).toHaveAttribute("title", "Delete");
  });
});
