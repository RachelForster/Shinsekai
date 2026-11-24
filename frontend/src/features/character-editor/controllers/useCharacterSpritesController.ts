import { useCallback, useEffect, useMemo, useState } from "react";

import type { Character } from "../../../entities/config/types";
import { fileUrl } from "../../../entities/files/repository";
import { baseName, numberedTags, tagContents } from "../../../shared/assets/assetText";
import { isVideoMedia } from "../../../shared/assets/visualMedia";
import { TAG_PREFIX_SPRITE } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import { useToast } from "../../../shared/ui";
import type { SpriteGroupsPatch } from "../CharacterSpritesSection";
import { mergeSprites, type CharacterPageContext } from "../characterContext";
import {
  DEFAULT_SPRITE_GROUP,
  normalizeSpriteGroupName,
  resolveCharacterSpriteGroups,
  type CharacterResourceDeleteTarget,
} from "../characterEditorUtils";
import { useCharacterSpriteMutations } from "./useCharacterSpriteMutations";
import { resolveSpriteVoiceType, useCharacterSpriteVoiceMutations } from "./useCharacterSpriteVoiceMutations";

type SpriteDeleteTarget = Extract<CharacterResourceDeleteTarget, { kind: "sprite" | "all-sprites" | "sprite-voice" }>;

export function useCharacterSpritesController(ctx: CharacterPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [pendingVoicePaths, setPendingVoicePaths] = useState<Record<number, string>>({});
  const [selectedSpriteIndex, setSelectedSpriteIndex] = useState(0);
  const [activeSpriteGroup, setActiveSpriteGroup] = useState("__all__");
  const [smartGroupOpen, setSmartGroupOpen] = useState(false);
  const [bulkSpriteTagsOpen, setBulkSpriteTagsOpen] = useState(false);
  const [bulkSpriteTagsDraft, setBulkSpriteTagsDraft] = useState("");
  const [portraitCropOpen, setPortraitCropOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<SpriteDeleteTarget | null>(null);

  useEffect(() => {
    setPendingVoicePaths({});
    setSelectedSpriteIndex(0);
    setActiveSpriteGroup("__all__");
    setSmartGroupOpen(false);
    ctx.setSectionBusy("character-sprites:smart-group", false);
  }, [ctx.selectedCharacterKey, ctx.setSectionBusy]);

  useEffect(() => {
    setSelectedSpriteIndex((current) => Math.min(current, Math.max(0, ctx.draft.sprites.length - 1)));
  }, [ctx.draft.sprites.length]);

  useEffect(
    () => () => {
      ctx.setSectionBusy("character-sprites:portrait-crop", false);
      ctx.setSectionBusy("character-sprites:bulk-tags", false);
      ctx.setSectionBusy("character-sprites:smart-group", false);
    },
    [ctx.setSectionBusy],
  );

  const selectedSprite = ctx.draft.sprites[selectedSpriteIndex];
  const voice = useCharacterSpriteVoiceMutations({
    ctx,
    selectedSprite,
    selectedSpriteIndex,
    setPendingVoicePaths,
  });

  const {
    autoLabelData,
    autoLabelDialogOpen,
    autoLabelMutation,
    autoLabelTask,
    closeAutoLabelDialog,
    emotionTagsMutation,
    portraitCropMutation,
    setAutoLabelDialogOpen,
    setAutoLabelTask,
    spriteDeleteAllMutation,
    spriteDeleteMutation,
    spriteGroupsMutation,
    spriteUploadMutation,
  } = useCharacterSpriteMutations(ctx, {
    onPortraitCropSaved: () => {
      ctx.setSectionBusy("character-sprites:portrait-crop", false);
      setPortraitCropOpen(false);
    },
  });

  const handleApplySpriteGroups = useCallback(
    (patch: SpriteGroupsPatch) => {
      if (!ctx.isSavedCharacter) {
        ctx.patchDraft((current) => {
          let groups = resolveCharacterSpriteGroups(current);
          if (patch.spriteGroups) {
            groups = resolveCharacterSpriteGroups({ ...current, sprite_groups: patch.spriteGroups });
          }
          let defaultGroup = patch.defaultSpriteGroup
            ? normalizeSpriteGroupName(patch.defaultSpriteGroup)
            : normalizeSpriteGroupName(current.default_sprite_group);
          let sprites = current.sprites.map((sprite) => ({ ...sprite }));
          if (patch.assignments) {
            for (const [rawIndex, group] of Object.entries(patch.assignments)) {
              const idx = Number(rawIndex);
              const normalized = normalizeSpriteGroupName(group);
              if (Number.isInteger(idx) && sprites[idx]) {
                sprites[idx] = { ...sprites[idx], group: normalized };
                if (!groups.includes(normalized)) {
                  groups = [...groups, normalized];
                }
              }
            }
          }
          if (patch.deleteGroup && patch.deleteGroup !== DEFAULT_SPRITE_GROUP) {
            groups = groups.filter((group) => group !== patch.deleteGroup);
            if (defaultGroup === patch.deleteGroup) {
              defaultGroup = DEFAULT_SPRITE_GROUP;
            }
            sprites = sprites.map((sprite) =>
              normalizeSpriteGroupName(sprite.group) === patch.deleteGroup
                ? { ...sprite, group: DEFAULT_SPRITE_GROUP }
                : sprite,
            );
          }
          if (!groups.includes(defaultGroup)) {
            groups = [...groups, defaultGroup];
          }
          return {
            ...current,
            default_sprite_group: defaultGroup,
            fallback_to_default_group: patch.fallbackToDefaultGroup ?? current.fallback_to_default_group ?? true,
            sprite_groups: groups,
            sprites,
          };
        });
        return;
      }
      spriteGroupsMutation.mutate(patch);
    },
    [ctx.isSavedCharacter, ctx.patchDraft, spriteGroupsMutation],
  );

  const handleSavePortraitCrop = useCallback(
    (nextCharacter: Character) => {
      if (!ctx.isSavedCharacter) {
        ctx.patchDraft((current) => ({
          ...current,
          portrait_crop: nextCharacter.portrait_crop,
          sprites: current.sprites.map((sprite, index) => ({
            ...sprite,
            portrait_crop: nextCharacter.sprites[index]?.portrait_crop,
          })),
        }));
        ctx.setSectionBusy("character-sprites:portrait-crop", false);
        setPortraitCropOpen(false);
        showToast({ kind: "success", title: t("character.sprite.portraitCropSaved") });
        return;
      }
      portraitCropMutation.mutate(nextCharacter);
    },
    [ctx.isSavedCharacter, ctx.patchDraft, ctx.setSectionBusy, portraitCropMutation, showToast, t],
  );

  const uploadSprites = useCallback(
    (paths: string[]) => {
      if (!paths.length) {
        return;
      }
      const group =
        activeSpriteGroup !== "__all__" && activeSpriteGroup !== DEFAULT_SPRITE_GROUP ? activeSpriteGroup : undefined;
      if (!ctx.isSavedCharacter || !ctx.selected) {
        const input = ctx.buildCharacterCreateInput();
        if (!input) {
          return;
        }
        spriteUploadMutation.mutate({
          ...input,
          emotionTags: input.character.emotion_tags,
          group,
          paths,
          saveFirst: true,
        });
        return;
      }
      spriteUploadMutation.mutate({
        character: ctx.selected,
        emotionTags: ctx.draft.emotion_tags,
        group,
        originalName: ctx.selected.name,
        paths,
        saveFirst: false,
      });
    },
    [
      activeSpriteGroup,
      ctx.buildCharacterCreateInput,
      ctx.draft.emotion_tags,
      ctx.isSavedCharacter,
      ctx.selected,
      spriteUploadMutation,
    ],
  );

  const updateSpriteTag = useCallback(
    (index: number, value: string) => {
      ctx.patchDraft((current) => {
        const tags = tagContents(current.emotion_tags, current.sprites.length);
        tags[index] = value;
        return { ...current, emotion_tags: numberedTags(TAG_PREFIX_SPRITE, tags) };
      });
    },
    [ctx.patchDraft],
  );

  const requestClearSprites = useCallback(() => {
    if (!ctx.isSavedCharacter || !ctx.draft.sprites.length) {
      showToast({ kind: "error", title: t("character.sprite.clear") });
      return;
    }
    setPendingDelete({
      characterName: ctx.currentCharacterName,
      count: ctx.draft.sprites.length,
      kind: "all-sprites",
    });
  }, [ctx.currentCharacterName, ctx.draft.sprites.length, ctx.isSavedCharacter, showToast, t]);

  const saveSpriteTags = useCallback(() => {
    if (!ctx.isSavedCharacter || !ctx.draft.emotion_tags) {
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("character.sprite.saveTags"),
      });
      return;
    }
    emotionTagsMutation.mutate(ctx.draft.emotion_tags);
  }, [ctx.draft.emotion_tags, ctx.isSavedCharacter, emotionTagsMutation, showToast, t]);

  const confirmBulkSpriteTags = useCallback(() => {
    const nextTags = bulkSpriteTagsDraft;
    ctx.updateField("emotion_tags", nextTags);
    if (ctx.isSavedCharacter && nextTags.trim() && !emotionTagsMutation.isPending) {
      emotionTagsMutation.mutate(nextTags);
    }
    ctx.setSectionBusy("character-sprites:bulk-tags", false);
    setBulkSpriteTagsOpen(false);
  }, [bulkSpriteTagsDraft, ctx.isSavedCharacter, ctx.setSectionBusy, ctx.updateField, emotionTagsMutation]);

  const requestSelectedSpriteVoiceDelete = useCallback(() => {
    if (!ctx.currentCharacterName || !selectedSprite?.voice_path) {
      showToast({ kind: "error", title: t("character.sprite.deleteVoice") });
      return;
    }
    setPendingDelete({
      characterName: ctx.currentCharacterName,
      filename: baseName(selectedSprite.path) || `${selectedSpriteIndex + 1}`,
      index: selectedSpriteIndex,
      kind: "sprite-voice",
    });
  }, [ctx.currentCharacterName, selectedSprite, selectedSpriteIndex, showToast, t]);

  const requestSelectedSpriteDelete = useCallback(() => {
    if (!ctx.currentCharacterName || !selectedSprite) {
      showToast({ kind: "error", title: t("common.remove") });
      return;
    }
    setPendingDelete({
      characterName: ctx.currentCharacterName,
      filename: baseName(selectedSprite.path) || `${selectedSpriteIndex + 1}`,
      index: selectedSpriteIndex,
      kind: "sprite",
    });
  }, [ctx.currentCharacterName, selectedSprite, selectedSpriteIndex, showToast, t]);

  const confirmPendingDelete = useCallback(() => {
    if (!pendingDelete) {
      return;
    }
    const target = pendingDelete;
    setPendingDelete(null);
    if (target.kind === "sprite") {
      spriteDeleteMutation.mutate({
        draft: structuredClone(ctx.draft),
        index: target.index,
        name: target.characterName,
      });
    } else if (target.kind === "all-sprites") {
      spriteDeleteAllMutation.mutate(target.characterName);
    } else {
      voice.deleteSpriteVoice(target.index, target.characterName);
    }
  }, [ctx.draft, pendingDelete, spriteDeleteAllMutation, spriteDeleteMutation, voice]);

  const spriteTags = useMemo(
    () => tagContents(ctx.draft.emotion_tags, ctx.draft.sprites.length),
    [ctx.draft.emotion_tags, ctx.draft.sprites.length],
  );
  const selectedSpriteTag = spriteTags[selectedSpriteIndex] ?? "";
  const spriteGalleryItems = useMemo(
    () =>
      ctx.draft.sprites.map((sprite, index) => ({
        badge: sprite.voice_path ? t("character.sprite.hasVoice") : t("character.sprite.noVoice"),
        badgeTone: sprite.voice_path ? ("default" as const) : ("muted" as const),
        cornerLabel: sprite.mouth_sync ? t("spriteMouth.tab") : undefined,
        id: `${sprite.path}-${index}`,
        imageSrc: sprite.path && !isVideoMedia(sprite.path) ? fileUrl(sprite.path) : "",
        videoSrc: isVideoMedia(sprite.path) ? fileUrl(sprite.path) : undefined,
        meta: spriteTags[index] || sprite.voice_text || "",
        title: baseName(sprite.path) || `${index + 1}`,
      })),
    [ctx.draft.sprites, spriteTags, t],
  );

  const pendingDeleteCopy = pendingDelete
    ? {
        body:
          pendingDelete.kind === "sprite"
            ? t("character.sprite.deleteConfirmBody", {
                filename: pendingDelete.filename,
                index: pendingDelete.index + 1,
                name: pendingDelete.characterName,
              })
            : pendingDelete.kind === "all-sprites"
              ? t("character.sprite.clearConfirmBody", {
                  count: pendingDelete.count,
                  name: pendingDelete.characterName,
                })
              : t("character.sprite.deleteVoiceConfirmBody", {
                  filename: pendingDelete.filename,
                  index: pendingDelete.index + 1,
                }),
        confirmLabel:
          pendingDelete.kind === "sprite" || pendingDelete.kind === "sprite-voice"
            ? t("common.remove")
            : t("common.delete"),
        title:
          pendingDelete.kind === "all-sprites"
            ? t("character.sprite.clear")
            : pendingDelete.kind === "sprite-voice"
              ? t("character.sprite.deleteVoice")
              : t("common.remove"),
      }
    : null;

  return {
    activeSpriteGroup,
    autoLabelData,
    autoLabelDialogOpen,
    autoLabelDisabled: !ctx.isSavedCharacter || !ctx.draft.sprites.length || !spriteTags.some((tag) => !tag.trim()),
    autoLabelPending: autoLabelMutation.isPending,
    autoLabelTask,
    bulkSpriteTagsDraft,
    bulkSpriteTagsOpen,
    cancelPendingDelete: () => setPendingDelete(null),
    closeAutoLabelDialog,
    closeBulkTags: () => {
      ctx.setSectionBusy("character-sprites:bulk-tags", false);
      setBulkSpriteTagsOpen(false);
    },
    closePortraitCrop: () => {
      ctx.setSectionBusy("character-sprites:portrait-crop", false);
      setPortraitCropOpen(false);
    },
    closeSmartGroup: () => {
      ctx.setSectionBusy("character-sprites:smart-group", false);
      setSmartGroupOpen(false);
    },
    confirmBulkSpriteTags,
    confirmPendingDelete,
    emotionTagsPending: emotionTagsMutation.isPending,
    generateDisabled: !ctx.isSavedCharacter || !ctx.draft.character_setting.trim(),
    generateHint: !ctx.isSavedCharacter
      ? t("spriteGeneration.saveFirst")
      : !ctx.draft.character_setting.trim()
        ? t("spriteGeneration.settingRequired")
        : undefined,
    handleApplySmartGroup: (character: Character, groupCount: number) => {
      ctx.preserveImportedDraft(character);
      ctx.upsertCharacterInCache(character);
      ctx.patchDraft((current) => ({
        ...current,
        default_sprite_group: character.default_sprite_group,
        fallback_to_default_group: character.fallback_to_default_group,
        sprite_groups: character.sprite_groups,
        sprites: mergeSprites(character.sprites, current),
      }));
      showToast({
        kind: "success",
        title: t("spriteGroup.autoGroupApplied", { groups: groupCount }),
      });
    },
    handleApplySpriteGroups,
    handleAutoLabel: () => {
      setAutoLabelTask(null);
      setAutoLabelDialogOpen(true);
      autoLabelMutation.mutate();
    },
    handleOpenPortraitCrop: () => {
      ctx.setSectionBusy("character-sprites:portrait-crop", true);
      portraitCropMutation.reset();
      setPortraitCropOpen(true);
    },
    handleSavePortraitCrop,
    handleSpriteVoiceTypeChange: voice.handleSpriteVoiceTypeChange,
    openBulkSpriteTagsDialog: () => {
      ctx.setSectionBusy("character-sprites:bulk-tags", true);
      setBulkSpriteTagsDraft(ctx.draft.emotion_tags);
      setBulkSpriteTagsOpen(true);
    },
    openSmartGroup: () => {
      ctx.setSectionBusy("character-sprites:smart-group", true);
      setSmartGroupOpen(true);
    },
    pendingDeleteCopy,
    pendingDeleteOpen: Boolean(pendingDelete),
    pendingVoicePath: pendingVoicePaths[selectedSpriteIndex] ?? "",
    portraitCropError: portraitCropMutation.isError
      ? portraitCropMutation.error instanceof Error
        ? portraitCropMutation.error.message
        : String(portraitCropMutation.error)
      : undefined,
    portraitCropOpen,
    portraitCropSaving: portraitCropMutation.isPending,
    requestClearSprites,
    requestSelectedSpriteDelete,
    requestSelectedSpriteVoiceDelete,
    saveSelectedSpriteVoiceText: voice.saveSelectedSpriteVoiceText,
    saveSpriteTags,
    selectedSprite: selectedSprite
      ? { ...selectedSprite, voice_type: resolveSpriteVoiceType(selectedSprite, ctx.draft) }
      : undefined,
    selectedSpriteIndex,
    selectedSpriteTag,
    setActiveSpriteGroup,
    setBulkSpriteTagsDraft,
    setSelectedSpriteIndex,
    smartGroupOpen,
    spriteDeletePending: spriteDeleteMutation.isPending,
    spriteGalleryItems,
    spriteGroupsPending: spriteGroupsMutation.isPending,
    spriteUploadPending: spriteUploadMutation.isPending,
    updatePendingVoicePath: (path: string) =>
      setPendingVoicePaths((current) => ({ ...current, [selectedSpriteIndex]: path })),
    updateSpriteTag,
    updateSelectedSpriteVoiceText: (value: string) => voice.updateSprite(selectedSpriteIndex, { voice_text: value }),
    uploadSelectedSpriteVoice: () => voice.uploadSelectedSpriteVoice(pendingVoicePaths[selectedSpriteIndex] ?? ""),
    uploadSprites,
    voiceDeletePending: voice.voiceDeletePending,
    voiceUploadPending: voice.voiceUploadPending,
  };
}
