import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CharacterPicker } from "../../../features/template-editor/CharacterPicker";
import { I18nProvider } from "../../../shared/i18n";

it("allows removing an unavailable character even when the library is empty", () => {
  const onChange = vi.fn();
  render(
    <I18nProvider language="en">
      <CharacterPicker characters={[]} selected={["Alice"]} onChange={onChange} />
    </I18nProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Alice (unavailable; click to deselect)" }));
  expect(onChange).toHaveBeenCalledWith([]);
});
