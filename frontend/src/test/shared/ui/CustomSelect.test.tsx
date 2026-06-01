import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CustomSelect } from "../../../shared/ui";

describe("CustomSelect", () => {
  it("renders the selected option and emits select-like change events", () => {
    const onChange = vi.fn();
    render(
      <CustomSelect id="mode" name="mode" onChange={onChange} value="auto">
        <option value="auto">Automatic</option>
        <option value="manual">Manual</option>
      </CustomSelect>,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "" }));
    fireEvent.click(screen.getByRole("option", { name: "Manual" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].target).toMatchObject({ id: "mode", name: "mode", value: "manual" });
  });

  it("skips disabled options during keyboard selection", () => {
    const onChange = vi.fn();
    render(
      <CustomSelect id="provider" onChange={onChange} value="first">
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

  it("falls back to the native select when multiple is enabled", () => {
    const onChange = vi.fn();
    render(
      <CustomSelect multiple onChange={onChange} value={["a"]}>
        <option value="a">A</option>
        <option value="b">B</option>
      </CustomSelect>,
    );

    expect(screen.getByRole("listbox")).toHaveClass("select");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
