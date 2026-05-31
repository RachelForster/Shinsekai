import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Switch } from "../../../shared/ui";

describe("Switch", () => {
  it("renders as a checkbox", () => {
    render(<Switch />);
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
  });

  it("is checked when passed checked=true", () => {
    render(<Switch checked onChange={() => {}} />);
    expect(screen.getByRole("checkbox")).toBeChecked();
  });

  it("fires onChange on click", () => {
    const onChange = vi.fn();
    render(<Switch onChange={onChange} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].target.checked).toBe(true);
  });

  it("disables when passed disabled", () => {
    render(<Switch disabled />);
    expect(screen.getByRole("checkbox")).toBeDisabled();
  });

  it("renders a label when children are provided", () => {
    render(<Switch>启用</Switch>);
    expect(screen.getByText("启用")).toBeInTheDocument();
  });
});
