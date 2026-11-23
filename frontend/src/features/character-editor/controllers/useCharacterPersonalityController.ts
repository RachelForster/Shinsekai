import { useCallback } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  generateCharacterBrief,
  generateCharacterSetting,
  translateCharacterFields,
} from "../../../entities/character/repository";
import { useI18n } from "../../../shared/i18n";
import { useReportSectionBusy, useToast } from "../../../shared/ui";
import type { CharacterPageContext } from "../characterContext";

interface AiSettingVariables {
  committedName: string;
  identityEpoch: number;
  name: string;
  releaseAiAction: () => void;
  setting: string;
  sourceKey: string;
  wasCreating: boolean;
}

interface AiBriefVariables {
  name: string;
  releaseAiAction: () => void;
  setting: string;
  sourceKey: string;
  wasCreating: boolean;
}

interface AiTranslateVariables {
  characterSetting: string;
  emotionTags: string;
  name: string;
  releaseAiAction: () => void;
  sourceKey: string;
  wasCreating: boolean;
}

export function useCharacterPersonalityController(ctx: CharacterPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();

  const aiSettingMutation = useMutation({
    mutationFn: ({ name, setting }: AiSettingVariables) => generateCharacterSetting({ name, setting }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.aiFallback"),
        title: t("character.action.aiWrite"),
      });
    },
    onSettled(_data, _error, variables) {
      variables.releaseAiAction();
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
      ctx.syncGeneratedSetting({
        characterBrief: result.characterBrief,
        characterSetting: result.characterSetting,
        committedName: variables.committedName,
        identityEpoch: variables.identityEpoch,
        name: variables.name,
        sourceKey: variables.sourceKey,
        wasCreating: variables.wasCreating,
      });
      showToast({ kind: "success", message: result.message, title: t("character.action.aiWrite") });
    },
  });

  const aiBriefMutation = useMutation({
    mutationFn: ({ name, setting }: AiBriefVariables) => generateCharacterBrief({ name, setting }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.aiFallback"),
        title: t("character.action.aiBrief"),
      });
    },
    onSettled(_data, _error, variables) {
      variables.releaseAiAction();
    },
    onSuccess(result, variables) {
      if (ctx.isSelectionActive(variables.sourceKey, variables.wasCreating)) {
        ctx.updateField("character_brief", result.characterBrief);
      }
      showToast({ kind: "success", message: result.message, title: t("character.action.aiBrief") });
    },
  });

  const translateMutation = useMutation({
    mutationFn: ({ characterSetting, emotionTags, name }: AiTranslateVariables) =>
      translateCharacterFields({
        characterSetting,
        emotionTags,
        name,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.error.translateFallback"),
        title: t("character.action.aiTranslate"),
      });
    },
    onSettled(_data, _error, variables) {
      variables.releaseAiAction();
    },
    onSuccess(result, variables) {
      if (result.error) {
        showToast({ kind: "error", message: result.error, title: t("character.action.aiTranslate") });
        return;
      }
      if (ctx.isSelectionActive(variables.sourceKey, variables.wasCreating)) {
        ctx.patchDraft((current) => ({
          ...current,
          character_setting: result.characterSetting,
          emotion_tags: result.emotionTags,
          name: result.name,
        }));
        if (result.name.trim()) {
          ctx.setNameError("");
        }
      }
      showToast({ kind: "success", title: t("character.action.aiTranslate") });
    },
  });

  useReportSectionBusy(
    ctx.setSectionBusy,
    "character-personality",
    aiSettingMutation.isPending || aiBriefMutation.isPending || translateMutation.isPending,
  );

  const generateSetting = useCallback(() => {
    if (ctx.identityPending || aiSettingMutation.isPending) {
      return;
    }
    if (!ctx.draft.name.trim()) {
      ctx.setNameError(t("character.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return;
    }
    const aiLease = ctx.tryBeginAiAction();
    if (!aiLease) {
      return;
    }
    aiSettingMutation.mutate({
      committedName: !ctx.inCreateMode && ctx.selected ? ctx.selected.name : "",
      identityEpoch: aiLease.identityEpoch,
      name: ctx.draft.name.trim(),
      releaseAiAction: aiLease.release,
      setting: ctx.draft.character_setting,
      sourceKey: ctx.selectedCharacterKey,
      wasCreating: ctx.inCreateMode,
    });
  }, [
    aiSettingMutation,
    ctx.draft.character_setting,
    ctx.draft.name,
    ctx.identityPending,
    ctx.inCreateMode,
    ctx.selected,
    ctx.selectedCharacterKey,
    ctx.setNameError,
    ctx.tryBeginAiAction,
    showToast,
    t,
  ]);

  const generateBrief = useCallback(() => {
    if (ctx.identityPending || aiBriefMutation.isPending) {
      return;
    }
    if (!ctx.draft.name.trim() || !ctx.draft.character_setting.trim()) {
      showToast({
        kind: "error",
        message: t("character.validation.briefSourceRequired"),
        title: t("common.validationFailed"),
      });
      return;
    }
    const aiLease = ctx.tryBeginAiAction();
    if (!aiLease) {
      return;
    }
    aiBriefMutation.mutate({
      name: ctx.draft.name.trim(),
      releaseAiAction: aiLease.release,
      setting: ctx.draft.character_setting,
      sourceKey: ctx.selectedCharacterKey,
      wasCreating: ctx.inCreateMode,
    });
  }, [
    aiBriefMutation,
    ctx.draft.character_setting,
    ctx.draft.name,
    ctx.identityPending,
    ctx.inCreateMode,
    ctx.selectedCharacterKey,
    ctx.tryBeginAiAction,
    showToast,
    t,
  ]);

  const translateDraft = useCallback(() => {
    if (ctx.identityPending || translateMutation.isPending) {
      return;
    }
    if (!ctx.draft.name.trim() && !ctx.draft.character_setting.trim() && !ctx.draft.emotion_tags.trim()) {
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return;
    }
    const aiLease = ctx.tryBeginAiAction();
    if (!aiLease) {
      return;
    }
    translateMutation.mutate({
      characterSetting: ctx.draft.character_setting,
      emotionTags: ctx.draft.emotion_tags,
      name: ctx.draft.name,
      releaseAiAction: aiLease.release,
      sourceKey: ctx.selectedCharacterKey,
      wasCreating: ctx.inCreateMode,
    });
  }, [
    ctx.draft.character_setting,
    ctx.draft.emotion_tags,
    ctx.draft.name,
    ctx.identityPending,
    ctx.inCreateMode,
    ctx.selectedCharacterKey,
    ctx.tryBeginAiAction,
    showToast,
    t,
    translateMutation,
  ]);

  return {
    aiPending: aiSettingMutation.isPending,
    briefPending: aiBriefMutation.isPending,
    generateBrief,
    generateSetting,
    translateDraft,
    translatePending: translateMutation.isPending,
  };
}
