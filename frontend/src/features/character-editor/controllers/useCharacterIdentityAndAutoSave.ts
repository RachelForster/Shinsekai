import { useCallback, useMemo, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { charactersQueryKey, saveCharacter } from "../../../entities/character/repository";
import type { Character } from "../../../entities/config/types";
import { useDebouncedAutoSave } from "../../../shared/hooks/useDebouncedAutoSave";
import { useI18n } from "../../../shared/i18n";
import { SELF_PERSONA_NAME } from "../../../shared/playerCharacterOptions";
import { useToast } from "../../../shared/ui";
import {
  SELF_PERSONA_SPRITE_PREFIX,
  buildCommittedCharacterPayload,
  buildNewCharacterPayload,
  pronunciationTextToMap,
  serializeCharacterNonIdentity,
  upsertCatalogCharacter,
} from "../characterEditorUtils";

interface UseCharacterIdentityAndAutoSaveOptions {
  activeCharacterKeyRef: MutableRefObject<string>;
  aiActionPending: boolean;
  busyResumeRevision: number;
  busySectionsCount: number;
  cancelAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  data: Character[];
  deletedCharacterKeysRef: MutableRefObject<Set<string>>;
  deletePending: boolean;
  discardAutoSaveRef: MutableRefObject<(targetKey?: string) => Promise<void>>;
  draft: Character;
  identityMutation: {
    isPending: boolean;
    mutate: (variables: {
      character: Character;
      field: "name" | "sprite_prefix";
      originalName: string;
      sourceKey: string;
    }) => void;
  };
  identityMutationEpochRef: MutableRefObject<number>;
  identityPendingRef: MutableRefObject<boolean>;
  identitySavingField: "name" | "sprite_prefix" | null;
  inCreateMode: boolean;
  isCreatingRef: MutableRefObject<boolean>;
  isDraftSynced: boolean;
  lockedSelectedPersona: boolean;
  nameDirty: boolean;
  nameError: string;
  pendingAiActionsRef: MutableRefObject<number>;
  pendingDelete: string | null;
  pronunciationText: string;
  queryClient: QueryClient;
  savePending: boolean;
  selected: Character | undefined;
  selectedCharacterKey: string;
  setDraft: Dispatch<SetStateAction<Character>>;
  setIdentitySavingField: Dispatch<SetStateAction<"name" | "sprite_prefix" | null>>;
  setNameError: Dispatch<SetStateAction<string>>;
  setSpritePrefixError: Dispatch<SetStateAction<string>>;
  setSyncedCharacterKey: Dispatch<SetStateAction<string>>;
  spriteGenerationOpen: boolean;
  spritePrefixDirty: boolean;
  spritePrefixError: string;
}

export function useCharacterIdentityAndAutoSave({
  activeCharacterKeyRef,
  aiActionPending,
  busyResumeRevision,
  busySectionsCount,
  cancelAutoSaveRef,
  data,
  deletedCharacterKeysRef,
  deletePending,
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
  savePending,
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
}: UseCharacterIdentityAndAutoSaveOptions) {
  const { showToast } = useToast();
  const { t } = useI18n();

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

  const liveNameError = useMemo(() => {
    if (!nameDirty || !selected) {
      return nameError;
    }
    const trimmed = draft.name.trim();
    if (!trimmed) {
      return t("character.validation.nameRequired");
    }
    const duplicate =
      (!lockedSelectedPersona && trimmed === SELF_PERSONA_NAME) ||
      data.some(
        (item) =>
          item !== selected &&
          (selected.id ? item.id !== selected.id : item.name !== selected.name) &&
          item.name.trim().toLowerCase() === trimmed.toLowerCase(),
      );
    return duplicate ? t("identity.error.duplicateName", { name: trimmed }) : "";
  }, [data, draft.name, lockedSelectedPersona, nameDirty, nameError, selected, t]);

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
      !savePending &&
      !deletePending &&
      !spriteGenerationOpen &&
      busySectionsCount === 0 &&
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
    rescheduleToken: busyResumeRevision,
    resetKey: selected ? selected.id || `name:${selected.name}` : "__creating__",
    validate: ({ character }) => {
      const errors = validateNonIdentityFields(character);
      return errors.length ? errors.join("\n") : null;
    },
  });
  cancelAutoSaveRef.current = autoSave.cancel;
  discardAutoSaveRef.current = autoSave.discardPending;

  const confirmIdentityField = useCallback(
    (field: "name" | "sprite_prefix") => {
      if (
        !selected ||
        (field === "sprite_prefix" && lockedSelectedPersona) ||
        identitySavingField !== null ||
        identityMutation.isPending ||
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
      const committed = buildCommittedCharacterPayload(draft, currentPronunciationMap, latestSelected, {
        name: field === "name" ? draft.name.trim() : latestSelected.name,
        sprite_prefix: field === "sprite_prefix" ? draft.sprite_prefix.trim() : latestSelected.sprite_prefix,
      });
      identityMutation.mutate({
        character: lockedSelectedPersona && field === "name" ? { ...committed, display_name: "" } : committed,
        field,
        originalName: latestSelected.name,
        sourceKey: selectedCharacterKey,
      });
    },
    [
      aiActionPending,
      autoSave,
      currentPronunciationMap,
      draft,
      identityMutation,
      identityMutationEpochRef,
      identityPendingRef,
      identitySavingField,
      liveNameError,
      liveSpritePrefixError,
      lockedSelectedPersona,
      pendingAiActionsRef,
      resolveLatestSelectedCharacter,
      selected,
      selectedCharacterKey,
      setIdentitySavingField,
      showToast,
      t,
      validateNonIdentityFields,
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

  const buildCharacterCreateInput = useCallback(() => {
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
  }, [
    currentPronunciationMap,
    data,
    draft,
    setNameError,
    setSpritePrefixError,
    showToast,
    t,
    validateNonIdentityFields,
  ]);

  return {
    autoSave,
    buildCharacterCreateInput,
    cancelIdentityField,
    confirmIdentityField,
    liveNameError,
    liveSpritePrefixError,
  };
}
