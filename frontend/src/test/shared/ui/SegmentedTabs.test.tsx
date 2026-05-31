import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SegmentedTabs } from "../../../shared/ui";

describe("SegmentedTabs", () => {
  const items = [
    { id: "a", label: "标签A" },
    { id: "b", label: "标签B" },
    { id: "c", label: "标签C" },
  ];

  it("renders all tabs", () => {
    render(<SegmentedTabs items={items} onChange={() => {}} value="a" />);
    expect(screen.getByRole("tab", { name: "标签A" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "标签B" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "标签C" })).toBeInTheDocument();
  });

  it("marks the active tab as selected", () => {
    render(<SegmentedTabs items={items} onChange={() => {}} value="b" />);
    expect(screen.getByRole("tab", { name: "标签B", selected: true })).toBeInTheDocument();
  });

  it("fires onChange when a tab is clicked", () => {
    const onChange = vi.fn();
    render(<SegmentedTabs items={items} onChange={onChange} value="a" />);
    fireEvent.click(screen.getByRole("tab", { name: "标签C" }));
    expect(onChange).toHaveBeenCalledWith("c");
  });

  it("sets aria-label when provided", () => {
    render(<SegmentedTabs ariaLabel="子页面" items={items} onChange={() => {}} value="a" />);
    expect(screen.getByRole("tablist")).toHaveAttribute("aria-label", "子页面");
  });
});
