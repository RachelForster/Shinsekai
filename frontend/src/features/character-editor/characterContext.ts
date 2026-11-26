import type { Dispatch, SetStateAction } from "react";

import type { Character, Sprite } from "../../entities/config/types";
import { numberedTags, tagContents } from "../../shared/assets/assetText";
import { TAG_PREFIX_SPRITE } from "../../shared/constants";
import type { AutoSavePhase } from "../../shared/hooks/useDebouncedAutoSave";
import type { SectionBusyLease } from "../../shared/ui";

export type CharacterSectionSlot = "top-grid" | "body";

export interface CharacterCreatePayload {
  character: Character;
  originalName: undefined;
}

export function mergeSprites(serverSprites: Sprite[], current: Character) {
  const currentSpritesByPath = new Map(
    current.sprites.filter((sprite) => sprite.path).map((sprite) => [sprite.path, sprite]),
  );
  const canFallbackToIndex = serverSprites.length === current.sprites.length;
  return serverSprites.map((sprite, index) => {
    const currentSprite =
      currentSpritesByPath.get(sprite.path) ?? (canFallbackToIndex ? current.sprites[index] : undefined);
    return {
      ...sprite,
      group: sprite.group !== undefined ? sprite.group : currentSprite?.group,
      portrait_crop: sprite.portrait_crop !== undefined ? sprite.portrait_crop : currentSprite?.portrait_crop,
      voice_type: sprite.voice_type ?? currentSprite?.voice_type,
    };
  });
}

export function mergeGeneratedSpritesIntoDraft(
  current: Character,
  imported: Character,
  replacedIndex?: number | number[],
): Character {
  const currentSpritesByPath = new Map(current.sprites.map((sprite) => [sprite.path, sprite]));
  const replacedIndices =
    replacedIndex === undefined ? [] : Array.isArray(replacedIndex) ? replacedIndex : [replacedIndex];
  for (const index of replacedIndices) {
    if (current.sprites[index] && imported.sprites[index]) {
      const path = imported.sprites[index].path;
      currentSpritesByPath.set(path, { ...current.sprites[index], path });
    }
  }
  const currentTags = tagContents(current.emotion_tags, current.sprites.length);
  const tagsByPath = new Map(current.sprites.map((sprite, index) => [sprite.path, currentTags[index]]));
  const savedTags = tagContents(imported.emotion_tags, imported.sprites.length);
  return {
    ...current,
    default_sprite_group: imported.default_sprite_group ?? current.default_sprite_group,
    fallback_to_default_group: imported.fallback_to_default_group ?? current.fallback_to_default_group,
    sprite_groups: imported.sprite_groups ?? current.sprite_groups,
    sprites: imported.sprites.map((sprite) => {
      const draftSprite = currentSpritesByPath.get(sprite.path);
      return draftSprite
        ? { ...draftSprite, group: sprite.group ?? draftSprite.group, mouth_sync: sprite.mouth_sync }
        : sprite;
    }),
    sprite_transitions: imported.sprite_transitions,
    emotion_tags: numberedTags(
      TAG_PREFIX_SPRITE,
      imported.sprites.map((sprite, index) => tagsByPath.get(sprite.path) ?? savedTags[index]),
    ),
  };
}

export interface CharacterPageContext {
  aiActionPending: boolean;
  applyUploadedCharacter: (character: Character, options: { originalName?: string; saveFirst: boolean }) => void;
  autoSaveError: string;
  autoSavePhase: AutoSavePhase;
  autoSaveRetry: () => void;
  buildCharacterCreateInput: () => CharacterCreatePayload | null;
  cancelCreatingCharacter: () => void;
  cancelDeleteCharacter: () => void;
  cancelIdentityField: (field: "name" | "sprite_prefix") => void;
  closeSpriteGeneration: () => void;
  confirmDeleteCharacter: () => void;
  confirmIdentityField: (field: "name" | "sprite_prefix") => void;
  currentCharacterName: string;
  data: Character[];
  draft: Character;
  exportCurrentCharacter: () => void;
  exportPending: boolean;
  handleSpriteGenerationImported: (character: Character, replacedIndex?: number | number[]) => void;
  identityPending: boolean;
  identitySavingField: "name" | "sprite_prefix" | null;
  importCharacters: (items: string[]) => void;
  importPending: boolean;
  inCreateMode: boolean;
  invalidateCharacters: () => void;
  isCreating: boolean;
  isLoading: boolean;
  isSavedCharacter: boolean;
  isSelectionActive: (sourceKey: string, wasCreating: boolean) => boolean;
  liveNameError: string;
  liveSpritePrefixError: string;
  nameDirty: boolean;
  openSpriteGeneration: () => void;
  patchDraft: Dispatch<SetStateAction<Character>>;
  pendingDelete: string | null;
  preserveImportedDraft: (character: Character) => void;
  pronunciationText: string;
  replaceCharacterInCache: (character: Character) => void;
  requestCharacterDelete: () => void;
  saveDraft: () => void;
  savePending: boolean;
  selected: Character | undefined;
  selectedCharacterKey: string;
  selectedName: string;
  selectExistingCharacter: (name: string) => void;
  beginSectionBusy: (sectionId: string) => SectionBusyLease;
  setNameError: Dispatch<SetStateAction<string>>;
  setPronunciationText: Dispatch<SetStateAction<string>>;
  setSectionBusy: (sectionId: string, busy: boolean) => void;
  spriteGenerationOpen: boolean;
  spritePrefixDirty: boolean;
  startCreatingCharacter: () => void;
  syncGeneratedSetting: (input: {
    characterBrief?: string;
    characterSetting: string;
    committedName: string;
    identityEpoch: number;
    name: string;
    sourceKey: string;
    wasCreating: boolean;
  }) => void;
  syncModelStateCharacter: (character: Character) => void;
  tryBeginAiAction: () => { identityEpoch: number; release: () => void } | null;
  updateField: <K extends keyof Character>(name: K, value: Character[K]) => void;
  upsertCharacterInCache: (character: Character) => void;
  visionAvailable: boolean;
  voiceReferenceReadOnly: boolean;
}
