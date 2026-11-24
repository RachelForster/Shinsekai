import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SpriteFramingControl } from "../../../features/chat-stage/components/SpriteFramingControl";
import type { VisualFraming } from "../../../modules/character-visual";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

afterEach(cleanup);
describe("shared sprite framing controls", () => {
  it("offers full, half and close presets without a format-specific editor", () => {
    const onChange = vi.fn();
    function ControlledFraming() {
      const [framing, setFraming] = useState<VisualFraming | undefined>(undefined);
      return (
        <SpriteFramingControl
          label="Alice"
          value={framing}
          onChange={(next) => {
            setFraming(next);
            onChange(next);
          }}
        />
      );
    }
    render(
      <I18nProvider language="en">
        <ControlledFraming />
      </I18nProvider>,
    );
    expect(screen.getByRole("radio", { name: "Full view" })).toBeChecked();
    expect(screen.getByRole("slider", { name: "Vertical framing position: Alice" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Half view" }));
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 0.5, verticalPosition: 0 });
    expect(screen.getByRole("radio", { name: "Half view" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Close-up" }));
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 0.3, verticalPosition: 0 });
    expect(screen.getByRole("radio", { name: "Close-up" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Full view" }));
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 1, verticalPosition: 0 });
    expect(screen.getByRole("radio", { name: "Full view" })).toBeChecked();
  });
  it("edits height and position independently using percentages", () => {
    const onChange = vi.fn();
    render(
      <I18nProvider language="en">
        <SpriteFramingControl label="Alice" value={{ heightRatio: 0.5, verticalPosition: 0.25 }} onChange={onChange} />
      </I18nProvider>,
    );
    const position = screen.getByRole("slider", { name: "Vertical framing position: Alice" });
    expect(position).not.toBeDisabled();
    expect(position).toHaveAttribute("min", "-100");
    expect(position).toHaveAttribute("max", "100");
    fireEvent.change(position, { target: { value: "75" } });
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 0.5, verticalPosition: 0.75 });
    fireEvent.change(position, { target: { value: "-50" } });
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 0.5, verticalPosition: -0.5 });
    fireEvent.change(screen.getByRole("slider", { name: "Visible height ratio: Alice" }), { target: { value: "40" } });
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 0.4, verticalPosition: 0.25 });
  });
  it("displays negative vertical position percentages and clears preset active state", () => {
    const onChange = vi.fn();
    render(
      <I18nProvider language="en">
        <SpriteFramingControl label="Alice" value={{ heightRatio: 0.5, verticalPosition: -0.5 }} onChange={onChange} />
      </I18nProvider>,
    );
    expect(screen.getByText("-50%")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Half view" })).not.toBeChecked();
  });
});
