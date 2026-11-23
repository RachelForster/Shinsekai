import { useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { configQueryKey, saveSystemConfig } from "../../../entities/config/repository";
import { useAppState } from "../../../shared/app-state/AppState";
import { useI18n } from "../../../shared/i18n";
import { useToast } from "../../../shared/ui";
import { normalizeUiLanguage, type UiLanguage } from "../apiSettingsUtils";
import type { ApiSettingsPageContext } from "../apiSettingsContext";

export function useApiLanguageController(ctx: ApiSettingsPageContext) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const { dispatch } = useAppState();

  const languageMutation = useMutation({
    mutationFn: async (language: UiLanguage) => {
      const baseSystem = ctx.data.system_config ?? ctx.systemDraft;
      if (!baseSystem) {
        throw new Error(t("system.error.saveFallback"));
      }
      return saveSystemConfig({ ...baseSystem, ui_language: language });
    },
    onError(error) {
      queryClient.invalidateQueries({ queryKey: configQueryKey });
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("system.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(saved) {
      ctx.setSystemDraft((current) => (current ? { ...current, ui_language: saved.ui_language } : saved));
      queryClient.invalidateQueries({ queryKey: configQueryKey });
      dispatch({ language: normalizeUiLanguage(saved.ui_language), type: "setLanguage" });
    },
  });

  const handleLanguageChange = useCallback(
    (language: UiLanguage) => {
      ctx.updateSystemDraft({ ui_language: language });
      languageMutation.mutate(language);
    },
    [ctx.updateSystemDraft, languageMutation],
  );

  return {
    disabled: languageMutation.isPending,
    handleLanguageChange,
  };
}
