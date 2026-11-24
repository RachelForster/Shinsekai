import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { backgroundsQueryKey, listBackgrounds } from "../../../entities/background/repository";
import type { Background } from "../../../entities/config/types";
import { suggestUniqueSpritePrefix } from "../../../shared/assets/spritePrefix";
import { useI18n } from "../../../shared/i18n";
import { useSectionBusyRegistry, useToast } from "../../../shared/ui";
import { useVisionAvailability } from "../../media-auto-label/useVisionAvailability";
import type { BackgroundPageContext, BackgroundSyncOptions } from "../backgroundContext";
import { createBackground, upsertCatalogBackground } from "../backgroundUtils";
import { useBackgroundAutoSaveController } from "./useBackgroundAutoSaveController";
import { useBackgroundCatalogMutations } from "./useBackgroundCatalogMutations";

export type { BackgroundPageContext } from "../backgroundContext";

export function useBackgroundPageController(): BackgroundPageContext {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const visionAvailable = useVisionAvailability();
  const backgroundsQuery = useQuery({ queryFn: listBackgrounds, queryKey: backgroundsQueryKey });
  const data = backgroundsQuery.data ?? [];
  const isLoading = backgroundsQuery.isLoading;
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<Background>(() => createBackground());
  const [draftSourceName, setDraftSourceName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [pendingBackgroundDelete, setPendingBackgroundDelete] = useState<string | null>(null);
  const [nameError, setNameError] = useState("");
  const [spritePrefixError, setSpritePrefixError] = useState("");
  const [spritePrefixTouched, setSpritePrefixTouched] = useState(false);
  const [identitySavingField, setIdentitySavingField] = useState<"name" | "sprite_prefix" | null>(null);
  const [syncedBackgroundKey, setSyncedBackgroundKey] = useState("");
  const isCreatingRef = useRef(isCreating);
  isCreatingRef.current = isCreating;
  const deletedBackgroundKeysRef = useRef<Set<string>>(new Set());
  const cancelAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const discardAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const previousSelectedNameRef = useRef("");
  const activeBackgroundKeyRef = useRef("");

  const inCreateMode = isCreating || data.length === 0;
  const existingPrefixes = useMemo(() => data.map((bg) => bg.sprite_prefix), [data]);

  const selected = useMemo(() => {
    if (isCreating) {
      return undefined;
    }
    if (selectedName) {
      return data.find((bg) => bg.name === selectedName);
    }
    return data[0];
  }, [data, isCreating, selectedName]);
  const currentBackgroundName = isCreating ? "" : selected?.name || selectedName;
  const draftMatchesSelection = isCreating || !selected || draftSourceName === selected.name;
  const currentDraft = draftMatchesSelection ? draft : selected!;
  const isSavedBackground = Boolean(
    !isCreating && (selected || (currentBackgroundName && data.some((bg) => bg.name === currentBackgroundName))),
  );

  useEffect(() => {
    if (!selected) {
      activeBackgroundKeyRef.current = "";
      setSyncedBackgroundKey("");
      return;
    }
    const selectedKey = selected.id || `name:${selected.name}`;
    if (selectedKey !== activeBackgroundKeyRef.current) {
      activeBackgroundKeyRef.current = selectedKey;
      setSyncedBackgroundKey(selectedKey);
      setSelectedName(selected.name);
      setDraft(structuredClone(selected));
      setDraftSourceName(selected.name);
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

  const invalidateBackgrounds = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
  }, [queryClient]);

  const refetchBackgrounds = useCallback(() => {
    void backgroundsQuery.refetch();
  }, [backgroundsQuery]);

  const syncSavedBackground = useCallback(
    (
      background: Background,
      patchDraftFromBackground: (current: Background, saved: Background) => Background,
      options?: BackgroundSyncOptions,
    ) => {
      const mode = options?.mode ?? "upsert";
      if (mode === "upsert") {
        queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
          upsertCatalogBackground(current, background),
        );
      } else if (mode === "replace") {
        queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
          current.map((item) => (item.name === background.name ? background : item)),
        );
      }
      if (options?.invalidate !== false) {
        void queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      }
      setDraft((current) => patchDraftFromBackground(current, background));
    },
    [queryClient],
  );

  const { deleteMutation, exportMutation, identityMutation, importMutation, saveMutation } =
    useBackgroundCatalogMutations({
      activeBackgroundKeyRef,
      cancelAutoSaveRef,
      data,
      deletedBackgroundKeysRef,
      discardAutoSaveRef,
      isCreatingRef,
      queryClient,
      setDraft,
      setDraftSourceName,
      setIsCreating,
      setNameError,
      setSelectedName,
      setSpritePrefixError,
      setSpritePrefixTouched,
      setSyncedBackgroundKey,
    });

  const updateField = useCallback(
    <K extends keyof Background>(name: K, value: Background[K]) => {
      if (name === "sprite_prefix") {
        setSpritePrefixTouched(true);
        setSpritePrefixError("");
      }
      if (name === "name" && String(value).trim()) {
        setNameError("");
      }
      setDraft((current) => {
        const baseDraft = draftMatchesSelection ? current : structuredClone(currentDraft);
        const next = { ...baseDraft, [name]: value };
        if (name === "name" && inCreateMode && !spritePrefixTouched) {
          next.sprite_prefix = suggestUniqueSpritePrefix(String(value), existingPrefixes, "bg");
        }
        return next;
      });
      setDraftSourceName(currentBackgroundName);
    },
    [currentBackgroundName, currentDraft, draftMatchesSelection, existingPrefixes, inCreateMode, spritePrefixTouched],
  );

  const patchActiveDraft = useCallback(
    (updater: (baseDraft: Background) => Background) => {
      setDraft((current) => updater(draftMatchesSelection ? current : currentDraft));
      setDraftSourceName(currentBackgroundName);
    },
    [currentBackgroundName, currentDraft, draftMatchesSelection],
  );

  const patchDraft = useCallback((updater: (current: Background) => Background) => {
    setDraft(updater);
  }, []);

  const selectedBackgroundKey = selected ? selected.id || `name:${selected.name}` : "";
  const isDraftSynced = Boolean(selected && syncedBackgroundKey === selectedBackgroundKey && draftMatchesSelection);
  const nameDirty = Boolean(!inCreateMode && isDraftSynced && currentDraft.name !== selected!.name);
  const spritePrefixDirty = Boolean(
    !inCreateMode && isDraftSynced && currentDraft.sprite_prefix !== selected!.sprite_prefix,
  );

  const {
    autoSave,
    buildBackgroundCreateInput,
    cancelIdentityField,
    confirmIdentityField,
    liveNameError,
    liveSpritePrefixError,
  } = useBackgroundAutoSaveController({
    activeBackgroundKeyRef,
    busyResumeRevision: resumeRevision,
    busySectionsCount: busyCount,
    cancelAutoSaveRef,
    currentDraft,
    data,
    deletedBackgroundKeysRef,
    deletePending: deleteMutation.isPending,
    discardAutoSaveRef,
    identityMutation,
    identitySavingField,
    inCreateMode,
    isCreatingRef,
    isDraftSynced,
    nameDirty,
    nameError,
    pendingBackgroundDelete,
    queryClient,
    savePending: saveMutation.isPending,
    selected,
    selectedBackgroundKey,
    setDraft,
    setIdentitySavingField,
    setNameError,
    setSpritePrefixError,
    setSyncedBackgroundKey,
    spritePrefixDirty,
    spritePrefixError,
  });

  const saveDraft = useCallback(() => {
    const input = buildBackgroundCreateInput();
    if (!input) {
      return;
    }
    saveMutation.mutate(input);
  }, [buildBackgroundCreateInput, saveMutation]);

  const saveBulkTags = useCallback(
    (field: "bg_tags" | "bgm_tags", nextTags: string) => {
      updateField(field, nextTags);
      if (selected && nextTags.trim() && !saveMutation.isPending) {
        saveMutation.mutate({
          background: {
            ...currentDraft,
            ...(selected.id ? { id: selected.id } : {}),
            [field]: nextTags,
            name: selected.name,
            sprite_prefix: selected.sprite_prefix,
          },
          originalName: selected.name,
        });
      }
    },
    [currentDraft, saveMutation, selected, updateField],
  );

  const selectBackground = useCallback(
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

  const startCreatingBackground = useCallback(() => {
    autoSave.flush();
    previousSelectedNameRef.current = currentBackgroundName || data[0]?.name || "";
    activeBackgroundKeyRef.current = "";
    isCreatingRef.current = true;
    setIsCreating(true);
    setSpritePrefixTouched(false);
    setSelectedName("");
    setDraft(createBackground(existingPrefixes));
    setDraftSourceName("");
    setNameError("");
    setSpritePrefixError("");
  }, [autoSave, currentBackgroundName, data, existingPrefixes]);

  const cancelCreatingBackground = useCallback(() => {
    if (!data.length) {
      return;
    }
    const targetName =
      (previousSelectedNameRef.current && data.some((item) => item.name === previousSelectedNameRef.current)
        ? previousSelectedNameRef.current
        : data[0]?.name) || "";
    activeBackgroundKeyRef.current = "";
    isCreatingRef.current = false;
    setIsCreating(false);
    setSpritePrefixTouched(false);
    setNameError("");
    setSpritePrefixError("");
    setSelectedName(targetName);
  }, [data]);

  const exportCurrentBackground = useCallback(() => {
    if (!currentBackgroundName) {
      showToast({
        kind: "error",
        message: t("background.validation.nameRequired"),
        title: t("common.export"),
      });
      return;
    }
    exportMutation.mutate(currentBackgroundName);
  }, [currentBackgroundName, exportMutation, showToast, t]);

  const requestDeleteBackground = useCallback(() => {
    if (!currentBackgroundName) {
      showToast({
        kind: "error",
        message: t("background.error.deleteFallback"),
        title: t("common.deleteFailed"),
      });
      return;
    }
    setPendingBackgroundDelete(currentBackgroundName);
  }, [currentBackgroundName, showToast, t]);

  const cancelDeleteBackground = useCallback(() => {
    setPendingBackgroundDelete(null);
  }, []);

  const confirmDeleteBackground = useCallback(() => {
    if (!pendingBackgroundDelete) {
      return;
    }
    const targetName = pendingBackgroundDelete;
    setPendingBackgroundDelete(null);
    deleteMutation.mutate(targetName);
  }, [deleteMutation, pendingBackgroundDelete]);

  return {
    autoSaveError: autoSave.errorMessage,
    autoSavePhase: autoSave.phase,
    autoSaveRetry: autoSave.retry,
    cancelCreatingBackground,
    cancelDeleteBackground,
    cancelIdentityField,
    confirmDeleteBackground,
    confirmIdentityField,
    currentBackgroundName,
    currentDraft,
    data,
    draftMatchesSelection,
    exportCurrentBackground,
    exportPending: exportMutation.isPending,
    identitySavingField,
    importBackgrounds: (paths: string[]) => importMutation.mutate(paths),
    importPending: importMutation.isPending,
    inCreateMode,
    invalidateBackgrounds,
    isCreating,
    isError: backgroundsQuery.isError,
    isLoading,
    isSavedBackground,
    liveNameError,
    liveSpritePrefixError,
    nameDirty,
    patchActiveDraft,
    patchDraft,
    pendingBackgroundDelete,
    queryError: backgroundsQuery.error,
    refetchBackgrounds,
    requestDeleteBackground,
    saveBulkTags,
    saveDraft,
    savePending: saveMutation.isPending,
    selected,
    selectedBackgroundKey,
    selectedName,
    beginSectionBusy,
    selectBackground,
    setNameError,
    setSectionBusy,
    spritePrefixDirty,
    startCreatingBackground,
    syncSavedBackground,
    updateField,
    visionAvailable,
  };
}
