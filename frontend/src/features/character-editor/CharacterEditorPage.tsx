import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { configQueryKey, getAppConfig } from "../../entities/config/repository";
import { templatesQueryKey } from "../../entities/template/repository";
import { relationQueryKey } from "../../entities/character-relation/repository";
import {
  charactersQueryKey,
  autoLabelCharacterSprites,
  deleteCharacter,
  deleteAllCharacterSprites,
  deleteCharacterSprite,
  deleteSpriteVoice,
  exportCharacter,
  generateCharacterBrief,
  generateCharacterSetting,
  importCharacters,
  listCharacters,
  saveCharacter,
  saveCharacterEmotionTags,
  saveCharacterSpriteGroups,
  saveSpriteVoiceText,
  saveSpriteVoiceType,
  translateCharacterFields,
  uploadCharacterSprites,
  uploadSpriteVoice,
} from "../../entities/character/repository";
import type { Character, Sprite } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import { baseName, numberedTags, removeTagRows, tagContents } from "../../shared/assets/assetText";
import { suggestUniqueSpritePrefix } from "../../shared/assets/spritePrefix";
import { isVideoMedia } from "../../shared/assets/visualMedia";
import { DEFAULT_CHARACTER_COLOR, TAG_PREFIX_SPRITE } from "../../shared/constants";
import { useDebouncedAutoSave } from "../../shared/hooks/useDebouncedAutoSave";
import { useI18n } from "../../shared/i18n";
import { SELF_PERSONA_NAME } from "../../shared/playerCharacterOptions";
import type {
  ImageAutoLabelResult,
  SpriteVoiceType,
  TaskSnapshot,
  TemplateLaunchSession,
} from "../../shared/platform/types";
import { AlertDialog, PageSectionNav, useToast } from "../../shared/ui";
import { CharacterBasicSection } from "./CharacterBasicSection";
import { CharacterMemoryDialogs } from "./CharacterMemoryDialogs";
import { CharacterMemoryImportDialogs } from "./CharacterMemoryImportDialogs";
import { CharacterMemorySection } from "./CharacterMemorySection";
import { CharacterPageHeader } from "./CharacterPageHeader";
import { CharacterPersonalitySection } from "./CharacterPersonalitySection";
import { CharacterRelationSection } from "../character-relation/view/CharacterRelationSection";
import { CharacterSpritesSection, type SpriteGroupsPatch } from "./CharacterSpritesSection";
import { SmartOutfitGroupDialog } from "./SmartOutfitGroupDialog";
import { SpriteGenerationPage } from "./SpriteGenerationPage";
import { CharacterVoiceSection } from "./CharacterVoiceSection";
import { MediaAutoLabelProgressDialog } from "../media-auto-label/MediaAutoLabelProgressDialog";
import { useVisionAvailability } from "../media-auto-label/useVisionAvailability";
import { SpriteTagsDialog } from "./SpriteTagsDialog";
import {
  DEFAULT_SPRITE_GROUP,
  SELF_PERSONA_SPRITE_PREFIX,
  buildCommittedCharacterPayload,
  buildNewCharacterPayload,
  createCharacter,
  isSelfPersonaCharacter,
  normalizeSpriteGroupName,
  pronunciationMapToText,
  pronunciationTextToMap,
  resolveCharacterSpriteGroups,
  serializeCharacterNonIdentity,
  upsertCatalogCharacter,
  type CharacterResourceDeleteTarget,
} from "./characterEditorUtils";
import { useCharacterMemoryController } from "./useCharacterMemoryController";
import { useCharacterMemoryImportController } from "./useCharacterMemoryImportController";
import "./CharacterEditorPage.css";
import { ModelStateEditor } from "./ModelStateEditor";
import { PortraitCropDialog } from "../../shared/components/PortraitCropDialog";

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

export function CharacterEditorPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const visionAvailable = useVisionAvailability();
  const charactersQuery = useQuery({ queryFn: listCharacters, queryKey: charactersQueryKey });
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const data = charactersQuery.data ?? [];
  const isLoading = charactersQuery.isLoading;
  const voiceReferenceReadOnly = configQuery.data?.api_config?.tts_provider === "kaggle-gpt-sovits";
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<Character>(createCharacter());
  const [isCreating, setIsCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [pendingResourceDelete, setPendingResourceDelete] = useState<CharacterResourceDeleteTarget | null>(null);
  const [pendingVoicePaths, setPendingVoicePaths] = useState<Record<number, string>>({});
  const [selectedSpriteIndex, setSelectedSpriteIndex] = useState(0);
  const [activeSpriteGroup, setActiveSpriteGroup] = useState("__all__");
  const [smartGroupOpen, setSmartGroupOpen] = useState(false);
  const [bulkSpriteTagsOpen, setBulkSpriteTagsOpen] = useState(false);
  const [bulkSpriteTagsDraft, setBulkSpriteTagsDraft] = useState("");
  const [portraitCropOpen, setPortraitCropOpen] = useState(false);
  const [autoLabelDialogOpen, setAutoLabelDialogOpen] = useState(false);
  const [spriteGenerationOpen, setSpriteGenerationOpen] = useState(false);
  const generationReturnRef = useRef<{ element: HTMLElement | null; scrollTop: number } | null>(null);
  useEffect(() => {
    if (spriteGenerationOpen || !generationReturnRef.current) return;
    const saved = generationReturnRef.current;
    generationReturnRef.current = null;
    const frame = requestAnimationFrame(() => {
      if (saved.element) saved.element.scrollTop = saved.scrollTop;
      document.querySelector<HTMLElement>("[data-sprite-generation-trigger]")?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [spriteGenerationOpen]);
  const preserveImportedDraftRef = useRef<Character | null>(null);
  const previousSelectedNameRef = useRef("");
  const [spritePrefixTouched, setSpritePrefixTouched] = useState(false);
  const [spritePrefixError, setSpritePrefixError] = useState("");
  const [identitySavingField, setIdentitySavingField] = useState<"name" | "sprite_prefix" | null>(null);
  const [autoLabelTask, setAutoLabelTask] = useState<TaskSnapshot<ImageAutoLabelResult> | null>(null);
  const [nameError, setNameError] = useState("");
  const [pronunciationText, setPronunciationText] = useState("");
  const colorInputRef = useRef<HTMLInputElement | null>(null);
  const [syncedCharacterKey, setSyncedCharacterKey] = useState("");
  const isCreatingRef = useRef(isCreating);
  isCreatingRef.current = isCreating;
  const deletedCharacterKeysRef = useRef<Set<string>>(new Set());
  const cancelAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const discardAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const pendingAiActionsRef = useRef(0);
  const identityPendingRef = useRef(false);
  const identityMutationEpochRef = useRef(0);
  const inCreateMode = isCreating || data.length === 0;
  const existingPrefixes = useMemo(() => data.map((character) => character.sprite_prefix), [data]);
  const selected = useMemo(() => {
    if (isCreating) {
      return undefined;
    }
    if (selectedName) {
      return data.find((character) => character.name === selectedName);
    }
    return data[0];
  }, [data, isCreating, selectedName]);
  const currentCharacterName = isCreating ? "" : selected?.name || selectedName;
  const isSavedCharacter = Boolean(
    !isCreating &&
    (selected || (currentCharacterName && data.some((character) => character.name === currentCharacterName))),
  );
  const memoryName = isSavedCharacter ? currentCharacterName : draft.name.trim();
  const memoryController = useCharacterMemoryController({ memoryName });
  const memoryImportController = useCharacterMemoryImportController({
    ensureReady: memoryController.ensureReady,
    memoryName,
    onRefresh: memoryController.refresh,
  });
  const colorPickerValue = /^#[0-9a-fA-F]{6}$/.test(draft.color || "") ? draft.color : DEFAULT_CHARACTER_COLOR;
  const setColorInputElement = useCallback((element: HTMLInputElement | null) => {
    colorInputRef.current = element;
  }, []);
  const openColorPicker = useCallback(() => {
    colorInputRef.current?.click();
  }, []);

  const activeCharacterKeyRef = useRef<string>("");
  useEffect(() => {
    if (!selected) {
      activeCharacterKeyRef.current = "";
      setSyncedCharacterKey("");
      return;
    }
    const selectedKey = selected.id || `name:${selected.name}`;
    if (selected.name === preserveImportedDraftRef.current?.name) {
      preserveImportedDraftRef.current = null;
      activeCharacterKeyRef.current = selectedKey;
      setSyncedCharacterKey(selectedKey);
      return;
    }
    if (selectedKey !== activeCharacterKeyRef.current) {
      activeCharacterKeyRef.current = selectedKey;
      setSyncedCharacterKey(selectedKey);
      setSelectedName(selected.name);
      setDraft(structuredClone(selected));
      setPronunciationText(pronunciationMapToText(selected.pronunciation_map));
      setPendingVoicePaths({});
      setSelectedSpriteIndex(0);
      setActiveSpriteGroup("__all__");
      setSmartGroupOpen(false);
      setNameError("");
      setSpritePrefixError("");
      setSpritePrefixTouched(false);
    } else if (selected.id) {
      setDraft((current) => (current.id ? current : { ...current, id: selected.id }));
    }
  }, [selected]);

  useEffect(() => {
    setSelectedSpriteIndex((current) => Math.min(current, Math.max(0, draft.sprites.length - 1)));
  }, [draft.sprites.length]);

  const syncRenamedCharacterCaches = useCallback(
    (oldName: string | undefined, newName: string) => {
      if (!oldName || oldName === newName) {
        return;
      }
      void queryClient.invalidateQueries({ queryKey: relationQueryKey });
      void queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "binding-names"] });
      queryClient.setQueryData<TemplateLaunchSession | null>([...templatesQueryKey, "session"], (current) =>
        current
          ? {
              ...current,
              primaryCharacters: current.primaryCharacters?.map((name) => (name === oldName ? newName : name)),
              selectedCharacters: current.selectedCharacters.map((name) => (name === oldName ? newName : name)),
            }
          : current,
      );
    },
    [queryClient],
  );

  const saveMutation = useMutation({
    mutationFn: ({ character, originalName }: { character: Character; originalName?: string }) =>
      saveCharacter(character, originalName),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(character, variables) {
      const nextKey = character.id || `name:${character.name}`;
      deletedCharacterKeysRef.current.delete(nextKey);
      deletedCharacterKeysRef.current.delete(`name:${character.name}`);
      isCreatingRef.current = false;
      activeCharacterKeyRef.current = nextKey;
      setSyncedCharacterKey(nextKey);
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        upsertCatalogCharacter(current, character, variables.originalName),
      );
      setIsCreating(false);
      setSpritePrefixTouched(false);
      setNameError("");
      setSpritePrefixError("");
      setSelectedName(character.name);
      setDraft(structuredClone(character));
      setPronunciationText(pronunciationMapToText(character.pronunciation_map));
      syncRenamedCharacterCaches(variables.originalName, character.name);
      showToast({ kind: "success", title: t("character.toast.saved") });
    },
  });

  const identityMutation = useMutation({
    mutationFn: async ({
      character,
      originalName,
      sourceKey,
    }: {
      character: Character;
      field: "name" | "sprite_prefix";
      originalName: string;
      sourceKey: string;
    }) => {
      await discardAutoSaveRef.current(sourceKey);
      return saveCharacter(character, originalName);
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSettled() {
      identityPendingRef.current = false;
      setIdentitySavingField(null);
    },
    onSuccess(character, variables) {
      identityMutationEpochRef.current += 1;
      if (
        deletedCharacterKeysRef.current.has(variables.sourceKey) ||
        deletedCharacterKeysRef.current.has(`name:${variables.originalName}`)
      ) {
        return;
      }
      const nextKey = character.id || `name:${character.name}`;
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        upsertCatalogCharacter(current, character, variables.originalName),
      );
      syncRenamedCharacterCaches(variables.originalName, character.name);
      if (!isCreatingRef.current && activeCharacterKeyRef.current === variables.sourceKey) {
        activeCharacterKeyRef.current = nextKey;
        setSyncedCharacterKey(nextKey);
        setSelectedName(character.name);
        setDraft((current) => ({
          ...current,
          ...(character.id ? { id: character.id } : {}),
          avatars: {
            ...current.avatars,
            ...character.avatars,
          },
          default_sprite_group: character.default_sprite_group,
          fallback_to_default_group: character.fallback_to_default_group,
          is_builtin: character.is_builtin,
          name: variables.field === "name" ? character.name : current.name,
          pinned: character.pinned,
          portrait_crop: character.portrait_crop,
          portrait_sprite_index: character.portrait_sprite_index,
          sprite_groups: character.sprite_groups,
          sprite_prefix: variables.field === "sprite_prefix" ? character.sprite_prefix : current.sprite_prefix,
          sprite_transitions: character.sprite_transitions,
          sprites: mergeSprites(character.sprites, current),
          undeletable: character.undeletable,
        }));
        if (variables.field === "name") {
          setNameError("");
        } else {
          setSpritePrefixError("");
        }
      }
      showToast({ kind: "success", title: t("character.toast.saved") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (targetName: string) => {
      const target = data.find((item) => item.name === targetName);
      const targetKey = target ? target.id || `name:${target.name}` : `name:${targetName}`;
      deletedCharacterKeysRef.current.add(targetKey);
      deletedCharacterKeysRef.current.add(`name:${targetName}`);
      await cancelAutoSaveRef.current(targetKey);
      return deleteCharacter(targetName);
    },
    onSuccess(_result, deletedName) {
      setSelectedName((current) => (current === deletedName ? "" : current));
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "instances"] });
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "binding-names"] });
      queryClient.setQueryData<TemplateLaunchSession | null>([...templatesQueryKey, "session"], (current) => {
        if (!current) {
          return current;
        }
        const primaryCharacters = current.primaryCharacters?.filter((name) => name !== deletedName);
        return {
          ...current,
          characterPromptMode:
            current.characterPromptMode === "compact" && !primaryCharacters?.length
              ? undefined
              : current.characterPromptMode,
          primaryCharacters,
          selectedCharacters: current.selectedCharacters.filter((name) => name !== deletedName),
        };
      });
      setPendingDelete(null);
      showToast({ kind: "success", title: t("character.toast.deleted") });
    },
    onError(error, deletedName) {
      const target = data.find((item) => item.name === deletedName);
      if (target?.id) {
        deletedCharacterKeysRef.current.delete(target.id);
      }
      deletedCharacterKeysRef.current.delete(`name:${deletedName}`);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.deleteFallback"),
        title: t("common.deleteFailed"),
      });
    },
  });

  const importMutation = useMutation({
    mutationFn: importCharacters,
    onSuccess(imported) {
      for (const item of imported) {
        if (item.id) {
          deletedCharacterKeysRef.current.delete(item.id);
        }
        deletedCharacterKeysRef.current.delete(`name:${item.name}`);
      }
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      const lastImported = imported[imported.length - 1];
      if (lastImported) {
        isCreatingRef.current = false;
        setIsCreating(false);
        setSelectedName(lastImported.name);
      }
      showToast({ kind: "success", title: t("character.toast.importComplete", { count: imported.length }) });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.importFallback"),
        title: t("common.importFailed"),
      });
    },
  });

  const exportMutation = useMutation({
    mutationFn: exportCharacter,
    onSuccess(path) {
      showToast({ kind: "success", message: path, title: t("character.toast.exportComplete") });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.exportFallback"),
        title: t("common.exportFailed"),
      });
    },
  });

  const aiSettingMutation = useMutation({
    mutationFn: async (variables: {
      committedName: string;
      identityEpoch: number;
      name: string;
      setting: string;
      sourceKey: string;
      wasCreating: boolean;
    }) => {
      if (!variables.wasCreating && variables.sourceKey) {
        await discardAutoSaveRef.current(variables.sourceKey);
      }
      return generateCharacterSetting({ name: variables.name, setting: variables.setting });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.aiFallback"),
        title: t("character.action.aiWrite"),
      });
    },
    onSettled() {
      pendingAiActionsRef.current = Math.max(0, pendingAiActionsRef.current - 1);
    },
    onSuccess(result, variables) {
      if (result.ok === false) {
        showToast({
          kind: "error",
          message: result.message,
          title: t("character.action.aiWrite"),
        });
        return;
      }
      const isDeleted =
        (variables.sourceKey && deletedCharacterKeysRef.current.has(variables.sourceKey)) ||
        (variables.committedName && deletedCharacterKeysRef.current.has(`name:${variables.committedName}`));
      if (
        !variables.wasCreating &&
        variables.committedName &&
        variables.committedName === variables.name &&
        !isDeleted &&
        identityMutationEpochRef.current === variables.identityEpoch
      ) {
        queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
          current.map((item) => {
            const itemKey = item.id || `name:${item.name}`;
            if (itemKey !== variables.sourceKey && item.name !== variables.committedName) {
              return item;
            }
            return {
              ...item,
              character_brief: result.characterBrief ?? item.character_brief ?? "",
              character_setting: result.characterSetting,
            };
          }),
        );
      }
      const stillActive =
        isCreatingRef.current === variables.wasCreating &&
        (variables.wasCreating || activeCharacterKeyRef.current === variables.sourceKey);
      if (stillActive) {
        setDraft((current) => ({
          ...current,
          character_brief: result.characterBrief ?? current.character_brief ?? "",
          character_setting: result.characterSetting,
        }));
      }
      showToast({ kind: "success", message: result.message, title: t("character.action.aiWrite") });
    },
  });

  const aiBriefMutation = useMutation({
    mutationFn: async (variables: { name: string; setting: string; sourceKey: string; wasCreating: boolean }) => {
      if (!variables.wasCreating && variables.sourceKey) {
        await discardAutoSaveRef.current(variables.sourceKey);
      }
      return generateCharacterBrief({ name: variables.name, setting: variables.setting });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.aiFallback"),
        title: t("character.action.aiBrief"),
      });
    },
    onSettled() {
      pendingAiActionsRef.current = Math.max(0, pendingAiActionsRef.current - 1);
    },
    onSuccess(result, variables) {
      const stillActive =
        isCreatingRef.current === variables.wasCreating &&
        (variables.wasCreating || activeCharacterKeyRef.current === variables.sourceKey);
      if (stillActive) {
        update("character_brief", result.characterBrief);
      }
      showToast({ kind: "success", message: result.message, title: t("character.action.aiBrief") });
    },
  });

  const translateMutation = useMutation({
    mutationFn: async (variables: {
      characterSetting: string;
      emotionTags: string;
      name: string;
      sourceKey: string;
      wasCreating: boolean;
    }) => {
      if (!variables.wasCreating && variables.sourceKey) {
        await discardAutoSaveRef.current(variables.sourceKey);
      }
      return translateCharacterFields({
        characterSetting: variables.characterSetting,
        emotionTags: variables.emotionTags,
        name: variables.name,
      });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.translateFallback"),
        title: t("character.action.aiTranslate"),
      });
    },
    onSettled() {
      pendingAiActionsRef.current = Math.max(0, pendingAiActionsRef.current - 1);
    },
    onSuccess(result, variables) {
      if (result.error) {
        showToast({ kind: "error", message: result.error, title: t("character.action.aiTranslate") });
        return;
      }
      const stillActive =
        isCreatingRef.current === variables.wasCreating &&
        (variables.wasCreating || activeCharacterKeyRef.current === variables.sourceKey);
      if (stillActive) {
        setDraft((current) => ({
          ...current,
          character_setting: result.characterSetting,
          emotion_tags: result.emotionTags,
          name: result.name,
        }));
        if (result.name.trim()) {
          setNameError("");
        }
      }
      showToast({ kind: "success", title: t("character.action.aiTranslate") });
    },
  });

  const voiceUploadMutation = useMutation({
    mutationFn: ({ index, voicePath, voiceText }: { index: number; voicePath: string; voiceText: string }) =>
      uploadSpriteVoice({
        name: currentCharacterName,
        spriteIndex: index,
        voicePath,
        voiceText,
        voiceType: spriteVoiceType(draft.sprites[index], draft),
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
        title: t("character.sprite.uploadVoice"),
      });
    },
    onSuccess(character, variables) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({
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
  });

  const voiceTextMutation = useMutation({
    mutationFn: ({ index, text }: { index: number; text: string }) =>
      saveSpriteVoiceText(currentCharacterName, index, text),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
        title: t("character.sprite.saveVoiceText"),
      });
    },
    onSuccess(character, variables) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => {
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
  });

  const voiceTypeMutation = useMutation({
    mutationFn: ({ index, voiceType: vt }: { index: number; voiceType: SpriteVoiceType }) =>
      saveSpriteVoiceType(currentCharacterName, index, vt),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
        title: t("character.sprite.voiceType"),
      });
    },
  });

  const voiceDeleteMutation = useMutation({
    mutationFn: ({ index, name }: { index: number; name: string }) => deleteSpriteVoice(name, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.voiceError"),
        title: t("character.sprite.deleteVoice"),
      });
    },
    onSuccess(character, variables) {
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({
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
  });

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
      const nextKey = character.id || `name:${character.name}`;
      activeCharacterKeyRef.current = nextKey;
      setSyncedCharacterKey(nextKey);
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        upsertCatalogCharacter(current, character, variables.originalName),
      );
      setIsCreating(false);
      setSpritePrefixTouched(false);
      setNameError("");
      setSpritePrefixError("");
      setSelectedName(character.name);
      setDraft((current) => ({
        ...structuredClone(character),
        sprites: mergeSprites(character.sprites, current),
      }));
      setPronunciationText(pronunciationMapToText(character.pronunciation_map));
      if (variables.saveFirst && variables.originalName && variables.originalName !== character.name) {
        void queryClient.invalidateQueries({ queryKey: ["knowledge", "binding-names"] });
      }
      showToast({ kind: "success", title: t("character.sprite.uploadImages") });
    },
  });

  const emotionTagsMutation = useMutation({
    mutationFn: (emotionTags: string) => saveCharacterEmotionTags(currentCharacterName, emotionTags),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.sprite.imageError"),
        title: t("character.sprite.saveTags"),
      });
    },
    onSuccess(character) {
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        upsertCatalogCharacter(current, character),
      );
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({ ...current, emotion_tags: character.emotion_tags }));
      showToast({ kind: "success", title: t("character.sprite.saveTags") });
    },
  });

  const autoLabelMutation = useMutation({
    mutationFn: () =>
      autoLabelCharacterSprites(currentCharacterName, {
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
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        current.map((item) => (item.name === currentCharacterName ? { ...item, emotion_tags: result.tags } : item)),
      );
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({ ...current, emotion_tags: result.tags }));
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
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        current.map((item) => (item.name === nextCharacter.name ? nextCharacter : item)),
      );
      setDraft((current) => ({
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
      queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      setDraft((current) => ({
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
        name: currentCharacterName,
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
      preserveImportedDraftRef.current = character;
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        upsertCatalogCharacter(current, character),
      );
      setDraft((current) => ({
        ...current,
        default_sprite_group: character.default_sprite_group,
        fallback_to_default_group: character.fallback_to_default_group,
        sprite_groups: character.sprite_groups,
        sprites: mergeSprites(character.sprites, current),
      }));
      showToast({ kind: "success", title: t("spriteGroup.savedToast") });
    },
  });

  const handleApplySpriteGroups = (patch: SpriteGroupsPatch) => {
    if (!isSavedCharacter) {
      setDraft((current) => {
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
  };

  const portraitCropMutation = useMutation({
    mutationFn: (nextCharacter: Character) => {
      const source = selected ? structuredClone(selected) : structuredClone(nextCharacter);
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
      preserveImportedDraftRef.current = character;
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        current.map((item) => (item.name === character.name ? character : item)),
      );
      setDraft((current) => ({
        ...current,
        portrait_crop: character.portrait_crop,
        sprites: current.sprites.map((sprite, index) => {
          const savedSprite = character.sprites.find((item) => item.path === sprite.path) ?? character.sprites[index];
          return savedSprite ? { ...sprite, portrait_crop: savedSprite.portrait_crop } : sprite;
        }),
      }));
      setPortraitCropOpen(false);
      showToast({ kind: "success", title: t("character.sprite.portraitCropSaved") });
    },
  });

  const handleSavePortraitCrop = (nextCharacter: Character) => {
    if (!isSavedCharacter) {
      setDraft((current) => ({
        ...current,
        portrait_crop: nextCharacter.portrait_crop,
        sprites: current.sprites.map((sprite, index) => ({
          ...sprite,
          portrait_crop: nextCharacter.sprites[index]?.portrait_crop,
        })),
      }));
      setPortraitCropOpen(false);
      showToast({ kind: "success", title: t("character.sprite.portraitCropSaved") });
      return;
    }
    portraitCropMutation.mutate(nextCharacter);
  };

  const update = <K extends keyof Character>(name: K, value: Character[K]) => {
    if (name === "sprite_prefix") {
      setSpritePrefixTouched(true);
      setSpritePrefixError("");
    }
    if (name === "name" && String(value).trim()) {
      setNameError("");
    }
    setDraft((current) => {
      const next = { ...current, [name]: value };
      if (name === "name" && inCreateMode && !spritePrefixTouched) {
        next.sprite_prefix = suggestUniqueSpritePrefix(String(value), existingPrefixes, "char");
      }
      return next;
    });
  };

  const updateSprite = (index: number, patch: Partial<Sprite>) => {
    setDraft((current) => {
      const sprites = [...current.sprites];
      sprites[index] = { ...sprites[index], ...patch };
      return { ...current, sprites };
    });
  };

  const characterHasGptSovitsModel = (character: Character) =>
    Boolean(character.gpt_model_path?.trim() && character.sovits_model_path?.trim());

  const spriteHasReferenceVoiceText = (sprite: Sprite | undefined) => Boolean(sprite?.voice_text?.trim());

  const defaultSpriteVoiceType = (sprite: Sprite | undefined, character: Character): SpriteVoiceType =>
    characterHasGptSovitsModel(character) && spriteHasReferenceVoiceText(sprite) ? "reference" : "fallback";

  const spriteVoiceType = (sprite: Sprite | undefined, character: Character): SpriteVoiceType =>
    sprite?.voice_type ?? defaultSpriteVoiceType(sprite, character);

  const updateSpriteTag = (index: number, value: string) => {
    setDraft((current) => {
      const tags = tagContents(current.emotion_tags, current.sprites.length);
      tags[index] = value;
      return { ...current, emotion_tags: numberedTags(TAG_PREFIX_SPRITE, tags) };
    });
  };

  const openBulkSpriteTagsDialog = () => {
    setBulkSpriteTagsDraft(draft.emotion_tags);
    setBulkSpriteTagsOpen(true);
  };

  const validateNonIdentityFields = useCallback(
    (candidate: Character): string[] => {
      const pathFields = [candidate.gpt_model_path, candidate.sovits_model_path, candidate.refer_audio_path]
        .filter(Boolean)
        .map(String);
      return [
        pathFields.some((path) => path.trim().startsWith('"') || path.trim().endsWith('"'))
          ? t("character.validation.noQuotedPaths")
          : "",
        candidate.gpt_model_path?.trim() && !candidate.gpt_model_path.trim().toLowerCase().endsWith(".ckpt")
          ? t("character.validation.gptModelExt")
          : "",
        candidate.sovits_model_path?.trim() && !candidate.sovits_model_path.trim().toLowerCase().endsWith(".pth")
          ? t("character.validation.sovitsModelExt")
          : "",
      ].filter(Boolean);
    },
    [t],
  );

  const selectedCharacterKey = selected ? selected.id || `name:${selected.name}` : "";
  const isDraftSynced = Boolean(selected && syncedCharacterKey === selectedCharacterKey);
  const lockedSelectedPersona = isSelfPersonaCharacter(selected);
  const nameDirty = Boolean(!inCreateMode && isDraftSynced && !lockedSelectedPersona && draft.name !== selected!.name);
  const spritePrefixDirty = Boolean(
    !inCreateMode && isDraftSynced && !lockedSelectedPersona && draft.sprite_prefix !== selected!.sprite_prefix,
  );

  const liveNameError = useMemo(() => {
    if (!nameDirty || !selected) {
      return nameError;
    }
    const trimmed = draft.name.trim();
    if (!trimmed) {
      return t("character.validation.nameRequired");
    }
    const duplicate =
      trimmed === SELF_PERSONA_NAME ||
      data.some(
        (item) =>
          item !== selected &&
          (selected.id ? item.id !== selected.id : item.name !== selected.name) &&
          item.name.trim().toLowerCase() === trimmed.toLowerCase(),
      );
    return duplicate ? t("identity.error.duplicateName", { name: trimmed }) : "";
  }, [data, draft.name, nameDirty, nameError, selected, t]);

  const liveSpritePrefixError = useMemo(() => {
    if (!spritePrefixDirty || !selected) {
      return spritePrefixError;
    }
    const trimmed = draft.sprite_prefix.trim();
    if (!trimmed) {
      return t("character.validation.spritePrefixRequired");
    }
    if (!/^[\x00-\x7F]+$/.test(trimmed)) {
      return t("character.validation.spritePrefixAscii");
    }
    const duplicate =
      trimmed.toLowerCase() === SELF_PERSONA_SPRITE_PREFIX ||
      data.some(
        (item) =>
          item !== selected &&
          (selected.id ? item.id !== selected.id : item.name !== selected.name) &&
          item.sprite_prefix.trim().toLowerCase() === trimmed.toLowerCase(),
      );
    return duplicate ? t("identity.error.duplicatePrefix", { prefix: trimmed }) : "";
  }, [data, draft.sprite_prefix, selected, spritePrefixDirty, spritePrefixError, t]);

  const currentPronunciationMap = useMemo(() => pronunciationTextToMap(pronunciationText), [pronunciationText]);
  const baselineAutoSaveKey = useMemo(() => (selected ? serializeCharacterNonIdentity(selected) : ""), [selected]);
  const currentAutoSaveKey = useMemo(
    () => (selected ? serializeCharacterNonIdentity(draft, currentPronunciationMap) : ""),
    [currentPronunciationMap, draft, selected],
  );

  const resolveLatestSelectedCharacter = useCallback((): Character | undefined => {
    if (!selected) {
      return undefined;
    }
    const catalog = queryClient.getQueryData<Character[]>(charactersQueryKey) ?? data;
    return (
      (selected.id ? catalog.find((item) => item.id === selected.id) : undefined) ??
      catalog.find((item) => item.name === selected.name) ??
      selected
    );
  }, [data, queryClient, selected]);

  const autoSave = useDebouncedAutoSave<{ character: Character; originalName: string }>({
    baselineKey: baselineAutoSaveKey,
    buildPayload: () => {
      const latestSelected = resolveLatestSelectedCharacter() ?? selected!;
      return {
        character: buildCommittedCharacterPayload(draft, currentPronunciationMap, latestSelected),
        originalName: latestSelected.name,
      };
    },
    currentKey: currentAutoSaveKey,
    enabled: Boolean(
      !inCreateMode &&
      isDraftSynced &&
      identitySavingField === null &&
      !identityMutation.isPending &&
      !saveMutation.isPending &&
      !deleteMutation.isPending &&
      !aiSettingMutation.isPending &&
      !aiBriefMutation.isPending &&
      !translateMutation.isPending &&
      !spriteGenerationOpen &&
      !portraitCropOpen &&
      !bulkSpriteTagsOpen &&
      !smartGroupOpen &&
      !pendingDelete,
    ),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    async onSave({ character, originalName }, { isSuperseded, resetKey }) {
      const saved = await saveCharacter(character, originalName);
      if (
        isSuperseded() ||
        deletedCharacterKeysRef.current.has(resetKey) ||
        deletedCharacterKeysRef.current.has(`name:${originalName}`)
      ) {
        return;
      }
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        upsertCatalogCharacter(current, saved, originalName),
      );
      if (saved.id && !isCreatingRef.current && activeCharacterKeyRef.current === resetKey) {
        activeCharacterKeyRef.current = saved.id;
        setSyncedCharacterKey(saved.id);
        setDraft((current) => (current.id ? current : { ...current, id: saved.id }));
      }
    },
    resetKey: selected ? selected.id || `name:${selected.name}` : "__creating__",
    validate: ({ character }) => {
      const errors = validateNonIdentityFields(character);
      return errors.length ? errors.join("\n") : null;
    },
  });
  cancelAutoSaveRef.current = autoSave.cancel;
  discardAutoSaveRef.current = autoSave.discardPending;

  const aiActionPending = aiSettingMutation.isPending || aiBriefMutation.isPending || translateMutation.isPending;
  const identityPending = identitySavingField !== null || identityMutation.isPending;

  const confirmIdentityField = (field: "name" | "sprite_prefix") => {
    if (
      !selected ||
      lockedSelectedPersona ||
      identityPending ||
      identityPendingRef.current ||
      aiActionPending ||
      pendingAiActionsRef.current > 0
    ) {
      return;
    }
    const fieldError = field === "name" ? liveNameError : liveSpritePrefixError;
    if (fieldError) {
      showToast({
        kind: "error",
        message: fieldError,
        title: t("common.validationFailed"),
      });
      return;
    }
    const nonIdentityErrors = validateNonIdentityFields(draft);
    if (nonIdentityErrors.length) {
      showToast({
        kind: "error",
        message: nonIdentityErrors.join("\n"),
        title: t("common.validationFailed"),
      });
      return;
    }
    autoSave.discardPending();
    const latestSelected = resolveLatestSelectedCharacter() ?? selected;
    identityPendingRef.current = true;
    identityMutationEpochRef.current += 1;
    setIdentitySavingField(field);
    identityMutation.mutate({
      character: buildCommittedCharacterPayload(draft, currentPronunciationMap, latestSelected, {
        name: field === "name" ? draft.name.trim() : latestSelected.name,
        sprite_prefix: field === "sprite_prefix" ? draft.sprite_prefix.trim() : latestSelected.sprite_prefix,
      }),
      field,
      originalName: latestSelected.name,
      sourceKey: selectedCharacterKey,
    });
  };

  const cancelIdentityField = (field: "name" | "sprite_prefix") => {
    if (!selected) {
      return;
    }
    if (field === "name") {
      setDraft((current) => ({ ...current, name: selected.name }));
      setNameError("");
    } else {
      setDraft((current) => ({ ...current, sprite_prefix: selected.sprite_prefix }));
      setSpritePrefixError("");
    }
  };

  const buildCharacterCreateInput = () => {
    const trimmedName = draft.name.trim();
    if (!trimmedName) {
      setNameError(t("character.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return null;
    }
    if (
      trimmedName === SELF_PERSONA_NAME ||
      data.some((item) => item.name.trim().toLowerCase() === trimmedName.toLowerCase())
    ) {
      const duplicateError = t("identity.error.duplicateName", { name: trimmedName });
      setNameError(duplicateError);
      showToast({
        kind: "error",
        message: duplicateError,
        title: t("common.validationFailed"),
      });
      return null;
    }
    const spritePrefix = draft.sprite_prefix.trim();
    const prefixError = !spritePrefix
      ? t("character.validation.spritePrefixRequired")
      : !/^[\x00-\x7F]+$/.test(spritePrefix)
        ? t("character.validation.spritePrefixAscii")
        : spritePrefix.toLowerCase() === SELF_PERSONA_SPRITE_PREFIX ||
            data.some((item) => item.sprite_prefix.trim().toLowerCase() === spritePrefix.toLowerCase())
          ? t("identity.error.duplicatePrefix", { prefix: spritePrefix })
          : "";
    if (prefixError) {
      setSpritePrefixError(prefixError);
    }
    const validationMessages = [prefixError, ...validateNonIdentityFields(draft)].filter(Boolean);
    if (validationMessages.length) {
      showToast({
        kind: "error",
        message: validationMessages.join("\n"),
        title: t("common.validationFailed"),
      });
      return null;
    }
    return {
      character: buildNewCharacterPayload(draft, currentPronunciationMap, {
        name: trimmedName,
        sprite_prefix: spritePrefix,
      }),
      originalName: undefined,
    };
  };

  const saveDraft = () => {
    const input = buildCharacterCreateInput();
    if (!input) {
      return;
    }
    saveMutation.mutate(input);
  };

  const spriteTags = useMemo(
    () => tagContents(draft.emotion_tags, draft.sprites.length),
    [draft.emotion_tags, draft.sprites.length],
  );
  const selectedSprite = draft.sprites[selectedSpriteIndex];
  const selectedSpriteTag = spriteTags[selectedSpriteIndex] ?? "";
  const spriteGalleryItems = useMemo(
    () =>
      draft.sprites.map((sprite, index) => ({
        badge: sprite.voice_path ? t("character.sprite.hasVoice") : t("character.sprite.noVoice"),
        badgeTone: sprite.voice_path ? ("default" as const) : ("muted" as const),
        cornerLabel: sprite.mouth_sync ? t("spriteMouth.tab") : undefined,
        id: `${sprite.path}-${index}`,
        imageSrc: sprite.path && !isVideoMedia(sprite.path) ? fileUrl(sprite.path) : "",
        videoSrc: isVideoMedia(sprite.path) ? fileUrl(sprite.path) : undefined,
        meta: spriteTags[index] || sprite.voice_text || "",
        title: baseName(sprite.path) || `${index + 1}`,
      })),
    [draft.sprites, spriteTags, t],
  );
  const characterSectionNavItems = [
    { id: "character-basic", label: t("character.section.basic") },
    { id: "character-personality", label: t("character.section.personality") },
    { id: "character-voice", label: t("character.section.voice") },
    { id: "character-sprites", label: t("character.section.sprites") },
    { id: "character-memory", label: t("character.memory.section") },
    { id: "character-relations", label: t("relation.title") },
  ];

  const confirmPendingResourceDelete = async () => {
    if (!pendingResourceDelete) {
      return;
    }
    const target = pendingResourceDelete;
    setPendingResourceDelete(null);
    if (target.kind === "memory") {
      await memoryController.deleteMemory({ memoryId: target.memoryId, name: target.characterName });
      return;
    }
    if (target.kind === "sprite") {
      spriteDeleteMutation.mutate({ draft: structuredClone(draft), index: target.index, name: target.characterName });
      return;
    }
    if (target.kind === "all-sprites") {
      spriteDeleteAllMutation.mutate(target.characterName);
      return;
    }
    voiceDeleteMutation.mutate({ index: target.index, name: target.characterName });
  };

  const pendingResourceDeleteCopy = pendingResourceDelete
    ? {
        body:
          pendingResourceDelete.kind === "memory"
            ? t("character.memory.deleteConfirmBody", {
                memory: pendingResourceDelete.memory,
                name: pendingResourceDelete.characterName,
              })
            : pendingResourceDelete.kind === "sprite"
              ? t("character.sprite.deleteConfirmBody", {
                  filename: pendingResourceDelete.filename,
                  index: pendingResourceDelete.index + 1,
                  name: pendingResourceDelete.characterName,
                })
              : pendingResourceDelete.kind === "all-sprites"
                ? t("character.sprite.clearConfirmBody", {
                    count: pendingResourceDelete.count,
                    name: pendingResourceDelete.characterName,
                  })
                : t("character.sprite.deleteVoiceConfirmBody", {
                    filename: pendingResourceDelete.filename,
                    index: pendingResourceDelete.index + 1,
                  }),
        confirmLabel:
          pendingResourceDelete.kind === "sprite" || pendingResourceDelete.kind === "sprite-voice"
            ? t("common.remove")
            : t("common.delete"),
        title:
          pendingResourceDelete.kind === "memory"
            ? t("character.memory.delete")
            : pendingResourceDelete.kind === "all-sprites"
              ? t("character.sprite.clear")
              : pendingResourceDelete.kind === "sprite-voice"
                ? t("character.sprite.deleteVoice")
                : t("common.remove"),
      }
    : null;

  const selectExistingCharacter = (name: string) => {
    autoSave.flush();
    isCreatingRef.current = false;
    setIsCreating(false);
    setSpritePrefixTouched(false);
    setNameError("");
    setSpritePrefixError("");
    setSelectedName(name);
  };

  const startCreatingCharacter = () => {
    autoSave.flush();
    previousSelectedNameRef.current = currentCharacterName || data[0]?.name || "";
    activeCharacterKeyRef.current = "";
    isCreatingRef.current = true;
    setIsCreating(true);
    setSpritePrefixTouched(false);
    setSelectedName("");
    setDraft(createCharacter(existingPrefixes));
    setPronunciationText("");
    setPendingVoicePaths({});
    setSelectedSpriteIndex(0);
    setActiveSpriteGroup("__all__");
    setSmartGroupOpen(false);
    setNameError("");
    setSpritePrefixError("");
  };

  const cancelCreatingCharacter = () => {
    if (!data.length) {
      return;
    }
    const targetName =
      (previousSelectedNameRef.current && data.some((item) => item.name === previousSelectedNameRef.current)
        ? previousSelectedNameRef.current
        : data[0]?.name) || "";
    activeCharacterKeyRef.current = "";
    isCreatingRef.current = false;
    setIsCreating(false);
    setSpritePrefixTouched(false);
    setNameError("");
    setSpritePrefixError("");
    setSelectedName(targetName);
  };

  const exportCurrentCharacter = () => {
    if (!currentCharacterName) {
      showToast({
        kind: "error",
        message: t("character.validation.nameRequired"),
        title: t("common.export"),
      });
      return;
    }
    exportMutation.mutate(currentCharacterName);
  };

  const requestCharacterDelete = () => {
    if (isSelfPersonaCharacter(draft)) {
      return;
    }
    if (!currentCharacterName) {
      showToast({
        kind: "error",
        message: t("character.validation.nameRequired"),
        title: t("common.delete"),
      });
      return;
    }
    setPendingDelete(currentCharacterName);
  };

  const generateSetting = () => {
    if (identityPending || identityPendingRef.current || aiSettingMutation.isPending) {
      return;
    }
    if (!draft.name.trim()) {
      setNameError(t("character.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return;
    }
    pendingAiActionsRef.current += 1;
    aiSettingMutation.mutate({
      committedName: !inCreateMode && selected ? selected.name : "",
      identityEpoch: identityMutationEpochRef.current,
      name: draft.name.trim(),
      setting: draft.character_setting,
      sourceKey: selectedCharacterKey,
      wasCreating: inCreateMode,
    });
  };

  const generateBrief = () => {
    if (identityPending || identityPendingRef.current || aiBriefMutation.isPending) {
      return;
    }
    if (!draft.name.trim() || !draft.character_setting.trim()) {
      showToast({
        kind: "error",
        message: t("character.validation.briefSourceRequired"),
        title: t("common.validationFailed"),
      });
      return;
    }
    pendingAiActionsRef.current += 1;
    aiBriefMutation.mutate({
      name: draft.name.trim(),
      setting: draft.character_setting,
      sourceKey: selectedCharacterKey,
      wasCreating: inCreateMode,
    });
  };

  const translateDraft = () => {
    if (identityPending || identityPendingRef.current || translateMutation.isPending) {
      return;
    }
    if (!draft.name.trim() && !draft.character_setting.trim() && !draft.emotion_tags.trim()) {
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return;
    }
    pendingAiActionsRef.current += 1;
    translateMutation.mutate({
      characterSetting: draft.character_setting,
      emotionTags: draft.emotion_tags,
      name: draft.name,
      sourceKey: selectedCharacterKey,
      wasCreating: inCreateMode,
    });
  };

  const uploadSprites = (paths: string[]) => {
    if (!paths.length) {
      return;
    }
    const group =
      activeSpriteGroup !== "__all__" && activeSpriteGroup !== DEFAULT_SPRITE_GROUP ? activeSpriteGroup : undefined;
    if (!isSavedCharacter || !selected) {
      const input = buildCharacterCreateInput();
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
      character: selected,
      emotionTags: draft.emotion_tags,
      group,
      originalName: selected.name,
      paths,
      saveFirst: false,
    });
  };

  const requestClearSprites = () => {
    if (!isSavedCharacter || !draft.sprites.length) {
      showToast({ kind: "error", title: t("character.sprite.clear") });
      return;
    }
    setPendingResourceDelete({
      characterName: currentCharacterName,
      count: draft.sprites.length,
      kind: "all-sprites",
    });
  };

  const saveSpriteTags = () => {
    if (!isSavedCharacter || !draft.emotion_tags) {
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("character.sprite.saveTags"),
      });
      return;
    }
    emotionTagsMutation.mutate(draft.emotion_tags);
  };

  const updatePendingVoicePath = (path: string) => {
    setPendingVoicePaths((current) => ({ ...current, [selectedSpriteIndex]: path }));
  };

  const saveSelectedSpriteVoiceText = (text: string) => {
    const savedText = selected?.sprites[selectedSpriteIndex]?.voice_text ?? "";
    if (currentCharacterName && text !== savedText && !voiceTextMutation.isPending) {
      voiceTextMutation.mutate({ index: selectedSpriteIndex, text });
    }
  };

  const handleSpriteVoiceTypeChange = (value: SpriteVoiceType) => {
    updateSprite(selectedSpriteIndex, { voice_type: value });
    if (isSavedCharacter) {
      voiceTypeMutation.mutate({ index: selectedSpriteIndex, voiceType: value });
    }
  };

  const uploadSelectedSpriteVoice = () => {
    const voicePath = pendingVoicePaths[selectedSpriteIndex]?.trim() ?? "";
    if (!isSavedCharacter) {
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
  };

  const requestSelectedSpriteVoiceDelete = () => {
    if (!currentCharacterName || !selectedSprite?.voice_path) {
      showToast({ kind: "error", title: t("character.sprite.deleteVoice") });
      return;
    }
    setPendingResourceDelete({
      characterName: currentCharacterName,
      filename: baseName(selectedSprite.path) || `${selectedSpriteIndex + 1}`,
      index: selectedSpriteIndex,
      kind: "sprite-voice",
    });
  };

  const requestSelectedSpriteDelete = () => {
    if (!currentCharacterName || !selectedSprite) {
      showToast({ kind: "error", title: t("common.remove") });
      return;
    }
    setPendingResourceDelete({
      characterName: currentCharacterName,
      filename: baseName(selectedSprite.path) || `${selectedSpriteIndex + 1}`,
      index: selectedSpriteIndex,
      kind: "sprite",
    });
  };

  const requestMemoryDelete = (memory: { id: string; memory: string }) => {
    setPendingResourceDelete({
      characterName: memoryName,
      kind: "memory",
      memory: memory.memory,
      memoryId: memory.id,
    });
  };

  const confirmBulkSpriteTags = () => {
    const nextTags = bulkSpriteTagsDraft;
    update("emotion_tags", nextTags);
    setBulkSpriteTagsOpen(false);
    if (isSavedCharacter && nextTags.trim() && !emotionTagsMutation.isPending) {
      emotionTagsMutation.mutate(nextTags);
    }
  };

  if (spriteGenerationOpen) {
    return (
      <SpriteGenerationPage
        character={draft}
        name={currentCharacterName}
        onClose={() => setSpriteGenerationOpen(false)}
        onImported={(character, replacedIndex) => {
          // Updating the resource collection must not discard unsaved personality or tag edits.
          preserveImportedDraftRef.current = character;
          queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
            current.map((item) => (item.name === character.name ? character : item)),
          );
          setDraft((current) => {
            const currentSpritesByPath = new Map(current.sprites.map((sprite) => [sprite.path, sprite]));
            const replacedIndices =
              replacedIndex === undefined ? [] : Array.isArray(replacedIndex) ? replacedIndex : [replacedIndex];
            for (const index of replacedIndices) {
              if (current.sprites[index] && character.sprites[index]) {
                const path = character.sprites[index].path;
                currentSpritesByPath.set(path, { ...current.sprites[index], path });
              }
            }
            const currentTags = tagContents(current.emotion_tags, current.sprites.length);
            const tagsByPath = new Map(current.sprites.map((sprite, index) => [sprite.path, currentTags[index]]));
            const savedTags = tagContents(character.emotion_tags, character.sprites.length);
            return {
              ...current,
              default_sprite_group: character.default_sprite_group ?? current.default_sprite_group,
              fallback_to_default_group: character.fallback_to_default_group ?? current.fallback_to_default_group,
              sprite_groups: character.sprite_groups ?? current.sprite_groups,
              sprites: character.sprites.map((sprite) => {
                const draft = currentSpritesByPath.get(sprite.path);
                return draft ? { ...draft, group: sprite.group ?? draft.group, mouth_sync: sprite.mouth_sync } : sprite;
              }),
              sprite_transitions: character.sprite_transitions,
              emotion_tags: numberedTags(
                TAG_PREFIX_SPRITE,
                character.sprites.map((sprite, index) => tagsByPath.get(sprite.path) ?? savedTags[index]),
              ),
            };
          });
          showToast({
            kind: "success",
            title: t(replacedIndex === undefined ? "spriteGeneration.saved" : "spriteGeneration.replaced"),
          });
        }}
      />
    );
  }

  return (
    <div className="page character-page">
      <CharacterPageHeader
        autoSaveError={autoSave.errorMessage}
        autoSavePhase={autoSave.phase}
        canCancelCreate={isCreating && data.length > 0}
        characters={data}
        exportPending={exportMutation.isPending}
        importPending={importMutation.isPending}
        isCreating={isCreating}
        isLoading={isLoading}
        onCancelCreate={cancelCreatingCharacter}
        onCreate={startCreatingCharacter}
        onExport={exportCurrentCharacter}
        onImport={(items) => importMutation.mutate(items)}
        onRetryAutoSave={autoSave.retry}
        onSave={saveDraft}
        onSelectCharacter={selectExistingCharacter}
        pendingIdentity={nameDirty || spritePrefixDirty}
        savePending={saveMutation.isPending}
        sectionNav={<PageSectionNav ariaLabel={t("character.title")} items={characterSectionNavItems} />}
        selectedName={selectedName}
      />

      <div className="settings-grid character-page__content">
        <div className="character-page__top-grid">
          <CharacterBasicSection
            colorPickerValue={colorPickerValue}
            draft={draft}
            id="character-basic"
            identityConfirmDisabled={aiActionPending}
            identitySavingField={identitySavingField}
            nameDirty={nameDirty}
            nameError={liveNameError}
            onCancelName={() => cancelIdentityField("name")}
            onCancelSpritePrefix={() => cancelIdentityField("sprite_prefix")}
            onChange={update}
            onColorInputRef={setColorInputElement}
            onConfirmName={() => confirmIdentityField("name")}
            onConfirmSpritePrefix={() => confirmIdentityField("sprite_prefix")}
            onDelete={requestCharacterDelete}
            onPickColor={openColorPicker}
            onPronunciationTextChange={setPronunciationText}
            pronunciationText={pronunciationText}
            spritePrefixDirty={spritePrefixDirty}
            spritePrefixError={liveSpritePrefixError}
          />

          <CharacterPersonalitySection
            actionsDisabled={identityPending}
            aiPending={aiSettingMutation.isPending}
            briefPending={aiBriefMutation.isPending}
            draft={draft}
            id="character-personality"
            onAiBrief={generateBrief}
            onAiWrite={generateSetting}
            onChange={update}
            onTranslate={translateDraft}
            translatePending={translateMutation.isPending}
          />
        </div>

        <CharacterVoiceSection
          draft={draft}
          id="character-voice"
          onChange={update}
          voiceReferenceReadOnly={voiceReferenceReadOnly}
        />

        <ModelStateEditor
          character={draft}
          onChange={setDraft}
          onSaved={(character) => {
            queryClient.setQueryData<Character[]>(charactersQueryKey, (current = [character]) =>
              upsertCatalogCharacter(current, character),
            );
            setDraft((current) => ({
              ...current,
              ...(character.id ? { id: character.id } : {}),
              avatar_type: character.avatar_type,
              avatars: character.avatars,
            }));
          }}
        />

        {draft.avatar_type === "static" && (
          <CharacterSpritesSection
            activeSpriteGroup={activeSpriteGroup}
            generateDisabled={!isSavedCharacter || !draft.character_setting.trim()}
            generateHint={
              !isSavedCharacter
                ? t("spriteGeneration.saveFirst")
                : !draft.character_setting.trim()
                  ? t("spriteGeneration.settingRequired")
                  : undefined
            }
            isSavedCharacter={isSavedCharacter}
            onActiveSpriteGroupChange={setActiveSpriteGroup}
            onApplySpriteGroups={handleApplySpriteGroups}
            onGenerate={() => {
              const element = document.querySelector<HTMLElement>(".content-outlet");
              generationReturnRef.current = { element, scrollTop: element?.scrollTop ?? 0 };
              setSpriteGenerationOpen(true);
            }}
            onOpenSmartGroup={() => setSmartGroupOpen(true)}
            autoLabelAvailable={visionAvailable}
            autoLabelDisabled={!isSavedCharacter || !draft.sprites.length || !spriteTags.some((tag) => !tag.trim())}
            autoLabelPending={autoLabelMutation.isPending}
            draft={draft}
            emotionTagsPending={emotionTagsMutation.isPending}
            id="character-sprites"
            onClearSprites={requestClearSprites}
            onAutoLabel={() => {
              setAutoLabelTask(null);
              setAutoLabelDialogOpen(true);
              autoLabelMutation.mutate();
            }}
            onOpenBulkTags={openBulkSpriteTagsDialog}
            onOpenPortraitCrop={() => {
              portraitCropMutation.reset();
              setPortraitCropOpen(true);
            }}
            onPendingVoicePathChange={updatePendingVoicePath}
            onSaveTags={saveSpriteTags}
            onSelectSprite={setSelectedSpriteIndex}
            onSpriteDelete={requestSelectedSpriteDelete}
            onSpriteTagChange={(value) => updateSpriteTag(selectedSpriteIndex, value)}
            onSpriteUpload={uploadSprites}
            onSpriteVoiceDelete={requestSelectedSpriteVoiceDelete}
            onSpriteVoiceTextBlur={saveSelectedSpriteVoiceText}
            onSpriteVoiceTextChange={(value) => updateSprite(selectedSpriteIndex, { voice_text: value })}
            onSpriteVoiceUpload={uploadSelectedSpriteVoice}
            onSpriteVoiceTypeChange={handleSpriteVoiceTypeChange}
            pendingVoicePath={pendingVoicePaths[selectedSpriteIndex] ?? ""}
            selectedSprite={
              selectedSprite ? { ...selectedSprite, voice_type: spriteVoiceType(selectedSprite, draft) } : undefined
            }
            selectedSpriteIndex={selectedSpriteIndex}
            selectedSpriteTag={selectedSpriteTag}
            spriteDeletePending={spriteDeleteMutation.isPending}
            spriteGalleryItems={spriteGalleryItems}
            spriteGroupsPending={spriteGroupsMutation.isPending}
            spriteUploadPending={spriteUploadMutation.isPending}
            voiceDeletePending={voiceDeleteMutation.isPending}
            voiceUploadPending={voiceUploadMutation.isPending}
          />
        )}

        <CharacterMemorySection
          addAsCanon={memoryController.addAsCanon}
          addPending={memoryController.addPending}
          awakenPending={memoryController.awakenPending}
          data={memoryController.data}
          deletePending={memoryController.deletePending}
          depError={memoryController.depError}
          depInstalling={memoryController.depInstalling}
          error={memoryController.error}
          id="character-memory"
          isChecking={memoryController.isChecking}
          isError={memoryController.isError}
          isFetched={memoryController.isFetched}
          isFetching={memoryController.isFetching}
          isLoading={memoryController.isLoading}
          memoryInput={memoryController.memoryInput}
          memoryImportPending={memoryImportController.previewPending || memoryImportController.importPending}
          memoryName={memoryName}
          memoryPage={memoryController.memoryPage}
          memoryTotalPages={memoryController.memoryTotalPages}
          activeSearchQuery={memoryController.activeSearchQuery}
          onAddAsCanonChange={memoryController.setAddAsCanon}
          onAddMemory={() => void memoryController.add()}
          onAwakenMemory={(memory) => void memoryController.awakenMemory({ memoryId: memory.id, name: memoryName })}
          onClearSearch={memoryController.clearSearch}
          onDeleteMemory={requestMemoryDelete}
          onInstallDep={() => void memoryController.installDependency()}
          onImportMemories={() => void memoryImportController.openPicker()}
          onMemoryInputChange={memoryController.setMemoryInput}
          onMemoryPageChange={memoryController.setMemoryPage}
          onPinMemory={(memory, pinned) =>
            void memoryController.pinMemory({ memoryId: memory.id, name: memoryName, pinned })
          }
          onRefresh={() => void memoryController.refresh()}
          onSearch={() => void memoryController.search()}
          onSearchInputChange={memoryController.setSearchInput}
          pinPending={memoryController.pinPending}
          searchInput={memoryController.searchInput}
          searchPending={memoryController.searchPending}
        />

        <CharacterRelationSection
          key={currentCharacterName || "new"}
          primary={isSavedCharacter ? currentCharacterName : ""}
        />
      </div>

      <SpriteTagsDialog
        draft={bulkSpriteTagsDraft}
        onChange={setBulkSpriteTagsDraft}
        onClose={() => setBulkSpriteTagsOpen(false)}
        onConfirm={confirmBulkSpriteTags}
        open={bulkSpriteTagsOpen}
      />

      <SmartOutfitGroupDialog
        characterName={currentCharacterName}
        onApplied={(character, groupCount) => {
          preserveImportedDraftRef.current = character;
          queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
            upsertCatalogCharacter(current, character),
          );
          setDraft((current) => ({
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
        }}
        onClose={() => setSmartGroupOpen(false)}
        open={smartGroupOpen}
        sprites={draft.sprites}
      />

      <PortraitCropDialog
        character={draft}
        error={
          portraitCropMutation.isError
            ? portraitCropMutation.error instanceof Error
              ? portraitCropMutation.error.message
              : String(portraitCropMutation.error)
            : undefined
        }
        initialSpriteIndex={selectedSpriteIndex}
        onClose={() => setPortraitCropOpen(false)}
        onSave={handleSavePortraitCrop}
        open={portraitCropOpen}
        saving={portraitCropMutation.isPending}
      />

      <AlertDialog
        body={t("character.delete.confirmBody", { name: pendingDelete ?? "" })}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("common.delete")}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && deleteMutation.mutate(pendingDelete)}
        open={Boolean(pendingDelete)}
        title={t("character.delete.confirmTitle")}
      />
      <AlertDialog
        body={pendingResourceDeleteCopy?.body ?? ""}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={pendingResourceDeleteCopy?.confirmLabel ?? t("common.delete")}
        onCancel={() => setPendingResourceDelete(null)}
        onConfirm={confirmPendingResourceDelete}
        open={Boolean(pendingResourceDelete)}
        title={pendingResourceDeleteCopy?.title ?? t("common.delete")}
      />

      <CharacterMemoryDialogs
        depInstalling={memoryController.depInstalling}
        dependencyOpen={memoryController.dependencyDialogOpen}
        dependencyTask={memoryController.dependencyTask}
        loadingMessage={memoryController.loadingMessage}
        loadingOpen={memoryController.loadingDialogOpen}
        loadingTask={memoryController.loadingTask}
        onCloseDependency={memoryController.closeDependencyDialog}
        onCloseLoading={memoryController.closeLoadingDialog}
      />
      <CharacterMemoryImportDialogs
        importPending={memoryImportController.importPending}
        onClosePicker={memoryImportController.closePicker}
        onClosePreview={memoryImportController.closePreview}
        onCloseTask={memoryImportController.closeTask}
        onConfirm={() => void memoryImportController.confirmImport()}
        onSelect={(items) => void memoryImportController.previewItems(items)}
        pickerOpen={memoryImportController.pickerOpen}
        preview={memoryImportController.preview}
        previewOpen={memoryImportController.previewOpen}
        result={memoryImportController.result}
        task={memoryImportController.task}
        taskOpen={memoryImportController.taskOpen}
      />
      <MediaAutoLabelProgressDialog
        onClose={() => setAutoLabelDialogOpen(false)}
        open={autoLabelDialogOpen}
        pending={autoLabelMutation.isPending}
        result={autoLabelMutation.data ?? null}
        task={autoLabelTask}
      />
    </div>
  );
}
