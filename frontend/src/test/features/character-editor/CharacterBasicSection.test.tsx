import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CharacterBasicSection } from "../../../features/character-editor/CharacterBasicSection";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderSection() {
  const props: Parameters<typeof CharacterBasicSection>[0] = {
    colorPickerValue: "#ff66aa",
    draft: {
      ...createCharacter(),
      color: "#ff66aa",
      name: "Mio",
      sprite_prefix: "mio",
    },
    nameError: "Name is required",
    onChange: vi.fn(),
    onColorInputRef: vi.fn(),
    onDelete: vi.fn(),
    onPickColor: vi.fn(),
    onPronunciationTextChange: vi.fn(),
    pronunciationText: "Mio=mio",
  };

  const result = render(
    <I18nProvider language="en">
      <CharacterBasicSection {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("CharacterBasicSection", () => {
  it("routes editable field changes through public callbacks", () => {
    const { props } = renderSection();

    fireEvent.change(screen.getByLabelText(/Character name/), { target: { value: "Mio New" } });
    expect(props.onChange).toHaveBeenCalledWith("name", "Mio New");

    fireEvent.change(screen.getAllByDisplayValue("#ff66aa")[0], { target: { value: "#abcdef" } });
    expect(props.onChange).toHaveBeenCalledWith("color", "#abcdef");

    fireEvent.change(screen.getByLabelText("Upload directory name (ASCII)"), { target: { value: "mio_new" } });
    expect(props.onChange).toHaveBeenCalledWith("sprite_prefix", "mio_new");

    fireEvent.change(screen.getByLabelText("Pronunciation map"), { target: { value: "Mio=miyo" } });
    expect(props.onPronunciationTextChange).toHaveBeenCalledWith("Mio=miyo");
  });

  it("exposes validation and destructive actions through the rendered UI", () => {
    const { props } = renderSection();

    expect(screen.getByText("Name is required")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Pick color" }));
    expect(props.onPickColor).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(props.onDelete).toHaveBeenCalledTimes(1);
  });
});
