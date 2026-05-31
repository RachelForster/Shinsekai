import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IconButton } from "../../../shared/ui";

describe("IconButton", () => {
  it("renders with an accessible label", () => {
    render(<IconButton label="关闭">✕</IconButton>);
    expect(screen.getByRole("button", { name: "关闭" })).toBeInTheDocument();
  });

  it("renders children", () => {
    render(<IconButton label="搜索">🔍</IconButton>);
    expect(screen.getByText("🔍")).toBeInTheDocument();
  });

  it("fires onClick", () => {
    let fired = false;
    render(
      <IconButton label="点击" onClick={() => (fired = true)}>
        ✓
      </IconButton>,
    );
    screen.getByRole("button").click();
    expect(fired).toBe(true);
  });

  it("uses title attribute for native tooltip", () => {
    render(<IconButton label="删除">🗑</IconButton>);
    expect(screen.getByRole("button")).toHaveAttribute("title", "删除");
  });
});
