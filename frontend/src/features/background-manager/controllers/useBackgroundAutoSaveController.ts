import { useCallback, useMemo, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { backgroundsQueryKey, saveBackground } from "../../../entities/background/repository";
import type { Background } from "../../../entities/config/types";
import { useDebouncedAutoSave } from "../../../shared/hooks/useDebouncedAutoSave";
import { useI18n } from "../../../shared/i18n";
import { useToast } from "../../../shared/ui";
import { serializeBackgroundNonIdentity, upsertCatalogBackground } from "../backgroundUtils";

interface UseBackgroundAutoSaveControllerOptions {
  activeBackgroundKeyRef: MutableRefObject<string>;
  busyResumeRevision: number;
  busySectionsCount: number;
  cancelAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  currentDraft: Background;
  data: Background[];
  deletedBackgroundKeysRef: MutableRefObject<Set<string>>;
  deletePending: boolean;
  discardAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  identityMutation: {
    isPending: boolean;
    mutate: (
      variables: {
        background: Background;
        field: "name" | "sprite_prefix";
        originalName: string;
        sourceKey: string;
      },
      options?: { onSettled?: () => void },
    ) => void;
  };
  identitySavingField: "name" | "sprite_prefix" | null;
  inCreateMode: boolean;
  isCreatingRef: MutableRefObject<boolean>;
  isDraftSynced: boolean;
  nameDirty: boolean;
  nameError: string;
  pendingBackgroundDelete: string | null;
  queryClient: QueryClient;
  savePending: boolean;
  selected: Background | undefined;
  selectedBackgroundKey: string;
  setDraft: Dispatch<SetStateAction<Background>>;
  setIdentitySavingField: Dispatch<SetStateAction<"name" | "sprite_prefix" | null>>;
  setNameError: Dispatch<SetStateAction<string>>;
  setSpritePrefixError: Dispatch<SetStateAction<string>>;
  setSyncedBackgroundKey: Dispatch<SetStateAction<string>>;
  spritePrefixDirty: boolean;
  spritePrefixError: string;
}

export function useBackgroundAutoSaveController({
  activeBackgroundKeyRef,
  busyResumeRevision,
  busySectionsCount,
  cancelAutoSaveRef,
  currentDraft,
  data,
  deletedBackgroundKeysRef,
  deletePending,
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
  savePending,
  selected,
  selectedBackgroundKey,
  setDraft,
  setIdentitySavingField,
  setNameError,
  setSpritePrefixError,
  setSyncedBackgroundKey,
  spritePrefixDirty,
  spritePrefixError,
}: UseBackgroundAutoSaveControllerOptions) {
  const { showToast } = useToast();
  const { t } = useI18n();

  const liveNameError = useMemo(() => {
    if (!nameDirty || !selected) {
      return nameError;
    }
    const trimmed = currentDraft.name.trim();
    if (!trimmed) {
      return t("background.validation.nameRequired");
    }
    const duplicate = data.some(
      (item) =>
        item !== selected &&
        (selected.id ? item.id !== selected.id : item.name !== selected.name) &&
        item.name.trim().toLowerCase() === trimmed.toLowerCase(),
    );
    return duplicate ? t("identity.error.duplicateName", { name: trimmed }) : "";
  }, [currentDraft.name, data, nameDirty, nameError, selected, t]);

  const liveSpritePrefixError = useMemo(() => {
    if (!spritePrefixDirty || !selected) {
      return spritePrefixError;
    }
    const trimmed = currentDraft.sprite_prefix.trim();
    if (!trimmed) {
      return t("character.validation.spritePrefixRequired");
    }
    if (!/^[\x00-\x7F]+$/.test(trimmed)) {
      return t("character.validation.spritePrefixAscii");
    }
    const duplicate = data.some(
      (item) =>
        item !== selected &&
        (selected.id ? item.id !== selected.id : item.name !== selected.name) &&
        item.sprite_prefix.trim().toLowerCase() === trimmed.toLowerCase(),
    );
    return duplicate ? t("identity.error.duplicatePrefix", { prefix: trimmed }) : "";
  }, [currentDraft.sprite_prefix, data, selected, spritePrefixDirty, spritePrefixError, t]);

  const baselineAutoSaveKey = useMemo(() => (selected ? serializeBackgroundNonIdentity(selected) : ""), [selected]);
  const currentAutoSaveKey = useMemo(
    () => (selected ? serializeBackgroundNonIdentity(currentDraft) : ""),
    [currentDraft, selected],
  );

  const resolveLatestSelectedBackground = useCallback((): Background | undefined => {
    if (!selected) {
      return undefined;
    }
    const catalog = queryClient.getQueryData<Background[]>(backgroundsQueryKey) ?? data;
    return (
      (selected.id ? catalog.find((item) => item.id === selected.id) : undefined) ??
      catalog.find((item) => item.name === selected.name) ??
      selected
    );
  }, [data, queryClient, selected]);

  const autoSave = useDebouncedAutoSave<{ background: Background; originalName: string }>({
    baselineKey: baselineAutoSaveKey,
    buildPayload: () => {
      const latestSelected = resolveLatestSelectedBackground() ?? selected!;
      return {
        background: {
          ...latestSelected,
          ...(latestSelected.id ? { id: latestSelected.id } : {}),
          bg_tags: currentDraft.bg_tags,
          bgm_tags: currentDraft.bgm_tags,
          name: latestSelected.name,
          sprite_prefix: latestSelected.sprite_prefix,
        },
        originalName: latestSelected.name,
      };
    },
    currentKey: currentAutoSaveKey,
    enabled: Boolean(
      !inCreateMode &&
      isDraftSynced &&
      identitySavingField === null &&
      !identityMutation.isPending &&
      !savePending &&
      !deletePending &&
      busySectionsCount === 0 &&
      !pendingBackgroundDelete,
    ),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    async onSave({ background, originalName }, { isSuperseded, resetKey }) {
      const saved = await saveBackground(background, originalName);
      if (
        isSuperseded() ||
        deletedBackgroundKeysRef.current.has(resetKey) ||
        deletedBackgroundKeysRef.current.has(`name:${originalName}`)
      ) {
        return;
      }
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, saved, originalName),
      );
      if (saved.id && !isCreatingRef.current && activeBackgroundKeyRef.current === resetKey) {
        activeBackgroundKeyRef.current = saved.id;
        setSyncedBackgroundKey(saved.id);
        setDraft((current) => (current.id ? current : { ...current, id: saved.id }));
      }
    },
    rescheduleToken: busyResumeRevision,
    resetKey: selected ? selected.id || `name:${selected.name}` : "__creating__",
  });
  cancelAutoSaveRef.current = autoSave.cancel;
  discardAutoSaveRef.current = autoSave.discardPending;

  const confirmIdentityField = useCallback(
    (field: "name" | "sprite_prefix") => {
      if (!selected || identitySavingField !== null || identityMutation.isPending) {
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
      autoSave.discardPending();
      const latestSelected = resolveLatestSelectedBackground() ?? selected;
      setIdentitySavingField(field);
      identityMutation.mutate(
        {
          background: {
            ...latestSelected,
            ...(latestSelected.id ? { id: latestSelected.id } : {}),
            bg_tags: currentDraft.bg_tags,
            bgm_tags: currentDraft.bgm_tags,
            name: field === "name" ? currentDraft.name.trim() : latestSelected.name,
            sprite_prefix: field === "sprite_prefix" ? currentDraft.sprite_prefix.trim() : latestSelected.sprite_prefix,
          },
          field,
          originalName: latestSelected.name,
          sourceKey: selectedBackgroundKey,
        },
        {
          onSettled: () => setIdentitySavingField(null),
        },
      );
    },
    [
      autoSave,
      currentDraft.bg_tags,
      currentDraft.bgm_tags,
      currentDraft.name,
      currentDraft.sprite_prefix,
      identityMutation,
      identitySavingField,
      liveNameError,
      liveSpritePrefixError,
      resolveLatestSelectedBackground,
      selected,
      selectedBackgroundKey,
      setIdentitySavingField,
      showToast,
      t,
    ],
  );

  const cancelIdentityField = useCallback(
    (field: "name" | "sprite_prefix") => {
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
    },
    [selected, setDraft, setNameError, setSpritePrefixError],
  );

  const buildBackgroundCreateInput = useCallback(() => {
    const trimmedName = currentDraft.name.trim();
    if (!trimmedName) {
      setNameError(t("background.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return null;
    }
    if (data.some((item) => item.name.trim().toLowerCase() === trimmedName.toLowerCase())) {
      const duplicateError = t("identity.error.duplicateName", { name: trimmedName });
      setNameError(duplicateError);
      showToast({
        kind: "error",
        message: duplicateError,
        title: t("common.validationFailed"),
      });
      return null;
    }
    const spritePrefix = currentDraft.sprite_prefix.trim();
    const prefixError = !spritePrefix
      ? t("character.validation.spritePrefixRequired")
      : !/^[\x00-\x7F]+$/.test(spritePrefix)
        ? t("character.validation.spritePrefixAscii")
        : data.some((item) => item.sprite_prefix.trim().toLowerCase() === spritePrefix.toLowerCase())
          ? t("identity.error.duplicatePrefix", { prefix: spritePrefix })
          : "";
    if (prefixError) {
      setSpritePrefixError(prefixError);
      showToast({
        kind: "error",
        message: prefixError,
        title: t("common.validationFailed"),
      });
      return null;
    }
    const { id: _omittedId, ...restDraft } = currentDraft;
    return {
      background: {
        ...restDraft,
        name: trimmedName,
        sprite_prefix: spritePrefix,
      },
      originalName: undefined,
    };
  }, [currentDraft, data, setNameError, setSpritePrefixError, showToast, t]);

  return {
    autoSave,
    buildBackgroundCreateInput,
    cancelIdentityField,
    confirmIdentityField,
    liveNameError,
    liveSpritePrefixError,
  };
}
