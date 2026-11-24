import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { useMutation, type QueryClient } from "@tanstack/react-query";

import type { Effect } from "../../../entities/config/types";
import {
  deleteEffect,
  effectsQueryKey,
  exportEffect,
  importEffects,
  saveEffect,
} from "../../../entities/effect/repository";
import { useI18n } from "../../../shared/i18n";
import { useToast } from "../../../shared/ui";
import { normalizeEffect, upsertCatalogEffect } from "../effectDraft";

interface UseEffectCatalogMutationsOptions {
  activeEffectKeyRef: MutableRefObject<string>;
  cancelAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  data: Effect[];
  deletedEffectKeysRef: MutableRefObject<Set<string>>;
  discardAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  isCreatingRef: MutableRefObject<boolean>;
  queryClient: QueryClient;
  setDraft: Dispatch<SetStateAction<Effect>>;
  setIsCreating: Dispatch<SetStateAction<boolean>>;
  setNameError: Dispatch<SetStateAction<string>>;
  setSelectedName: Dispatch<SetStateAction<string>>;
  setSyncedEffectKey: Dispatch<SetStateAction<string>>;
}

export function useEffectCatalogMutations({
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
}: UseEffectCatalogMutationsOptions) {
  const { showToast } = useToast();
  const { t } = useI18n();

  const saveMutation = useMutation({
    mutationFn: ({ effect, originalName }: { effect: Effect; originalName?: string }) =>
      saveEffect(effect, originalName),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(effect, variables) {
      const nextKey = effect.id || `name:${effect.name}`;
      deletedEffectKeysRef.current.delete(nextKey);
      deletedEffectKeysRef.current.delete(`name:${effect.name}`);
      isCreatingRef.current = false;
      activeEffectKeyRef.current = nextKey;
      setSyncedEffectKey(nextKey);
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) =>
        upsertCatalogEffect(current, effect, variables.originalName),
      );
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setIsCreating(false);
      setNameError("");
      setSelectedName(effect.name);
      setDraft(structuredClone(effect));
      showToast({ kind: "success", title: t("effect.toast.saved") });
    },
  });

  const identityMutation = useMutation({
    mutationFn: async ({
      effect,
      originalName,
      sourceKey,
    }: {
      effect: Effect;
      originalName: string;
      sourceKey: string;
    }) => {
      await discardAutoSaveRef.current(sourceKey);
      return saveEffect(effect, originalName);
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(effect, variables) {
      if (
        deletedEffectKeysRef.current.has(variables.sourceKey) ||
        deletedEffectKeysRef.current.has(`name:${variables.originalName}`)
      ) {
        return;
      }
      const nextKey = effect.id || `name:${effect.name}`;
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) =>
        upsertCatalogEffect(current, effect, variables.originalName),
      );
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      if (!isCreatingRef.current && activeEffectKeyRef.current === variables.sourceKey) {
        activeEffectKeyRef.current = nextKey;
        setSyncedEffectKey(nextKey);
        setNameError("");
        setSelectedName(effect.name);
        setDraft((current) => ({
          ...current,
          ...(effect.id ? { id: effect.id } : {}),
          audio_list: effect.audio_list,
          image_audio_list: effect.image_audio_list,
          image_list: effect.image_list,
          name: effect.name,
        }));
      }
      showToast({ kind: "success", title: t("effect.toast.saved") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (targetName: string) => {
      const target = data.find((item) => item.name === targetName);
      const targetKey = target ? target.id || `name:${target.name}` : `name:${targetName}`;
      deletedEffectKeysRef.current.add(targetKey);
      deletedEffectKeysRef.current.add(`name:${targetName}`);
      await cancelAutoSaveRef.current(targetKey);
      return deleteEffect(targetName);
    },
    onSuccess(_result, deletedName) {
      setSelectedName((current) => (current === deletedName ? "" : current));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      showToast({ kind: "success", title: t("effect.toast.deleted") });
    },
    onError(error, deletedName) {
      const target = data.find((item) => item.name === deletedName);
      if (target?.id) {
        deletedEffectKeysRef.current.delete(target.id);
      }
      deletedEffectKeysRef.current.delete(`name:${deletedName}`);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.deleteFallback"),
        title: t("common.deleteFailed"),
      });
    },
  });

  const importMutation = useMutation({
    mutationFn: importEffects,
    onSuccess(imported) {
      for (const item of imported) {
        if (item.id) {
          deletedEffectKeysRef.current.delete(item.id);
        }
        deletedEffectKeysRef.current.delete(`name:${item.name}`);
      }
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => [...current, ...imported]);
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      const lastImported = imported[imported.length - 1];
      if (lastImported) {
        const nextKey = lastImported.id || `name:${lastImported.name}`;
        isCreatingRef.current = false;
        activeEffectKeyRef.current = nextKey;
        setSyncedEffectKey(nextKey);
        setIsCreating(false);
        setSelectedName(lastImported.name);
        setDraft(normalizeEffect(structuredClone(lastImported)));
      }
      showToast({ kind: "success", title: t("effect.toast.importComplete", { count: imported.length }) });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.importFallback"),
        title: t("common.importFailed"),
      });
    },
  });

  const exportMutation = useMutation({
    mutationFn: exportEffect,
    onSuccess(path) {
      showToast({ kind: "success", message: path, title: t("effect.toast.exportComplete") });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.exportFallback"),
        title: t("common.exportFailed"),
      });
    },
  });

  return {
    deleteMutation,
    exportMutation,
    identityMutation,
    importMutation,
    saveMutation,
  };
}
