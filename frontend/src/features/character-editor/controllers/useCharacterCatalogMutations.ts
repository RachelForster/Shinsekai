import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { useMutation, type QueryClient } from "@tanstack/react-query";

import {
  charactersQueryKey,
  deleteCharacter,
  exportCharacter,
  importCharacters,
  saveCharacter,
} from "../../../entities/character/repository";
import { relationQueryKey } from "../../../entities/character-relation/repository";
import type { Character } from "../../../entities/config/types";
import { templatesQueryKey } from "../../../entities/template/repository";
import { useI18n } from "../../../shared/i18n";
import type { TemplateLaunchSession } from "../../../shared/platform/types";
import { useToast } from "../../../shared/ui";
import { mergeSprites } from "../characterContext";
import { pronunciationMapToText, upsertCatalogCharacter } from "../characterEditorUtils";

interface UseCharacterCatalogMutationsOptions {
  activeCharacterKeyRef: MutableRefObject<string>;
  cancelAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  data: Character[];
  deletedCharacterKeysRef: MutableRefObject<Set<string>>;
  discardAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  identityMutationEpochRef: MutableRefObject<number>;
  identityPendingRef: MutableRefObject<boolean>;
  isCreatingRef: MutableRefObject<boolean>;
  queryClient: QueryClient;
  setDraft: Dispatch<SetStateAction<Character>>;
  setIdentitySavingField: Dispatch<SetStateAction<"name" | "sprite_prefix" | null>>;
  setIsCreating: Dispatch<SetStateAction<boolean>>;
  setNameError: Dispatch<SetStateAction<string>>;
  setPendingDelete: Dispatch<SetStateAction<string | null>>;
  setPronunciationText: Dispatch<SetStateAction<string>>;
  setSelectedName: Dispatch<SetStateAction<string>>;
  setSpritePrefixError: Dispatch<SetStateAction<string>>;
  setSpritePrefixTouched: Dispatch<SetStateAction<boolean>>;
  setSyncedCharacterKey: Dispatch<SetStateAction<string>>;
}

export function useCharacterCatalogMutations({
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
}: UseCharacterCatalogMutationsOptions) {
  const { showToast } = useToast();
  const { t } = useI18n();

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
              playerCharacter: current.playerCharacter === oldName ? newName : current.playerCharacter,
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
          display_name: character.display_name,
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

  return {
    deleteMutation,
    exportMutation,
    identityMutation,
    importMutation,
    saveMutation,
  };
}
