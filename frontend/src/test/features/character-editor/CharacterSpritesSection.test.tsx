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
    onPendingVoicePathChange: vi.fn(),
    onSaveTags: vi.fn(),
    onSelectSprite: vi.fn(),
    onSpriteDelete: vi.fn(),
    onSpriteTagChange: vi.fn(),
    onSpriteUpload: vi.fn(),
    onSpriteVoiceDelete: vi.fn(),
    onSpriteVoiceTextBlur: vi.fn(),
    onSpriteVoiceTextChange: vi.fn(),
    onSpriteVoiceUpload: vi.fn(),
    onSpriteVoiceTypeChange: vi.fn(),
    pendingVoicePath: "D:/new/voice.wav",
    selectedSprite: draft.sprites[1],
    selectedSpriteIndex: 1,
    selectedSpriteTag: "happy",
    spriteDeletePending: false,
    spriteGalleryItems: [
      { id: "sprite-a", imageSrc: "asset://D:/sprites/sprite-a.png", meta: "neutral", title: "sprite-a.png" },
      { id: "sprite-b", imageSrc: "asset://D:/sprites/sprite-b.png", meta: "happy", title: "sprite-b.png" },
    ],
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
  it("only shows the smart-label action when vision is available", () => {
    const onAutoLabel = vi.fn();
    const first = renderSection();
    expect(screen.queryByRole("button", { name: "Smart labeling" })).not.toBeInTheDocument();
    first.unmount();

    renderSection({ autoLabelAvailable: true, autoLabelDisabled: false, onAutoLabel });
    fireEvent.click(screen.getByRole("button", { name: "Smart labeling" }));
    expect(onAutoLabel).toHaveBeenCalledOnce();
  });

  it("shows an empty state and disables batch tagging and portrait crop when there are no sprites", () => {
    const onOpenPortraitCrop = vi.fn();
    renderSection({
      draft: { ...createCharacter(), sprites: [] },
      onOpenPortraitCrop,
      selectedSprite: undefined,
      spriteGalleryItems: [],
    });

    expect(screen.getByRole("button", { name: "Batch tags" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Avatar" })).toBeDisabled();
  });

  it("opens the portrait crop dialog when Avatar is clicked", () => {
    const onOpenPortraitCrop = vi.fn();
    renderSection({ onOpenPortraitCrop });

    const button = screen.getByRole("button", { name: "Avatar" });
    expect(button).toHaveAttribute("title", "Adjust portrait crop");
    fireEvent.click(button);
    expect(onOpenPortraitCrop).toHaveBeenCalledOnce();
  });

  it("routes gallery, tag, voice, and destructive actions through callbacks", () => {
    const { props } = renderSection();

    fireEvent.click(screen.getByRole("button", { name: /sprite-a\.png/ }));
    expect(props.onSelectSprite).toHaveBeenCalledWith(0);

    expect(screen.queryByRole("button", { name: "Save scale" })).not.toBeInTheDocument();

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

  it("renders the matching voice type hint for each sprite voice mode", () => {
    const { props, rerender } = renderSection();
    const selectedSprite = props.selectedSprite;
    expect(selectedSprite).toBeDefined();

    expect(screen.getByText(/Reference audio will be used for TTS voice cloning/)).toBeInTheDocument();

    rerender(
      <I18nProvider language="en">
        <CharacterSpritesSection {...props} selectedSprite={{ ...selectedSprite!, voice_type: "preset" }} />
      </I18nProvider>,
    );
    expect(
      screen.getByText("Preset voice skips TTS and always plays the audio file attached to this sprite."),
    ).toBeInTheDocument();

    rerender(
      <I18nProvider language="en">
        <CharacterSpritesSection {...props} selectedSprite={{ ...selectedSprite!, voice_type: "fallback" }} />
      </I18nProvider>,
    );
    expect(
      screen.getByText(
        "Fallback voice plays only when no usable TTS engine is configured, preserving legacy sprite audio behavior.",
      ),
    ).toBeInTheDocument();
  });

  it("hides voice text controls for fallback voices and keeps them for preset voices", () => {
    const { props, rerender } = renderSection({
      selectedSprite: {
        path: "D:/sprites/sprite-b.png",
        voice_path: "D:/voices/sprite-b.wav",
        voice_text: "Hello",
        voice_type: "fallback",
      },
    });

    expect(screen.queryByLabelText("Voice text")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save text" })).not.toBeInTheDocument();

    rerender(
      <I18nProvider language="en">
        <CharacterSpritesSection
          {...props}
          selectedSprite={{
            path: "D:/sprites/sprite-b.png",
            voice_path: "D:/voices/sprite-b.wav",
            voice_text: "Hello",
            voice_type: "preset",
          }}
        />
      </I18nProvider>,
    );

    expect(screen.getByLabelText("Voice text")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save text" })).toBeInTheDocument();
  });

  it("applies a single-primary hierarchy in the sprite section header and inspector", () => {
    const { container } = renderSection({
      autoLabelAvailable: true,
      autoLabelDisabled: false,
      onAutoLabel: vi.fn(),
      onGenerate: vi.fn(),
      onOpenPortraitCrop: vi.fn(),
    });

    const headerActions = container.querySelector(".section__header .page__actions");
    expect(headerActions).not.toBeNull();
    expect(headerActions!.querySelectorAll(".button--primary")).toHaveLength(1);
    expect(Array.from(headerActions!.querySelectorAll("button")).map((button) => button.textContent?.trim())).toEqual([
      "Delete all sprites",
      "Smart labeling",
      "Batch tags",
      "Avatar",
      "Generate sprites",
      "Upload",
    ]);

    expect(screen.getByRole("button", { name: "Upload" })).toHaveClass("button--primary");
    expect(screen.getByRole("button", { name: "Generate sprites" })).not.toHaveClass(
      "button--primary",
      "button--ghost",
      "button--danger",
    );
    expect(screen.getByRole("button", { name: "Smart labeling" })).toHaveClass("button--ghost");
    expect(screen.getByRole("button", { name: "Batch tags" })).toHaveClass("button--ghost");
    expect(screen.getByRole("button", { name: "Avatar" })).toHaveClass("button--ghost");
    expect(screen.getByRole("button", { name: "Delete all sprites" })).toHaveClass("button--danger");

    const inspectorActions = container.querySelector(".asset-inspector__actions");
    expect(inspectorActions).not.toBeNull();
    expect(
      Array.from(inspectorActions!.querySelectorAll("button")).map((button) => button.textContent?.trim()),
    ).toEqual(["Remove", "Delete voice", "Upload voice"]);

    expect(screen.getByRole("button", { name: "Upload tags" })).not.toHaveClass("button--ghost");
    expect(screen.getByRole("button", { name: "Upload voice" })).not.toHaveClass("button--ghost");
    expect(screen.getByRole("button", { name: "Delete voice" })).toHaveClass("button--ghost");
    expect(screen.getByRole("button", { name: "Remove" })).toHaveClass("button--danger");
  });
});
