import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { configQueryKey, getAppConfig } from "../../../entities/config/repository";
import { charactersQueryKey, listCharacters } from "../../../entities/character/repository";
import type { Character } from "../../../entities/config/types";
import { suggestUniqueSpritePrefix } from "../../../shared/assets/spritePrefix";
import { useI18n } from "../../../shared/i18n";
import { useSectionBusyRegistry, useToast } from "../../../shared/ui";
import { useVisionAvailability } from "../../media-auto-label/useVisionAvailability";
import { mergeGeneratedSpritesIntoDraft, mergeSprites, type CharacterPageContext } from "../characterContext";
import {
  createCharacter,
  isSelfPersonaCharacter,
  pronunciationMapToText,
  upsertCatalogCharacter,
} from "../characterEditorUtils";
import { useCharacterAiSyncController } from "./useCharacterAiSyncController";
import { useCharacterCatalogMutations } from "./useCharacterCatalogMutations";
import { useCharacterIdentityAndAutoSave } from "./useCharacterIdentityAndAutoSave";

export type { CharacterPageContext } from "../characterContext";

export function useCharacterPageController(): CharacterPageContext {
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
  const [draft, setDraft] = useState<Character>(() => createCharacter());
  const [isCreating, setIsCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [spriteGenerationOpen, setSpriteGenerationOpen] = useState(false);
  const [spritePrefixTouched, setSpritePrefixTouched] = useState(false);
  const [spritePrefixError, setSpritePrefixError] = useState("");
  const [identitySavingField, setIdentitySavingField] = useState<"name" | "sprite_prefix" | null>(null);
  const [nameError, setNameError] = useState("");
  const [pronunciationText, setPronunciationText] = useState("");
  const [syncedCharacterKey, setSyncedCharacterKey] = useState("");

  const generationReturnRef = useRef<{ element: HTMLElement | null; scrollTop: number } | null>(null);
  const preserveImportedDraftRef = useRef<Character | null>(null);
  const previousSelectedNameRef = useRef("");
  const activeCharacterKeyRef = useRef("");
  const isCreatingRef = useRef(isCreating);
  isCreatingRef.current = isCreating;
  const deletedCharacterKeysRef = useRef<Set<string>>(new Set());
  const cancelAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const discardAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const identityPendingRef = useRef(false);
  const identityMutationEpochRef = useRef(0);

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

  const inCreateMode = isCreating || data.length === 0;
  const inCreateModeRef = useRef(inCreateMode);
  inCreateModeRef.current = inCreateMode;
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
      setNameError("");
      setSpritePrefixError("");
      setSpritePrefixTouched(false);
    } else if (selected.id) {
      setDraft((current) => (current.id ? current : { ...current, id: selected.id }));
    }
  }, [selected]);

  const { beginSectionBusy, busyCount, resumeRevision, setSectionBusy } = useSectionBusyRegistry({
    onBeforeBusy: () => discardAutoSaveRef.current(),
  });

  const invalidateCharacters = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: charactersQueryKey });
  }, [queryClient]);

  const upsertCharacterInCache = useCallback(
    (character: Character) => {
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        upsertCatalogCharacter(current, character),
      );
    },
    [queryClient],
  );

  const replaceCharacterInCache = useCallback(
    (character: Character) => {
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        current.map((item) => (item.name === character.name ? character : item)),
      );
    },
    [queryClient],
  );

  const preserveImportedDraft = useCallback((character: Character) => {
    preserveImportedDraftRef.current = character;
  }, []);

  const { deleteMutation, exportMutation, identityMutation, importMutation, saveMutation } =
    useCharacterCatalogMutations({
      activeCharacterKeyRef,
      cancelAutoSaveRef,
      data,
      deletedCharacterKeysRef,
      discardAutoSaveRef,
      identityMutationEpochRef,
      identityPendingRef,
      isCreatingRef,
      queryClient,
      setDraft,
      setIdentitySavingField,
      setIsCreating,
      setNameError,
      setPendingDelete,
      setPronunciationText,
      setSelectedName,
      setSpritePrefixError,
      setSpritePrefixTouched,
      setSyncedCharacterKey,
    });

  const applyUploadedCharacter = useCallback(
    (character: Character, options: { originalName?: string; saveFirst: boolean }) => {
      const nextKey = character.id || `name:${character.name}`;
      activeCharacterKeyRef.current = nextKey;
      setSyncedCharacterKey(nextKey);
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
        upsertCatalogCharacter(current, character, options.originalName),
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
      if (options.saveFirst && options.originalName && options.originalName !== character.name) {
        void queryClient.invalidateQueries({ queryKey: ["knowledge", "binding-names"] });
      }
    },
    [queryClient],
  );

  const syncModelStateCharacter = useCallback(
    (character: Character) => {
      queryClient.setQueryData<Character[]>(charactersQueryKey, (current = [character]) =>
        upsertCatalogCharacter(current, character),
      );
      setDraft((current) => ({
        ...current,
        ...(character.id ? { id: character.id } : {}),
        avatar_type: character.avatar_type,
        avatars: character.avatars,
      }));
    },
    [queryClient],
  );

  const handleSpriteGenerationImported = useCallback(
    (character: Character, replacedIndex?: number | number[]) => {
      preserveImportedDraftRef.current = character;
      replaceCharacterInCache(character);
      setDraft((current) => mergeGeneratedSpritesIntoDraft(current, character, replacedIndex));
      showToast({
        kind: "success",
        title: t(replacedIndex === undefined ? "spriteGeneration.saved" : "spriteGeneration.replaced"),
      });
    },
    [replaceCharacterInCache, showToast, t],
  );

  const openSpriteGeneration = useCallback(() => {
    const element = document.querySelector<HTMLElement>(".content-outlet");
    generationReturnRef.current = { element, scrollTop: element?.scrollTop ?? 0 };
    setSpriteGenerationOpen(true);
  }, []);

  const updateField = useCallback(
    <K extends keyof Character>(name: K, value: Character[K]) => {
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
    },
    [existingPrefixes, inCreateMode, spritePrefixTouched],
  );

  const selectedCharacterKey = selected ? selected.id || `name:${selected.name}` : "";
  const isDraftSynced = Boolean(selected && syncedCharacterKey === selectedCharacterKey);
  const lockedSelectedPersona = isSelfPersonaCharacter(selected);
  const nameDirty = Boolean(!inCreateMode && isDraftSynced && draft.name !== selected!.name);
  const spritePrefixDirty = Boolean(
    !inCreateMode && isDraftSynced && !lockedSelectedPersona && draft.sprite_prefix !== selected!.sprite_prefix,
  );

  const identityPending = identitySavingField !== null || identityMutation.isPending;
  const { aiActionPending, isSelectionActive, pendingAiActionsRef, syncGeneratedSetting, tryBeginAiAction } =
    useCharacterAiSyncController({
      activeCharacterKeyRef,
      deletedCharacterKeysRef,
      identityMutationEpochRef,
      identityPendingRef,
      inCreateModeRef,
      queryClient,
      setDraft,
    });

  const {
    autoSave,
    buildCharacterCreateInput,
    cancelIdentityField,
    confirmIdentityField,
    liveNameError,
    liveSpritePrefixError,
  } = useCharacterIdentityAndAutoSave({
    activeCharacterKeyRef,
    aiActionPending,
    busyResumeRevision: resumeRevision,
    busySectionsCount: busyCount,
    cancelAutoSaveRef,
    data,
    deletedCharacterKeysRef,
    deletePending: deleteMutation.isPending,
    discardAutoSaveRef,
    draft,
    identityMutation,
    identityMutationEpochRef,
    identityPendingRef,
    identitySavingField,
    inCreateMode,
    isCreatingRef,
    isDraftSynced,
    lockedSelectedPersona,
    nameDirty,
    nameError,
    pendingAiActionsRef,
    pendingDelete,
    pronunciationText,
    queryClient,
    savePending: saveMutation.isPending,
    selected,
    selectedCharacterKey,
    setDraft,
    setIdentitySavingField,
    setNameError,
    setSpritePrefixError,
    setSyncedCharacterKey,
    spriteGenerationOpen,
    spritePrefixDirty,
    spritePrefixError,
  });

  const saveDraft = useCallback(() => {
    const input = buildCharacterCreateInput();
    if (!input) {
      return;
    }
    saveMutation.mutate(input);
  }, [buildCharacterCreateInput, saveMutation]);

  const selectExistingCharacter = useCallback(
    (name: string) => {
      autoSave.flush();
      isCreatingRef.current = false;
      setIsCreating(false);
      setSpritePrefixTouched(false);
      setNameError("");
      setSpritePrefixError("");
      setSelectedName(name);
    },
    [autoSave],
  );

  const startCreatingCharacter = useCallback(() => {
    autoSave.flush();
    previousSelectedNameRef.current = currentCharacterName || data[0]?.name || "";
    activeCharacterKeyRef.current = "";
    isCreatingRef.current = true;
    setIsCreating(true);
    setSpritePrefixTouched(false);
    setSelectedName("");
    setDraft(createCharacter(existingPrefixes));
    setPronunciationText("");
    setNameError("");
    setSpritePrefixError("");
  }, [autoSave, currentCharacterName, data, existingPrefixes]);

  const cancelCreatingCharacter = useCallback(() => {
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
  }, [data]);

  const exportCurrentCharacter = useCallback(() => {
    if (!currentCharacterName) {
      showToast({
        kind: "error",
        message: t("character.validation.nameRequired"),
        title: t("common.export"),
      });
      return;
    }
    exportMutation.mutate(currentCharacterName);
  }, [currentCharacterName, exportMutation, showToast, t]);

  const requestCharacterDelete = useCallback(() => {
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
  }, [currentCharacterName, draft, showToast, t]);

  const cancelDeleteCharacter = useCallback(() => {
    setPendingDelete(null);
  }, []);

  const confirmDeleteCharacter = useCallback(() => {
    if (pendingDelete) {
      deleteMutation.mutate(pendingDelete);
    }
  }, [deleteMutation, pendingDelete]);

  return {
    aiActionPending,
    applyUploadedCharacter,
    autoSaveError: autoSave.errorMessage,
    autoSavePhase: autoSave.phase,
    autoSaveRetry: autoSave.retry,
    buildCharacterCreateInput,
    cancelCreatingCharacter,
    cancelDeleteCharacter,
    cancelIdentityField,
    closeSpriteGeneration: () => setSpriteGenerationOpen(false),
    confirmDeleteCharacter,
    confirmIdentityField,
    currentCharacterName,
    data,
    draft,
    exportCurrentCharacter,
    exportPending: exportMutation.isPending,
    handleSpriteGenerationImported,
    identityPending,
    identitySavingField,
    importCharacters: (items: string[]) => importMutation.mutate(items),
    importPending: importMutation.isPending,
    inCreateMode,
    invalidateCharacters,
    isCreating,
    isLoading,
    isSavedCharacter,
    isSelectionActive,
    liveNameError,
    liveSpritePrefixError,
    nameDirty,
    openSpriteGeneration,
    patchDraft: setDraft,
    pendingDelete,
    preserveImportedDraft,
    pronunciationText,
    replaceCharacterInCache,
    requestCharacterDelete,
    saveDraft,
    savePending: saveMutation.isPending,
    selected,
    selectedCharacterKey,
    selectedName,
    beginSectionBusy,
    selectExistingCharacter,
    setNameError,
    setPronunciationText,
    setSectionBusy,
    spriteGenerationOpen,
    spritePrefixDirty,
    startCreatingCharacter,
    syncGeneratedSetting,
    syncModelStateCharacter,
    tryBeginAiAction,
    updateField,
    upsertCharacterInCache,
    visionAvailable,
    voiceReferenceReadOnly,
  };
}
