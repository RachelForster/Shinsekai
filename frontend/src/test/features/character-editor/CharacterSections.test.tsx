import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CharacterBasicSection } from "../../../features/character-editor/CharacterBasicSection";
import { CharacterListPanel } from "../../../features/character-editor/CharacterListPanel";
import { CharacterMemorySection } from "../../../features/character-editor/CharacterMemorySection";
import { CharacterSpritesSection } from "../../../features/character-editor/CharacterSpritesSection";
import { SpriteTagsDialog } from "../../../features/character-editor/SpriteTagsDialog";
import type { Character } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

function renderEn(children: ReactNode) {
  return render(<I18nProvider language="en">{children}</I18nProvider>);
}

const characterDraft: Character = {
  character_setting: "Quiet student.",
  color: "#66ccff",
  emotion_tags: "happy",
  name: "Mika",
  pronunciation_map: {},
  speech_speed: 1,
  speech_volume: 1,
  sprite_prefix: "mika",
  sprite_scale: 1,
  sprites: [
    {
      path: "/project/chars/mika/Sprite01.webp",
      voice_path: "/project/chars/mika/voice/Sprite01.wav",
      voice_text: "Hello",
    },
  ],
};

describe("Character editor sections", () => {
  beforeEach(() => {
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("edits basic fields and keeps the color picker action reachable", () => {
    const onChange = vi.fn();
    const onDelete = vi.fn();
    const onPickColor = vi.fn();
    const onPronunciationTextChange = vi.fn();

    renderEn(
      <CharacterBasicSection
        colorPickerValue="#66ccff"
        draft={characterDraft}
        nameError="Name already exists"
        onChange={onChange}
        onColorInputRef={vi.fn()}
        onDelete={onDelete}
        onPickColor={onPickColor}
        onPronunciationTextChange={onPronunciationTextChange}
        pronunciationText="美香=みか"
      />,
    );

    expect(screen.getByText("Name already exists")).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("Mika"), { target: { value: "Mika 2" } });
    fireEvent.change(screen.getByDisplayValue("mika"), { target: { value: "mika2" } });
    fireEvent.change(screen.getByDisplayValue("美香=みか"), { target: { value: "新=しん" } });
    fireEvent.click(screen.getByRole("button", { name: "Pick color" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(onChange).toHaveBeenCalledWith("name", "Mika 2");
    expect(onChange).toHaveBeenCalledWith("sprite_prefix", "mika2");
    expect(onPronunciationTextChange).toHaveBeenCalledWith("新=しん");
    expect(onPickColor).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("shows character list state and reports selected character names", () => {
    const onRetry = vi.fn();
    const onSelect = vi.fn();

    renderEn(
      <CharacterListPanel
        characters={[
          { ...characterDraft, color: "#ff99aa", name: "Mika" },
          { ...characterDraft, color: "#99ffaa", name: "Sora" },
        ]}
        currentDraftName="Mika"
        error={null}
        isCreating={false}
        isError={false}
        isLoading={false}
        onRetry={onRetry}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByRole("button", { name: /Mika/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("button", { name: /Sora/ }));
    expect(onSelect).toHaveBeenCalledWith("Sora");
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("edits sprite preview metadata and routes sprite actions", () => {
    const onScaleChange = vi.fn();
    const onScaleWheel = vi.fn();
    const onSelectSprite = vi.fn();
    const onSpriteTagChange = vi.fn();
    const onSpriteVoiceTextBlur = vi.fn();
    const onSpriteVoiceTextChange = vi.fn();
    const actions = {
      onClearSprites: vi.fn(),
      onOpenBulkTags: vi.fn(),
      onPendingSpritePathsChange: vi.fn(),
      onPendingVoicePathChange: vi.fn(),
      onSaveScale: vi.fn(),
      onSaveTags: vi.fn(),
      onSpriteDelete: vi.fn(),
      onSpriteUpload: vi.fn(),
      onSpriteVoiceDelete: vi.fn(),
      onSpriteVoiceUpload: vi.fn(),
    };

    renderEn(
      <CharacterSpritesSection
        draft={characterDraft}
        emotionTagsPending={false}
        onScaleChange={onScaleChange}
        onScaleWheel={onScaleWheel}
        onSelectSprite={onSelectSprite}
        onSpriteTagChange={onSpriteTagChange}
        onSpriteVoiceTextBlur={onSpriteVoiceTextBlur}
        onSpriteVoiceTextChange={onSpriteVoiceTextChange}
        pendingSpritePaths={["/tmp/new.webp"]}
        pendingVoicePath="/tmp/new.wav"
        selectedSprite={characterDraft.sprites[0]}
        selectedSpriteIndex={0}
        selectedSpriteTag="happy"
        spriteDeletePending={false}
        spriteGalleryItems={[
          {
            badge: "Voice",
            id: "sprite-1",
            imageSrc: "/asset/Sprite01.webp",
            meta: "happy",
            title: "Sprite01.webp",
          },
        ]}
        spriteScalePending={false}
        spriteUploadPending={false}
        voiceDeletePending={false}
        voiceUploadPending={false}
        {...actions}
      />,
    );

    fireEvent.wheel(screen.getByDisplayValue("1").closest(".character-scale-control")!);
    fireEvent.change(screen.getByDisplayValue("1"), { target: { value: "1.25" } });
    fireEvent.click(screen.getByRole("button", { name: /Sprite01.webp/ }));
    fireEvent.change(screen.getByDisplayValue("happy"), { target: { value: "smile" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload tags" }));
    fireEvent.change(screen.getByDisplayValue("Hello"), { target: { value: "New line" } });
    fireEvent.blur(screen.getByDisplayValue("Hello"));
    fireEvent.click(screen.getByRole("button", { name: "Upload voice" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete voice" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Batch tags" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete all sprites" }));

    expect(onScaleWheel).toHaveBeenCalledTimes(1);
    expect(onScaleChange).toHaveBeenCalledWith("sprite_scale", 1.25);
    expect(onSelectSprite).toHaveBeenCalledWith(0);
    expect(onSpriteTagChange).toHaveBeenCalledWith("smile");
    expect(actions.onSaveTags).toHaveBeenCalledTimes(1);
    expect(onSpriteVoiceTextChange).toHaveBeenCalledWith("New line");
    expect(onSpriteVoiceTextBlur).toHaveBeenCalledWith("Hello");
    expect(actions.onSpriteVoiceUpload).toHaveBeenCalledTimes(1);
    expect(actions.onSpriteVoiceDelete).toHaveBeenCalledTimes(1);
    expect(actions.onSpriteDelete).toHaveBeenCalledTimes(1);
    expect(actions.onOpenBulkTags).toHaveBeenCalledTimes(1);
    expect(actions.onClearSprites).toHaveBeenCalledTimes(1);
  });

  it("renders memory rows and protects disabled memory actions", () => {
    const onAddMemory = vi.fn();
    const onDeleteMemory = vi.fn();
    const onMemoryInputChange = vi.fn();
    const onRefresh = vi.fn();

    renderEn(
      <CharacterMemorySection
        addPending={false}
        data={{
          agentId: "Mika",
          count: 2,
          memories: [
            { id: "mem-1", memory: "Likes rain." },
            { id: "", memory: "Draft only." },
          ],
        }}
        deletePending={false}
        error={null}
        isError={false}
        isFetched
        isFetching={false}
        isLoading={false}
        memoryInput="New memory"
        memoryName="Mika"
        onAddMemory={onAddMemory}
        onDeleteMemory={onDeleteMemory}
        onMemoryInputChange={onMemoryInputChange}
        onRefresh={onRefresh}
      />,
    );

    expect(screen.getByText("2 memories")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    fireEvent.change(screen.getByPlaceholderText("Memory content"), { target: { value: "Updated memory" } });
    fireEvent.click(screen.getByRole("button", { name: "Add memory" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);

    expect(screen.getAllByRole("button", { name: "Delete" })[1]).toBeDisabled();
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(onMemoryInputChange).toHaveBeenCalledWith("Updated memory");
    expect(onAddMemory).toHaveBeenCalledTimes(1);
    expect(onDeleteMemory).toHaveBeenCalledWith({ id: "mem-1", memory: "Likes rain." });
  });

  it("edits and confirms sprite batch tag dialogs", () => {
    const onChange = vi.fn();
    const onClose = vi.fn();
    const onConfirm = vi.fn();

    renderEn(<SpriteTagsDialog draft="happy\nsad" onChange={onChange} onClose={onClose} onConfirm={onConfirm} open />);

    expect(screen.getByRole("dialog", { name: "Batch sprite tags" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Emotion tags (per upload / order)"), { target: { value: "angry" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onChange).toHaveBeenCalledWith("angry");
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
