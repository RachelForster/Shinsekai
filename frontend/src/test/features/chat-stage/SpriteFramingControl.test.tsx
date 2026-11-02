import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SpriteFramingControl } from "../../../features/chat-stage/components/SpriteFramingControl";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

afterEach(cleanup);
describe("shared sprite framing controls", () => {
  it("offers full, half and close presets without a format-specific editor", () => {
    const onChange = vi.fn();
    render(
      <I18nProvider language="en">
        <SpriteFramingControl label="Alice" onChange={onChange} />
      </I18nProvider>,
    );
    expect(screen.getByRole("button", { name: "Full view" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("slider", { name: "Vertical framing position: Alice" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Half view" }));
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 0.5, verticalPosition: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Close-up" }));
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 0.3, verticalPosition: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Full view" }));
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 1, verticalPosition: 0 });
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
    fireEvent.change(position, { target: { value: "75" } });
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 0.5, verticalPosition: 0.75 });
    fireEvent.change(screen.getByRole("slider", { name: "Visible height ratio: Alice" }), { target: { value: "40" } });
    expect(onChange).toHaveBeenLastCalledWith({ heightRatio: 0.4, verticalPosition: 0.25 });
  });
});
