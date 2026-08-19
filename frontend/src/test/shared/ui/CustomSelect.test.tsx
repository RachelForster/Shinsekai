import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CustomSelect } from "../../../shared/ui";

describe("CustomSelect", () => {
  it("renders the selected label and emits select-like change events", () => {
    const onChange = vi.fn();
    render(
      <CustomSelect id="mode" name="mode" onChange={onChange} value="safe">
        <option value="fast">Fast</option>
        <option value="safe">Safe</option>
      </CustomSelect>,
    );

    const combo = screen.getByRole("combobox");
    expect(combo).toHaveTextContent("Safe");

    fireEvent.click(combo);
    fireEvent.click(screen.getByRole("option", { name: "Fast" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].target).toMatchObject({
      id: "mode",
      name: "mode",
      value: "fast",
    });
  });

  it("skips disabled options during keyboard selection", () => {
    const onChange = vi.fn();
    render(
      <CustomSelect id="provider" onChange={onChange} defaultValue="first">
        <option value="first">First</option>
        <option disabled value="blocked">
          Blocked
        </option>
        <option value="last">Last</option>
      </CustomSelect>,
    );

    const trigger = screen.getByRole("combobox");
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ target: expect.objectContaining({ value: "last" }) }),
    );
    expect(screen.getByRole("combobox")).toHaveTextContent("Last");
  });

  it("closes when focus moves outside", () => {
    render(
      <>
        <CustomSelect id="theme" defaultValue="dark">
          <option value="dark">Dark</option>
          <option value="light">Light</option>
        </CustomSelect>
        <button type="button">Outside</button>
      </>,
    );

    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.focusIn(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("keeps a multi-select menu open and emits the clicked option", () => {
    const onChange = vi.fn();
    render(
      <CustomSelect multiple onChange={onChange} value={["a"]}>
        <option value="a">A</option>
        <option value="b">B</option>
      </CustomSelect>,
    );

    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toHaveAttribute("aria-multiselectable", "true");
    expect(screen.getByRole("option", { name: "A" })).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("option", { name: "B" }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ target: expect.objectContaining({ value: "b" }) }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
  });
});
