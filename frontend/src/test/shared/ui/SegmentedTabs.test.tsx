import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useState } from "react";

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

  it("moves focus and selection together with keyboard wraparound and panel links", () => {
    function Tabs() {
      const [value, setValue] = useState("a");
      return <SegmentedTabs idPrefix="example" items={items} onChange={setValue} value={value} />;
    }
    render(<Tabs />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "标签A" }), { key: "ArrowLeft" });
    const last = screen.getByRole("tab", { name: "标签C", selected: true });
    expect(last).toHaveFocus();
    expect(last).toHaveAttribute("aria-controls", "example-panel-c");
    fireEvent.keyDown(last, { key: "Home" });
    expect(screen.getByRole("tab", { name: "标签A", selected: true })).toHaveFocus();
    expect(last).toHaveAttribute("tabindex", "-1");
  });
});
