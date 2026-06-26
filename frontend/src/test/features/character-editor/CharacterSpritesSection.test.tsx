import { fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { CharacterSpritesSection } from "../../../features/character-editor/CharacterSpritesSection";
import { createCharacter } from "../../../features/character-editor/characterEditorUtils";
import type { Character } from "../../../shared/platform/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

let originalMediaLoad: PropertyDescriptor | undefined;
let originalMediaPause: PropertyDescriptor | undefined;

beforeAll(() => {
  originalMediaLoad = Object.getOwnPropertyDescriptor(window.HTMLMediaElement.prototype, "load");
  originalMediaPause = Object.getOwnPropertyDescriptor(window.HTMLMediaElement.prototype, "pause");
  Object.defineProperty(window.HTMLMediaElement.prototype, "load", {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(window.HTMLMediaElement.prototype, "pause", {
    configurable: true,
    value: vi.fn(),
  });
});

afterAll(() => {
  if (originalMediaLoad) {
    Object.defineProperty(window.HTMLMediaElement.prototype, "load", originalMediaLoad);
  }
  if (originalMediaPause) {
    Object.defineProperty(window.HTMLMediaElement.prototype, "pause", originalMediaPause);
  }
});

vi.mock("../../../entities/files/repository", () => ({
  fileUrl: (path: string) => `asset://${path}`,
}));

function renderSection(overrides: Partial<Parameters<typeof CharacterSpritesSection>[0]> = {}) {
  const draft: Character = {
    ...createCharacter(),
    sprite_scale: 1.25,
    sprites: [
      { path: "D:/sprites/sprite-a.png" },
      {
        path: "D:/sprites/sprite-b.png",
        voice_path: "D:/voices/sprite-b.wav",
        voice_text: "Hello",
        voice_type: "reference",
      },
    ],
  };
  const props: Parameters<typeof CharacterSpritesSection>[0] = {
    draft,
    emotionTagsPending: false,
    onClearSprites: vi.fn(),
    onOpenBulkTags: vi.fn(),
    onPendingSpritePathsChange: vi.fn(),
    onPendingVoicePathChange: vi.fn(),
    onSaveScale: vi.fn(),
    onSaveTags: vi.fn(),
    onScaleChange: vi.fn(),
    onScaleWheel: vi.fn(),
    onSelectSprite: vi.fn(),
    onSpriteDelete: vi.fn(),
    onSpriteTagChange: vi.fn(),
    onSpriteUpload: vi.fn(),
    onSpriteVoiceDelete: vi.fn(),
    onSpriteVoiceTextBlur: vi.fn(),
    onSpriteVoiceTextChange: vi.fn(),
    onSpriteVoiceUpload: vi.fn(),
    onSpriteVoiceTypeChange: vi.fn(),
    pendingSpritePaths: ["D:/new/sprite-c.png"],
    pendingVoicePath: "D:/new/voice.wav",
    selectedSprite: draft.sprites[1],
    selectedSpriteIndex: 1,
    selectedSpriteTag: "happy",
    spriteDeletePending: false,
    spriteGalleryItems: [
      { id: "sprite-a", imageSrc: "asset://D:/sprites/sprite-a.png", meta: "neutral", title: "sprite-a.png" },
      { id: "sprite-b", imageSrc: "asset://D:/sprites/sprite-b.png", meta: "happy", title: "sprite-b.png" },
    ],
    spriteScalePending: false,
    spriteUploadPending: false,
    voiceDeletePending: false,
    voiceUploadPending: false,
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <CharacterSpritesSection {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("CharacterSpritesSection", () => {
  it("shows an empty state and disables batch tagging when there are no sprites", () => {
    renderSection({
      draft: { ...createCharacter(), sprites: [] },
      selectedSprite: undefined,
      spriteGalleryItems: [],
    });

    expect(screen.getByRole("button", { name: "Batch tags" })).toBeDisabled();
  });

  it("routes gallery, scale, tag, voice, and destructive actions through callbacks", () => {
    const { props } = renderSection();

    fireEvent.click(screen.getByRole("button", { name: /sprite-a\.png/ }));
    expect(props.onSelectSprite).toHaveBeenCalledWith(0);

    fireEvent.change(screen.getByDisplayValue("1.25"), { target: { value: "1.5" } });
    expect(props.onScaleChange).toHaveBeenCalledWith("sprite_scale", 1.5);

    fireEvent.click(screen.getByRole("button", { name: "Save scale" }));
    expect(props.onSaveScale).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(props.onSpriteUpload).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Batch tags" }));
    expect(props.onOpenBulkTags).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Delete all sprites" }));
    expect(props.onClearSprites).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("Sprite tag"), { target: { value: "surprised" } });
    expect(props.onSpriteTagChange).toHaveBeenCalledWith("surprised");

    fireEvent.click(screen.getByRole("button", { name: "Upload tags" }));
    expect(props.onSaveTags).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByDisplayValue("Hello"), { target: { value: "Updated voice line" } });
    expect(props.onSpriteVoiceTextChange).toHaveBeenCalledWith("Updated voice line");
    fireEvent.blur(screen.getByDisplayValue("Hello"), { target: { value: "Updated voice line" } });
    expect(props.onSpriteVoiceTextBlur).toHaveBeenCalledWith("Updated voice line");

    fireEvent.click(screen.getByRole("button", { name: "Upload voice" }));
    expect(props.onSpriteVoiceUpload).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Delete voice" }));
    expect(props.onSpriteVoiceDelete).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(props.onSpriteDelete).toHaveBeenCalledTimes(1);
  });
});
