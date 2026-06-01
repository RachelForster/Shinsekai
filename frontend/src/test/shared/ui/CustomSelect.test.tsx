import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CustomSelect } from "../../../shared/ui/CustomSelect";

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

  it("skips disabled options during keyboard navigation", () => {
    const onChange = vi.fn();
    render(
      <CustomSelect id="provider" onChange={onChange} defaultValue="a">
        <option value="a">A</option>
        <option disabled value="b">
          B
        </option>
        <option value="c">C</option>
      </CustomSelect>,
    );

    const combo = screen.getByRole("combobox");
    fireEvent.keyDown(combo, { key: "ArrowDown" });
    fireEvent.keyDown(combo, { key: "ArrowDown" });
    fireEvent.keyDown(combo, { key: "Enter" });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].target.value).toBe("c");
    expect(screen.getByRole("combobox")).toHaveTextContent("C");
  });

  it("falls back to the native select for multiple mode", () => {
    render(
      <CustomSelect defaultValue={["a", "b"]} multiple>
        <option value="a">A</option>
        <option value="b">B</option>
      </CustomSelect>,
    );

    expect(screen.getByRole("listbox")).toHaveClass("select");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
