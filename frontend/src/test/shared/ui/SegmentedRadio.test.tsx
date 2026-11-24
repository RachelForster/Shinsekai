import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SegmentedRadio } from "../../../shared/ui";

afterEach(cleanup);

const options = [
  { label: "Alpha", value: "alpha" },
  { label: "Beta", value: "beta" },
  { label: "Gamma", value: "gamma" },
] as const;

describe("SegmentedRadio", () => {
  it("renders an equal-segment radiogroup with radio inputs and checks the active option", () => {
    render(<SegmentedRadio ariaLabel="Mode" onChange={() => {}} options={options} value="beta" />);

    const group = screen.getByRole("radiogroup", { name: "Mode" });
    expect(group).toHaveClass("segmented-radio", "segmented-radio--md");
    expect(within(group).getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByRole("radio", { name: "Alpha" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Beta" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Gamma" })).not.toBeChecked();
  });

  it("supports null or undefined value with no option checked", () => {
    render(<SegmentedRadio ariaLabel="Preset" onChange={() => {}} options={options} value={null} />);

    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).not.toBeChecked();
    }
  });

  it("calls onChange with the clicked option value", () => {
    const onChange = vi.fn();
    render(<SegmentedRadio ariaLabel="Mode" onChange={onChange} options={options} value="alpha" />);

    fireEvent.click(screen.getByRole("radio", { name: "Gamma" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("gamma");
  });

  it("disables all options when disabled is true and respects option-level disabled", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <SegmentedRadio
        ariaLabel="Mode"
        onChange={onChange}
        options={[
          { label: "Alpha", value: "alpha" },
          { disabled: true, label: "Beta", value: "beta" },
        ]}
        size="sm"
        value="alpha"
      />,
    );

    expect(screen.getByRole("radiogroup", { name: "Mode" })).toHaveClass("segmented-radio--sm");
    expect(screen.getByRole("radio", { name: "Alpha" })).toBeEnabled();
    expect(screen.getByRole("radio", { name: "Beta" })).toBeDisabled();

    rerender(
      <SegmentedRadio ariaLabel="Mode" disabled onChange={onChange} options={options} size="sm" value="alpha" />,
    );
    expect(screen.getByRole("radiogroup", { name: "Mode" })).toHaveClass("segmented-radio--disabled");
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).toBeDisabled();
    }
  });

  it("renders option icons and isolates generated group names while respecting explicit name", () => {
    render(
      <>
        <SegmentedRadio
          ariaLabel="First"
          onChange={() => {}}
          options={[{ icon: <svg data-testid="alpha-icon" />, label: "Alpha", value: "alpha" }]}
          value="alpha"
        />
        <SegmentedRadio ariaLabel="Second" name="explicit-group" onChange={() => {}} options={options} value="beta" />
      </>,
    );

    expect(screen.getByTestId("alpha-icon")).toBeInTheDocument();
    const firstRadio = within(screen.getByRole("radiogroup", { name: "First" })).getByRole("radio");
    const secondRadios = within(screen.getByRole("radiogroup", { name: "Second" })).getAllByRole("radio");
    expect(firstRadio.getAttribute("name")).toBeTruthy();
    expect(firstRadio.getAttribute("name")).not.toBe("explicit-group");
    for (const radio of secondRadios) {
      expect(radio).toHaveAttribute("name", "explicit-group");
    }
  });
});
