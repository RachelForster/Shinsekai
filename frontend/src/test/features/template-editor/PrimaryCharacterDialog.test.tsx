import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PrimaryCharacterDialog } from "../../../features/template-editor/PrimaryCharacterDialog";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { Character } from "../../../shared/platform/types";

const characters = Array.from({ length: 6 }, (_, index) => ({
  character_brief: index === 5 ? "Brief ready" : "",
  character_setting: `Full setting ${index + 1}`,
  color: "#66ccff",
  emotion_tags: "",
  name: `Character ${index + 1}`,
  pronunciation_map: {},
  speech_speed: 1,
  speech_volume: 1,
  sprite_prefix: `character-${index + 1}`,
  sprite_scale: 1,
  sprites: [],
})) satisfies Character[];

function renderDialog(overrides: Partial<Parameters<typeof PrimaryCharacterDialog>[0]> = {}) {
  const props: Parameters<typeof PrimaryCharacterDialog>[0] = {
    characters,
    onConfirm: vi.fn(),
    onUseAll: vi.fn(),
    open: true,
    ...overrides,
  };
  render(
    <I18nProvider language="en">
      <PrimaryCharacterDialog {...props} />
    </I18nProvider>,
  );
  return props;
}

describe("PrimaryCharacterDialog", () => {
  it("allows more than four primary characters and confirms the full selection", () => {
    const props = renderDialog();

    for (const character of characters.slice(1)) {
      fireEvent.click(screen.getByRole("button", { name: new RegExp(character.name) }));
    }
    expect(screen.getByText("6 primary of 6 characters")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Apply roles" }));

    expect(props.onConfirm).toHaveBeenCalledWith(characters.map((character) => character.name));
  });

  it("shows brief state and treats either cancel action as use-all", () => {
    const props = renderDialog({ initialPrimaryCharacters: ["Character 1"] });

    expect(screen.getAllByText("Brief will be generated")).toHaveLength(4);
    expect(screen.getByText("Brief ready")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Use all as primary" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(props.onUseAll).toHaveBeenCalledTimes(2);
  });

  it("cannot be dismissed while brief generation is pending", () => {
    const props = renderDialog({ pending: true });
    const dialog = screen.getByRole("dialog", { name: "Choose primary characters" });

    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "Escape" });

    expect(props.onUseAll).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Use all as primary" })).toBeDisabled();
  });
});
