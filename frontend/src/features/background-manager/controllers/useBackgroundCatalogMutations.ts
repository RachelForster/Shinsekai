import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { useMutation, type QueryClient } from "@tanstack/react-query";

import {
  backgroundsQueryKey,
  deleteBackground,
  exportBackground,
  importBackgrounds,
  saveBackground,
} from "../../../entities/background/repository";
import type { Background } from "../../../entities/config/types";
import { useI18n } from "../../../shared/i18n";
import { useToast } from "../../../shared/ui";
import { upsertCatalogBackground } from "../backgroundUtils";

interface UseBackgroundCatalogMutationsOptions {
  activeBackgroundKeyRef: MutableRefObject<string>;
  cancelAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  data: Background[];
  deletedBackgroundKeysRef: MutableRefObject<Set<string>>;
  discardAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  isCreatingRef: MutableRefObject<boolean>;
  queryClient: QueryClient;
  setDraft: Dispatch<SetStateAction<Background>>;
  setDraftSourceName: Dispatch<SetStateAction<string>>;
  setIsCreating: Dispatch<SetStateAction<boolean>>;
  setNameError: Dispatch<SetStateAction<string>>;
  setSelectedName: Dispatch<SetStateAction<string>>;
  setSpritePrefixError: Dispatch<SetStateAction<string>>;
  setSpritePrefixTouched: Dispatch<SetStateAction<boolean>>;
  setSyncedBackgroundKey: Dispatch<SetStateAction<string>>;
}

export function useBackgroundCatalogMutations({
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
}: UseBackgroundCatalogMutationsOptions) {
  const { showToast } = useToast();
  const { t } = useI18n();

  const saveMutation = useMutation({
    mutationFn: ({ background, originalName }: { background: Background; originalName?: string }) =>
      saveBackground(background, originalName),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(background, variables) {
      const nextKey = background.id || `name:${background.name}`;
      deletedBackgroundKeysRef.current.delete(nextKey);
      deletedBackgroundKeysRef.current.delete(`name:${background.name}`);
      isCreatingRef.current = false;
      activeBackgroundKeyRef.current = nextKey;
      setSyncedBackgroundKey(nextKey);
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, background, variables.originalName),
      );
      setIsCreating(false);
      setSpritePrefixTouched(false);
      if (!variables.originalName) {
        setNameError("");
        setSpritePrefixError("");
      }
      setSelectedName(background.name);
      setDraft((current) =>
        variables.originalName
          ? {
              ...structuredClone(background),
              name: current.name,
              sprite_prefix: current.sprite_prefix,
            }
          : structuredClone(background),
      );
      setDraftSourceName(background.name);
      showToast({ kind: "success", title: t("background.toast.saved") });
    },
  });

  const identityMutation = useMutation({
    mutationFn: async ({
      background,
      originalName,
      sourceKey,
    }: {
      background: Background;
      field: "name" | "sprite_prefix";
      originalName: string;
      sourceKey: string;
    }) => {
      await discardAutoSaveRef.current(sourceKey);
      return saveBackground(background, originalName);
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(background, variables) {
      if (
        deletedBackgroundKeysRef.current.has(variables.sourceKey) ||
        deletedBackgroundKeysRef.current.has(`name:${variables.originalName}`)
      ) {
        return;
      }
      const nextKey = background.id || `name:${background.name}`;
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, background, variables.originalName),
      );
      if (!isCreatingRef.current && activeBackgroundKeyRef.current === variables.sourceKey) {
        activeBackgroundKeyRef.current = nextKey;
        setSyncedBackgroundKey(nextKey);
        setSelectedName(background.name);
        setDraftSourceName(background.name);
        setDraft((current) => ({
          ...current,
          ...(background.id ? { id: background.id } : {}),
          bgm_list: background.bgm_list,
          name: variables.field === "name" ? background.name : current.name,
          sprite_prefix: variables.field === "sprite_prefix" ? background.sprite_prefix : current.sprite_prefix,
          sprites: background.sprites,
        }));
        if (variables.field === "name") {
          setNameError("");
        } else {
          setSpritePrefixError("");
        }
      }
      showToast({ kind: "success", title: t("background.toast.saved") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (targetName: string) => {
      const target = data.find((item) => item.name === targetName);
      const targetKey = target ? target.id || `name:${target.name}` : `name:${targetName}`;
      deletedBackgroundKeysRef.current.add(targetKey);
      deletedBackgroundKeysRef.current.add(`name:${targetName}`);
      await cancelAutoSaveRef.current(targetKey);
      return deleteBackground(targetName);
    },
    onSuccess(_result, deletedName) {
      setSelectedName((current) => (current === deletedName ? "" : current));
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      showToast({ kind: "success", title: t("background.toast.deleted") });
    },
    onError(error, deletedName) {
      const target = data.find((item) => item.name === deletedName);
      if (target?.id) {
        deletedBackgroundKeysRef.current.delete(target.id);
      }
      deletedBackgroundKeysRef.current.delete(`name:${deletedName}`);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.deleteFallback"),
        title: t("common.deleteFailed"),
      });
    },
  });

  const importMutation = useMutation({
    mutationFn: importBackgrounds,
    onSuccess(imported) {
      for (const item of imported) {
        if (item.id) {
          deletedBackgroundKeysRef.current.delete(item.id);
        }
        deletedBackgroundKeysRef.current.delete(`name:${item.name}`);
      }
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      const lastImported = imported[imported.length - 1];
      if (lastImported) {
        isCreatingRef.current = false;
        setIsCreating(false);
        setSelectedName(lastImported.name);
        setDraft(structuredClone(lastImported));
        setDraftSourceName(lastImported.name);
      }
      showToast({ kind: "success", title: t("background.toast.importComplete", { count: imported.length }) });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.importFallback"),
        title: t("common.importFailed"),
      });
    },
  });

  const exportMutation = useMutation({
    mutationFn: exportBackground,
    onSuccess(path) {
      showToast({ kind: "success", message: path, title: t("background.toast.exportComplete") });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.exportFallback"),
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
