import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { effectsQueryKey, listEffects, saveEffect } from "../../../entities/effect/repository";
import type { Effect } from "../../../entities/config/types";
import { isValidEffectStorageName } from "../../../shared/assets/spritePrefix";
import { useDebouncedAutoSave } from "../../../shared/hooks/useDebouncedAutoSave";
import { useI18n } from "../../../shared/i18n";
import { useToast, useSectionBusyRegistry } from "../../../shared/ui";
import type { EffectPageContext, EnsureSavedOptions } from "../effectContext";
import {
  buildCreateEffectPayload,
  createEffect,
  normalizeEffect,
  serializeEffectNonIdentity,
  upsertCatalogEffect,
} from "../effectDraft";
import { useEffectCatalogMutations } from "./useEffectCatalogMutations";

export type { EffectPageContext, EnsureSavedOptions } from "../effectContext";

export function useEffectPageController(): EffectPageContext {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const effectsQuery = useQuery({ queryFn: listEffects, queryKey: effectsQueryKey });
  const data = useMemo(() => (Array.isArray(effectsQuery.data) ? effectsQuery.data : []), [effectsQuery.data]);
  const isLoading = effectsQuery.isLoading;
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<Effect>(createEffect);
  const [isCreating, setIsCreating] = useState(false);
  const [pendingEffectDelete, setPendingEffectDelete] = useState<string | null>(null);
  const [nameError, setNameError] = useState("");
  const [syncedEffectKey, setSyncedEffectKey] = useState("");
  const isCreatingRef = useRef(isCreating);
  isCreatingRef.current = isCreating;
  const deletedEffectKeysRef = useRef<Set<string>>(new Set());
  const cancelAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const discardAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const previousSelectedNameRef = useRef("");
  const activeEffectKeyRef = useRef("");

  const inCreateMode = isCreating || data.length === 0;

  const selected = useMemo(() => {
    if (isCreating) {
      return undefined;
    }
    if (selectedName) {
      return data.find((ef) => ef.name === selectedName);
    }
    return data[0];
  }, [data, isCreating, selectedName]);
  const currentEffectName = isCreating ? "" : selected?.name || selectedName;

  useEffect(() => {
    if (!selected) {
      activeEffectKeyRef.current = "";
      setSyncedEffectKey("");
      return;
    }
    const selectedKey = selected.id || `name:${selected.name}`;
    if (selectedKey !== activeEffectKeyRef.current) {
      activeEffectKeyRef.current = selectedKey;
      setSyncedEffectKey(selectedKey);
      setSelectedName(selected.name);
      setDraft(normalizeEffect(structuredClone(selected)));
      setNameError("");
    } else if (selected.id) {
      setDraft((current) => (current.id ? current : { ...current, id: selected.id }));
    }
  }, [selected]);

  const { beginSectionBusy, busyCount, resumeRevision } = useSectionBusyRegistry({
    onBeforeBusy: () => discardAutoSaveRef.current(),
  });

  const invalidateEffects = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: effectsQueryKey });
  }, [queryClient]);

  const syncSavedEffect = useCallback(
    (
      effect: Effect,
      patchDraftFromEffect: (current: Effect, saved: Effect) => Effect,
      options?: { invalidate?: boolean },
    ) => {
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      if (options?.invalidate !== false) {
        void queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      }
      setDraft((current) => patchDraftFromEffect(current, effect));
    },
    [queryClient],
  );

  const { deleteMutation, exportMutation, identityMutation, importMutation, saveMutation } = useEffectCatalogMutations({
    activeEffectKeyRef,
    cancelAutoSaveRef,
    data,
    deletedEffectKeysRef,
    discardAutoSaveRef,
    isCreatingRef,
    queryClient,
    setDraft,
    setIsCreating,
    setNameError,
    setSelectedName,
    setSyncedEffectKey,
  });

  const updateField = useCallback(<K extends keyof Effect>(name: K, value: Effect[K]) => {
    setDraft((current) => ({ ...current, [name]: value }));
    if (name === "name" && String(value).trim()) {
      setNameError("");
    }
  }, []);

  const patchDraft = useCallback((updater: (current: Effect) => Effect) => {
    setDraft(updater);
  }, []);

  const selectedEffectKey = selected ? selected.id || `name:${selected.name}` : "";
  const isDraftSynced = Boolean(selected && syncedEffectKey === selectedEffectKey);
  const nameDirty = Boolean(!inCreateMode && isDraftSynced && draft.name !== selected!.name);
  const liveNameError = useMemo(() => {
    if (!nameDirty || !selected) {
      return nameError;
    }
    const trimmed = draft.name.trim();
    if (!trimmed) {
      return t("effect.validation.nameRequired");
    }
    if (!isValidEffectStorageName(trimmed)) {
      return t("identity.error.invalidEffectName");
    }
    const duplicate = data.some(
      (item) =>
        item !== selected &&
        (selected.id ? item.id !== selected.id : item.name !== selected.name) &&
        item.name.trim().toLowerCase() === trimmed.toLowerCase(),
    );
    return duplicate ? t("identity.error.duplicateName", { name: trimmed }) : "";
  }, [data, draft.name, nameDirty, nameError, selected, t]);

  const baselineAutoSaveKey = useMemo(() => (selected ? serializeEffectNonIdentity(selected) : ""), [selected]);
  const currentAutoSaveKey = useMemo(() => (selected ? serializeEffectNonIdentity(draft) : ""), [draft, selected]);

  const resolveLatestSelectedEffect = useCallback((): Effect | undefined => {
    if (!selected) {
      return undefined;
    }
    const catalog = queryClient.getQueryData<Effect[]>(effectsQueryKey) ?? data;
    return (
      (selected.id ? catalog.find((item) => item.id === selected.id) : undefined) ??
      catalog.find((item) => item.name === selected.name) ??
      selected
    );
  }, [data, queryClient, selected]);

  const autoSave = useDebouncedAutoSave<{ effect: Effect; originalName: string }>({
    baselineKey: baselineAutoSaveKey,
    buildPayload: () => {
      const latestSelected = resolveLatestSelectedEffect() ?? selected!;
      return {
        effect: {
          ...latestSelected,
          ...(latestSelected.id ? { id: latestSelected.id } : {}),
          ambient_layers: draft.ambient_layers,
          ambient_tags: draft.ambient_tags,
          audio_tags: draft.audio_tags,
          color: draft.color.trim() || "#5b8def",
          image_tags: draft.image_tags,
          name: latestSelected.name,
          prompt_text: draft.prompt_text,
        },
        originalName: latestSelected.name,
      };
    },
    currentKey: currentAutoSaveKey,
    enabled: Boolean(
      !inCreateMode &&
      isDraftSynced &&
      !identityMutation.isPending &&
      !saveMutation.isPending &&
      !deleteMutation.isPending &&
      busyCount === 0 &&
      !pendingEffectDelete,
    ),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    async onSave({ effect, originalName }, { isSuperseded, resetKey }) {
      const saved = await saveEffect(effect, originalName);
      if (
        isSuperseded() ||
        deletedEffectKeysRef.current.has(resetKey) ||
        deletedEffectKeysRef.current.has(`name:${originalName}`)
      ) {
        return;
      }
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) =>
        upsertCatalogEffect(current, saved, originalName),
      );
      if (saved.id && !isCreatingRef.current && activeEffectKeyRef.current === resetKey) {
        activeEffectKeyRef.current = saved.id;
        setSyncedEffectKey(saved.id);
        setDraft((current) => (current.id ? current : { ...current, id: saved.id }));
      }
    },
    rescheduleToken: resumeRevision,
    resetKey: selected ? selected.id || `name:${selected.name}` : "__creating__",
  });
  cancelAutoSaveRef.current = autoSave.cancel;
  discardAutoSaveRef.current = autoSave.discardPending;

  const confirmIdentityName = useCallback(() => {
    if (!selected || identityMutation.isPending) {
      return;
    }
    if (liveNameError) {
      showToast({
        kind: "error",
        message: liveNameError,
        title: t("common.validationFailed"),
      });
      return;
    }
    autoSave.discardPending();
    const latestSelected = resolveLatestSelectedEffect() ?? selected;
    identityMutation.mutate({
      effect: {
        ...latestSelected,
        ...(latestSelected.id ? { id: latestSelected.id } : {}),
        audio_tags: draft.audio_tags,
        color: draft.color.trim() || "#5b8def",
        image_tags: draft.image_tags,
        name: draft.name.trim(),
        prompt_text: draft.prompt_text,
      },
      originalName: latestSelected.name,
      sourceKey: selectedEffectKey,
    });
  }, [
    autoSave,
    draft.audio_tags,
    draft.color,
    draft.image_tags,
    draft.name,
    draft.prompt_text,
    identityMutation,
    liveNameError,
    resolveLatestSelectedEffect,
    selected,
    selectedEffectKey,
    showToast,
    t,
  ]);

  const cancelIdentityName = useCallback(() => {
    if (!selected) {
      return;
    }
    setDraft((current) => ({ ...current, name: selected.name }));
    setNameError("");
  }, [selected]);

  const validateCreateName = useCallback(
    (rawName: string): string | null => {
      const trimmed = rawName.trim();
      if (!trimmed) {
        return t("effect.validation.nameRequired");
      }
      if (!isValidEffectStorageName(trimmed)) {
        return t("identity.error.invalidEffectName");
      }
      if (data.some((item) => item.name.trim().toLowerCase() === trimmed.toLowerCase())) {
        return t("identity.error.duplicateName", { name: trimmed });
      }
      return null;
    },
    [data, t],
  );

  const saveDraft = useCallback(() => {
    const error = validateCreateName(draft.name);
    if (error) {
      setNameError(error);
      showToast({
        kind: "error",
        message: error === t("effect.validation.nameRequired") ? t("common.fixInvalidFields") : error,
        title: t("common.validationFailed"),
      });
      return;
    }
    saveMutation.mutate({
      effect: buildCreateEffectPayload(draft),
      originalName: undefined,
    });
  }, [draft, saveMutation, showToast, t, validateCreateName]);

  const ensureSavedForAction = useCallback(
    (onReady: () => void, options?: EnsureSavedOptions) => {
      if (!currentEffectName) {
        const error = validateCreateName(draft.name);
        if (error) {
          setNameError(error);
          if (options?.toastTitle) {
            showToast({
              kind: "error",
              message: error === t("effect.validation.nameRequired") ? t("common.fixInvalidFields") : error,
              title: options.toastTitle,
            });
          }
          return;
        }
        saveMutation.mutate(
          {
            effect: buildCreateEffectPayload(draft),
            originalName: undefined,
          },
          { onSuccess: onReady },
        );
        return;
      }
      if (options?.requireNonEmptyNameWhenSaved && !draft.name.trim()) {
        setNameError(t("effect.validation.nameRequired"));
        return;
      }
      onReady();
    },
    [currentEffectName, draft, saveMutation, showToast, t, validateCreateName],
  );

  const selectEffect = useCallback(
    (name: string) => {
      autoSave.flush();
      isCreatingRef.current = false;
      setIsCreating(false);
      setNameError("");
      setSelectedName(name);
    },
    [autoSave],
  );

  const startCreatingEffect = useCallback(() => {
    autoSave.flush();
    previousSelectedNameRef.current = currentEffectName || data[0]?.name || "";
    activeEffectKeyRef.current = "";
    isCreatingRef.current = true;
    setIsCreating(true);
    setSelectedName("");
    setDraft(createEffect());
    setNameError("");
  }, [autoSave, currentEffectName, data]);

  const cancelCreatingEffect = useCallback(() => {
    if (!data.length) {
      return;
    }
    const targetName =
      (previousSelectedNameRef.current && data.some((item) => item.name === previousSelectedNameRef.current)
        ? previousSelectedNameRef.current
        : data[0]?.name) || "";
    activeEffectKeyRef.current = "";
    isCreatingRef.current = false;
    setIsCreating(false);
    setNameError("");
    setSelectedName(targetName);
  }, [data]);

  const exportCurrentEffect = useCallback(() => {
    if (!currentEffectName) {
      showToast({
        kind: "error",
        message: t("effect.validation.nameRequired"),
        title: t("common.export"),
      });
      return;
    }
    exportMutation.mutate(currentEffectName);
  }, [currentEffectName, exportMutation, showToast, t]);

  const requestDeleteEffect = useCallback(() => {
    if (!currentEffectName) {
      showToast({
        kind: "error",
        message: t("effect.error.deleteFallback"),
        title: t("common.deleteFailed"),
      });
      return;
    }
    setPendingEffectDelete(currentEffectName);
  }, [currentEffectName, showToast, t]);

  const cancelDeleteEffect = useCallback(() => {
    setPendingEffectDelete(null);
  }, []);

  const confirmDeleteEffect = useCallback(() => {
    if (!pendingEffectDelete) {
      return;
    }
    const targetName = pendingEffectDelete;
    setPendingEffectDelete(null);
    deleteMutation.mutate(targetName);
  }, [deleteMutation, pendingEffectDelete]);

  return {
    autoSaveError: autoSave.errorMessage,
    autoSavePhase: autoSave.phase,
    autoSaveRetry: autoSave.retry,
    cancelCreatingEffect,
    cancelDeleteEffect,
    cancelIdentityName,
    confirmDeleteEffect,
    confirmIdentityName,
    currentEffectName,
    data,
    draft,
    ensureSavedForAction,
    exportCurrentEffect,
    exportPending: exportMutation.isPending,
    identityPending: identityMutation.isPending,
    importEffects: (paths: string[]) => importMutation.mutate(paths),
    importPending: importMutation.isPending,
    inCreateMode,
    invalidateEffects,
    isCreating,
    isLoading,
    liveNameError,
    nameDirty,
    patchDraft,
    pendingEffectDelete,
    requestDeleteEffect,
    saveDraft,
    savePending: saveMutation.isPending,
    selectedEffectKey,
    selectedName,
    selectEffect,
    beginSectionBusy,
    startCreatingEffect,
    syncSavedEffect,
    updateField,
  };
}
