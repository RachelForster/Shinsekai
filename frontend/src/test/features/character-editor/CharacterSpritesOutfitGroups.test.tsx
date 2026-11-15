import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CharacterSpritesSection } from "../../../features/character-editor/CharacterSpritesSection";
import { SmartOutfitGroupDialog } from "../../../features/character-editor/SmartOutfitGroupDialog";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import type { Character } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

const mockAutoGroupCharacterSprites = vi.fn();
const mockSaveCharacterSpriteGroups = vi.fn();

vi.mock("../../../entities/character/repository", () => ({
  autoGroupCharacterSprites: (input: unknown) => mockAutoGroupCharacterSprites(input),
  saveCharacterSpriteGroups: (input: unknown) => mockSaveCharacterSpriteGroups(input),
}));

vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `asset://${path}`,
}));

const multiOutfitCharacter: Character = {
  ...createCharacter(),
  default_sprite_group: "校服",
  fallback_to_default_group: true,
  name: "Nanami",
  sprite_groups: ["默认", "校服", "私服"],
  sprites: [
    { group: "校服", path: "D:/sprites/school_smile.png" },
    { group: "校服", path: "D:/sprites/school_angry.png" },
    { group: "默认", path: "D:/sprites/default_idle.png" },
    { group: "私服", path: "D:/sprites/casual_wink.png" },
  ],
};

describe("CharacterSpritesSection outfit groups & SmartOutfitGroupDialog", () => {
  it("filters sprites by outfit tab while preserving global #index + 1 numbering and global onSelectSprite index", () => {
    const onSelectSprite = vi.fn();
    const onApplySpriteGroups = vi.fn();
    const galleryItems = multiOutfitCharacter.sprites.map((sprite, index) => ({
      badge: "No voice",
      badgeTone: "muted" as const,
      id: `${sprite.path}-${index}`,
      imageSrc: `asset://${sprite.path}`,
      title: sprite.path.split("/").pop() || `${index + 1}`,
    }));

    render(
      <I18nProvider language="en">
        <CharacterSpritesSection
          draft={multiOutfitCharacter}
          emotionTagsPending={false}
          isSavedCharacter
          onApplySpriteGroups={onApplySpriteGroups}
          onClearSprites={vi.fn()}
          onOpenBulkTags={vi.fn()}
          onPendingVoicePathChange={vi.fn()}
          onSaveTags={vi.fn()}
          onSelectSprite={onSelectSprite}
          onSpriteDelete={vi.fn()}
          onSpriteTagChange={vi.fn()}
          onSpriteUpload={vi.fn()}
          onSpriteVoiceDelete={vi.fn()}
          onSpriteVoiceTextBlur={vi.fn()}
          onSpriteVoiceTextChange={vi.fn()}
          onSpriteVoiceTypeChange={vi.fn()}
          onSpriteVoiceUpload={vi.fn()}
          pendingVoicePath=""
          selectedSprite={multiOutfitCharacter.sprites[0]}
          selectedSpriteIndex={0}
          selectedSpriteTag="smile"
          spriteDeletePending={false}
          spriteGalleryItems={galleryItems}
          spriteUploadPending={false}
          voiceDeletePending={false}
          voiceUploadPending={false}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole("tab", { name: "All (4)" })).toHaveAttribute("aria-selected", "true");
    const casualTab = screen.getByRole("tab", { name: /私服 \(1\)/ });
    fireEvent.click(casualTab);

    // Switching to 私服 auto-selects global index 3 and renders only casual_wink.png with #4 badge!
    expect(onSelectSprite).toHaveBeenCalledWith(3);
    expect(screen.queryByRole("button", { name: /school_smile\.png/ })).not.toBeInTheDocument();
    const casualCard = screen.getByRole("button", { name: /casual_wink\.png/ });
    expect(within(casualCard).getByText("4")).toBeInTheDocument();

    fireEvent.click(casualCard);
    expect(onSelectSprite).toHaveBeenLastCalledWith(3);

    // Batch select visible in 私服 tab and move to 校服
    fireEvent.click(screen.getByRole("button", { name: "Batch move" }));
    fireEvent.click(screen.getByRole("button", { name: "Select visible" }));
    expect(screen.getByText("1 checked")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("combobox", { name: "Choose target group…" }));
    fireEvent.click(screen.getByRole("option", { name: "校服" }));
    fireEvent.click(screen.getByRole("button", { name: "Move to group" }));

    expect(onApplySpriteGroups).toHaveBeenCalledWith({
      assignments: { "3": "校服" },
    });
  });

  it("previews smart auto-grouping and applies assignments via SmartOutfitGroupDialog", async () => {
    mockAutoGroupCharacterSprites.mockResolvedValue({
      assignments: { "0": "校服", "1": "校服", "3": "私服" },
      avatarType: "static",
      changedCount: 3,
      characterName: "Nanami",
      groups: [
        { count: 2, group: "校服", spriteIndices: [0, 1] },
        { count: 1, group: "私服", spriteIndices: [3] },
      ],
      spriteGroups: ["默认", "校服", "私服"],
    });
    mockSaveCharacterSpriteGroups.mockResolvedValue(multiOutfitCharacter);
    const onApplied = vi.fn();
    const onClose = vi.fn();

    render(
      <I18nProvider language="en">
        <SmartOutfitGroupDialog
          characterName="Nanami"
          onApplied={onApplied}
          onClose={onClose}
          open
          sprites={multiOutfitCharacter.sprites}
        />
      </I18nProvider>,
    );

    expect(await screen.findByText("Detected 2 outfit groups (3 sprites updated)")).toBeInTheDocument();
    expect(screen.getByText("#4 · casual_wink.png")).toBeInTheDocument();
    expect(mockAutoGroupCharacterSprites).toHaveBeenCalledWith({
      apply: false,
      name: "Nanami",
      overwriteExisting: false,
    });

    fireEvent.click(screen.getByRole("button", { name: "Apply grouping" }));
    await waitFor(() =>
      expect(mockSaveCharacterSpriteGroups).toHaveBeenCalledWith({
        assignments: { "0": "校服", "1": "校服", "3": "私服" },
        name: "Nanami",
        spriteGroups: ["默认", "校服", "私服"],
      }),
    );
    expect(onApplied).toHaveBeenCalledWith(multiOutfitCharacter, 2);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
