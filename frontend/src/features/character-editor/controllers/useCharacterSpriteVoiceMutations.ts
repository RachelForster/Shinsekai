import { useCallback, type Dispatch, type SetStateAction } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  deleteSpriteVoice,
  saveSpriteVoiceText,
  saveSpriteVoiceType,
  uploadSpriteVoice,
} from "../../../entities/character/repository";
import type { Character, Sprite } from "../../../entities/config/types";
import { useI18n } from "../../../shared/i18n";
import type { SpriteVoiceType } from "../../../shared/platform/types";
import { useToast, withSectionBusy } from "../../../shared/ui";
import { mergeSprites, type CharacterPageContext } from "../characterContext";

function characterHasGptSovitsModel(character: Character) {
  return Boolean(character.gpt_model_path?.trim() && character.sovits_model_path?.trim());
}

function spriteHasReferenceVoiceText(sprite: Sprite | undefined) {
  return Boolean(sprite?.voice_text?.trim());
}

export function resolveSpriteVoiceType(sprite: Sprite | undefined, character: Character): SpriteVoiceType {
  return (
    sprite?.voice_type ??
    (characterHasGptSovitsModel(character) && spriteHasReferenceVoiceText(sprite) ? "reference" : "fallback")
  );
}

interface UseCharacterSpriteVoiceMutationsOptions {
  ctx: CharacterPageContext;
  selectedSprite: Sprite | undefined;
  selectedSpriteIndex: number;
  setPendingVoicePaths: Dispatch<SetStateAction<Record<number, string>>>;
}

export function useCharacterSpriteVoiceMutations({
  ctx,
  selectedSprite,
  selectedSpriteIndex,
  setPendingVoicePaths,
}: UseCharacterSpriteVoiceMutationsOptions) {
  const { showToast } = useToast();
  const { t } = useI18n();

  const voiceUploadMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "character-sprites", {
      mutationFn: ({ index, voicePath, voiceText }: { index: number; voicePath: string; voiceText: string }) =>
        uploadSpriteVoice({
          name: ctx.currentCharacterName,
          spriteIndex: index,
          voicePath,
          voiceText,
          voiceType: resolveSpriteVoiceType(ctx.draft.sprites[index], ctx.draft),
        }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
          title: t("character.sprite.uploadVoice"),
        });
      },
      onSuccess(character, variables) {
        ctx.invalidateCharacters();
        ctx.patchDraft((current) => ({
          ...current,
          sprites: mergeSprites(character.sprites, current),
        }));
        setPendingVoicePaths((current) => {
          const next = { ...current };
          delete next[variables.index];
          return next;
        });
        showToast({ kind: "success", title: t("character.sprite.uploadVoice") });
      },
    }),
  );

  const voiceTextMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "character-sprites", {
      mutationFn: ({ index, text }: { index: number; text: string }) =>
        saveSpriteVoiceText(ctx.currentCharacterName, index, text),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
          title: t("character.sprite.saveVoiceText"),
        });
      },
      onSuccess(character, variables) {
        ctx.invalidateCharacters();
        ctx.patchDraft((current) => {
          const sprites = [...current.sprites];
          const returned = character.sprites[variables.index];
          if (returned && sprites[variables.index]) {
            sprites[variables.index] = {
              ...sprites[variables.index],
              voice_path: returned.voice_path || sprites[variables.index].voice_path,
              voice_text: returned.voice_text ?? "",
            };
          }
          return { ...current, sprites };
        });
        showToast({ kind: "success", title: t("character.sprite.saveVoiceText") });
      },
    }),
  );

  const voiceTypeMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "character-sprites", {
      mutationFn: ({ index, voiceType }: { index: number; voiceType: SpriteVoiceType }) =>
        saveSpriteVoiceType(ctx.currentCharacterName, index, voiceType),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
          title: t("character.sprite.voiceType"),
        });
      },
    }),
  );

  const voiceDeleteMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "character-sprites", {
      mutationFn: ({ index, name }: { index: number; name: string }) => deleteSpriteVoice(name, index),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
          title: t("character.sprite.deleteVoice"),
        });
      },
      onSuccess(character, variables) {
        ctx.invalidateCharacters();
        ctx.patchDraft((current) => ({
          ...current,
          sprites: mergeSprites(character.sprites, current),
        }));
        setPendingVoicePaths((current) => {
          const next = { ...current };
          delete next[variables.index];
          return next;
        });
        showToast({ kind: "success", title: t("character.sprite.deleteVoice") });
      },
    }),
  );

  const updateSprite = useCallback(
    (index: number, patch: Partial<Sprite>) => {
      ctx.patchDraft((current) => {
        const sprites = [...current.sprites];
        sprites[index] = { ...sprites[index], ...patch };
        return { ...current, sprites };
      });
    },
    [ctx.patchDraft],
  );

  const saveSelectedSpriteVoiceText = useCallback(
    (text: string) => {
      const savedText = ctx.selected?.sprites[selectedSpriteIndex]?.voice_text ?? "";
      if (ctx.currentCharacterName && text !== savedText && !voiceTextMutation.isPending) {
        voiceTextMutation.mutate({ index: selectedSpriteIndex, text });
      }
    },
    [ctx.currentCharacterName, ctx.selected, selectedSpriteIndex, voiceTextMutation],
  );

  const handleSpriteVoiceTypeChange = useCallback(
    (value: SpriteVoiceType) => {
      updateSprite(selectedSpriteIndex, { voice_type: value });
      if (ctx.isSavedCharacter) {
        voiceTypeMutation.mutate({ index: selectedSpriteIndex, voiceType: value });
      }
    },
    [ctx.isSavedCharacter, selectedSpriteIndex, updateSprite, voiceTypeMutation],
  );

  const uploadSelectedSpriteVoice = useCallback(
    (pendingPath: string) => {
      const voicePath = pendingPath.trim();
      if (!ctx.isSavedCharacter) {
        showToast({
          kind: "error",
          message: t("character.validation.nameRequired"),
          title: t("character.sprite.uploadVoice"),
        });
        return;
      }
      if (!voicePath) {
        showToast({ kind: "error", title: t("character.sprite.voiceUploadPath") });
        return;
      }
      voiceUploadMutation.mutate({
        index: selectedSpriteIndex,
        voicePath,
        voiceText: selectedSprite?.voice_text ?? "",
      });
    },
    [ctx.isSavedCharacter, selectedSprite?.voice_text, selectedSpriteIndex, showToast, t, voiceUploadMutation],
  );

  return {
    deleteSpriteVoice: (index: number, name: string) => voiceDeleteMutation.mutate({ index, name }),
    handleSpriteVoiceTypeChange,
    saveSelectedSpriteVoiceText,
    updateSprite,
    uploadSelectedSpriteVoice,
    voiceDeletePending: voiceDeleteMutation.isPending,
    voiceUploadPending: voiceUploadMutation.isPending,
  };
}
