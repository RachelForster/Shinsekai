import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CharacterPersonalitySection } from "../../../features/character-editor/CharacterPersonalitySection";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderSection() {
  const props: Parameters<typeof CharacterPersonalitySection>[0] = {
    aiPending: false,
    draft: {
      ...createCharacter(),
      character_setting: "A bright student council member.",
    },
    onAiWrite: vi.fn(),
    onChange: vi.fn(),
    onTranslate: vi.fn(),
    translatePending: false,
  };

  const result = render(
    <I18nProvider language="en">
      <CharacterPersonalitySection {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("CharacterPersonalitySection", () => {
  it("edits character setting text and exposes AI actions", () => {
    const { props } = renderSection();

    fireEvent.change(screen.getByLabelText("Character setting"), { target: { value: "Updated profile" } });
    expect(props.onChange).toHaveBeenCalledWith("character_setting", "Updated profile");

    fireEvent.click(screen.getByRole("button", { name: "AI write" }));
    expect(props.onAiWrite).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "AI translate" }));
    expect(props.onTranslate).toHaveBeenCalledTimes(1);
  });
});
