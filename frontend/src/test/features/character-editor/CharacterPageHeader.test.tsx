import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CharacterPageHeader } from "../../../features/character-editor/CharacterPageHeader";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

const mocks = {
  openExternal: vi.fn(),
};

vi.mock("../../../entities/files/repository", () => ({
  openExternal: (url: string) => mocks.openExternal(url),
}));

function renderHeader(overrides: Partial<Parameters<typeof CharacterPageHeader>[0]> = {}) {
  const props: Parameters<typeof CharacterPageHeader>[0] = {
    characters: [
      { ...createCharacter(), name: "Mio" },
      { ...createCharacter(), name: "Aki" },
    ],
    exportPending: false,
    importPending: false,
    isCreating: false,
    isLoading: false,
    onCreate: vi.fn(),
    onExport: vi.fn(),
    onImport: vi.fn(),
    onSave: vi.fn(),
    onSelectCharacter: vi.fn(),
    savePending: false,
    selectedName: "Mio",
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <CharacterPageHeader {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("CharacterPageHeader", () => {
  it("routes primary toolbar actions through public callbacks", () => {
    const { props } = renderHeader();

    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(props.onCreate).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(props.onExport).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.onSave).toHaveBeenCalledTimes(1);
  });

  it("selects characters and opens community links without touching production APIs", () => {
    const { props } = renderHeader();

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "Aki" }));
    expect(props.onSelectCharacter).toHaveBeenCalledWith("Aki");

    fireEvent.click(screen.getByRole("button", { name: "Community characters" }));
    fireEvent.click(screen.getByRole("button", { name: "Upload contribution" }));
    expect(mocks.openExternal).toHaveBeenCalledTimes(2);
    expect(mocks.openExternal.mock.calls[0][0]).toContain("resources");
  });
});
