import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  autoLabelCharacterSprites,
  deleteAllCharacterSprites,
  deleteCharacterSprite,
  saveCharacter,
  saveCharacterEmotionTags,
  saveCharacterSpriteGroups,
  uploadCharacterSprites,
} from "../../../entities/character/repository";
import type { Character } from "../../../entities/config/types";
import { removeTagRows } from "../../../shared/assets/assetText";
import { TAG_PREFIX_SPRITE } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import type { ImageAutoLabelResult, TaskSnapshot } from "../../../shared/platform/types";
import { useToast } from "../../../shared/ui";
import type { SpriteGroupsPatch } from "../CharacterSpritesSection";
import { mergeSprites, type CharacterPageContext } from "../characterContext";

export function useCharacterSpriteMutations(
  ctx: CharacterPageContext,
  { onPortraitCropSaved }: { onPortraitCropSaved: () => void },
) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [autoLabelDialogOpen, setAutoLabelDialogOpen] = useState(false);
  const [autoLabelTask, setAutoLabelTask] = useState<TaskSnapshot<ImageAutoLabelResult> | null>(null);

  const spriteUploadMutation = useMutation({
    mutationFn: async ({
      character,
      emotionTags,
      group,
      originalName,
      paths,
      saveFirst,
    }: {
      character: Character;
      emotionTags: string;
      group?: string;
      originalName?: string;
      paths: string[];
      saveFirst: boolean;
    }) => {
      const saved = saveFirst ? await saveCharacter(character, originalName) : character;
      return uploadCharacterSprites({
        emotionTags,
        ...(group ? { group } : {}),
        name: saved.name,
        paths,
      });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.uploadImages"),
      });
    },
    onSuccess(character, variables) {
      ctx.applyUploadedCharacter(character, {
        originalName: variables.originalName,
        saveFirst: variables.saveFirst,
      });
      showToast({ kind: "success", title: t("character.sprite.uploadImages") });
    },
  });

  const emotionTagsMutation = useMutation({
    mutationFn: (emotionTags: string) => saveCharacterEmotionTags(ctx.currentCharacterName, emotionTags),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.saveTags"),
      });
    },
    onSuccess(character) {
      ctx.upsertCharacterInCache(character);
      ctx.invalidateCharacters();
      ctx.patchDraft((current) => ({ ...current, emotion_tags: character.emotion_tags }));
      showToast({ kind: "success", title: t("character.sprite.saveTags") });
    },
  });

  const autoLabelMutation = useMutation({
    mutationFn: () =>
      autoLabelCharacterSprites(ctx.currentCharacterName, {
        onTaskUpdate: setAutoLabelTask,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("mediaAutoLabel.error"),
        title: t("mediaAutoLabel.action"),
      });
    },
    onSuccess(result) {
      if (ctx.selected) {
        ctx.replaceCharacterInCache({ ...ctx.selected, name: ctx.currentCharacterName, emotion_tags: result.tags });
      }
      ctx.invalidateCharacters();
      ctx.patchDraft((current) => ({ ...current, emotion_tags: result.tags }));
      showToast({
        kind: result.failedCount ? "info" : "success",
        message: t("mediaAutoLabel.complete", {
          annotated: result.annotatedCount,
          failed: result.failedCount,
          skipped: result.skippedCount,
        }),
        title: t("mediaAutoLabel.action"),
      });
    },
  });

  const spriteDeleteMutation = useMutation({
    mutationFn: ({ index, name }: { draft: Character; index: number; name: string }) =>
      deleteCharacterSprite(name, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("common.remove"),
      });
    },
    onSuccess(character, variables) {
      const emotionTags = removeTagRows(
        variables.draft.emotion_tags,
        variables.draft.sprites.length,
        [variables.index],
        TAG_PREFIX_SPRITE,
      );
      const nextCharacter = {
        ...character,
        emotion_tags: emotionTags,
        sprites: mergeSprites(character.sprites, variables.draft),
      };
      ctx.replaceCharacterInCache(nextCharacter);
      ctx.patchDraft((current) => ({
        ...current,
        emotion_tags: removeTagRows(current.emotion_tags, current.sprites.length, [variables.index], TAG_PREFIX_SPRITE),
        sprites: mergeSprites(character.sprites, current),
      }));
      showToast({ kind: "success", title: t("common.remove") });
    },
  });

  const spriteDeleteAllMutation = useMutation({
    mutationFn: (name: string) => deleteAllCharacterSprites(name),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.clear"),
      });
    },
    onSuccess(character) {
      ctx.invalidateCharacters();
      ctx.patchDraft((current) => ({
        ...current,
        emotion_tags: character.emotion_tags,
        sprites: mergeSprites(character.sprites, current),
      }));
      showToast({ kind: "success", title: t("character.sprite.clear") });
    },
  });

  const spriteGroupsMutation = useMutation({
    mutationFn: (patch: SpriteGroupsPatch) =>
      saveCharacterSpriteGroups({
        name: ctx.currentCharacterName,
        ...patch,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(character) {
      ctx.preserveImportedDraft(character);
      ctx.upsertCharacterInCache(character);
      ctx.patchDraft((current) => ({
        ...current,
        default_sprite_group: character.default_sprite_group,
        fallback_to_default_group: character.fallback_to_default_group,
        sprite_groups: character.sprite_groups,
        sprites: mergeSprites(character.sprites, current),
      }));
      showToast({ kind: "success", title: t("spriteGroup.savedToast") });
    },
  });

  const portraitCropMutation = useMutation({
    mutationFn: (nextCharacter: Character) => {
      const source = ctx.selected ? structuredClone(ctx.selected) : structuredClone(nextCharacter);
      const { relation_graph: _omittedRelationGraph, ...base } = source;
      const editedByPath = new Map(nextCharacter.sprites.map((sprite) => [sprite.path, sprite.portrait_crop]));
      base.portrait_crop = nextCharacter.portrait_crop;
      base.sprites = base.sprites.map((sprite, index) => {
        const editedCrop = editedByPath.has(sprite.path)
          ? editedByPath.get(sprite.path)
          : nextCharacter.sprites[index]?.portrait_crop;
        return {
          ...sprite,
          portrait_crop: editedCrop,
        };
      });
      return saveCharacter(base, base.name);
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.portraitCropTitle"),
      });
    },
    onSuccess(character) {
      ctx.preserveImportedDraft(character);
      ctx.replaceCharacterInCache(character);
      ctx.patchDraft((current) => ({
        ...current,
        portrait_crop: character.portrait_crop,
        sprites: current.sprites.map((sprite, index) => {
          const savedSprite = character.sprites.find((item) => item.path === sprite.path) ?? character.sprites[index];
          return savedSprite ? { ...sprite, portrait_crop: savedSprite.portrait_crop } : sprite;
        }),
      }));
      onPortraitCropSaved();
      showToast({ kind: "success", title: t("character.sprite.portraitCropSaved") });
    },
  });

  return {
    autoLabelData: autoLabelMutation.data ?? null,
    autoLabelDialogOpen,
    autoLabelMutation,
    autoLabelTask,
    closeAutoLabelDialog: () => setAutoLabelDialogOpen(false),
    emotionTagsMutation,
    portraitCropMutation,
    setAutoLabelDialogOpen,
    setAutoLabelTask,
    spriteDeleteAllMutation,
    spriteDeleteMutation,
    spriteGroupsMutation,
    spriteUploadMutation,
  };
}
