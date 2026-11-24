import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CharacterPersonalitySection } from "../../../features/character-editor/CharacterPersonalitySection";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderSection() {
  const props: Parameters<typeof CharacterPersonalitySection>[0] = {
    aiPending: false,
    briefPending: false,
    draft: {
      ...createCharacter(),
      character_setting: "A bright student council member.",
    },
    onAiBrief: vi.fn(),
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

    fireEvent.change(screen.getByLabelText("Character brief"), { target: { value: "Short profile" } });
    expect(props.onChange).toHaveBeenCalledWith("character_brief", "Short profile");

    fireEvent.click(screen.getByRole("button", { name: "Generate brief" }));
    expect(props.onAiBrief).toHaveBeenCalledTimes(1);

    const aiWriteButton = screen.getByRole("button", { name: "AI write" });
    const aiTranslateButton = screen.getByRole("button", { name: "AI translate" });
    expect(aiTranslateButton.parentElement).toBe(aiWriteButton.parentElement);
    expect(aiTranslateButton.compareDocumentPosition(aiWriteButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(aiWriteButton);
    expect(props.onAiWrite).toHaveBeenCalledTimes(1);

    fireEvent.click(aiTranslateButton);
    expect(props.onTranslate).toHaveBeenCalledTimes(1);
  });
});
