import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { chatThemeQueryKey, listChatThemes, setActiveChatTheme } from "../../../entities/chat/repository";
import {
  configQueryKey,
  detectNetworkProxy,
  getAppConfig,
  saveSystemConfig,
} from "../../../entities/config/repository";
import {
  buildPayloadFromSchema,
  hasSchemaErrors,
  type SchemaErrorMap,
  validatePayloadFromSchema,
} from "../../../entities/config/schema";
import type { SystemConfig } from "../../../entities/config/types";
import { useAppState } from "../../../shared/app-state/AppState";
import { isTauriDesktop } from "../../../shared/desktop/desktopApi";
import { useI18n } from "../../../shared/i18n";
import {
  canConnectRemotePc,
  isRemotePcActive,
  isStandaloneRuntimeActive,
} from "../../../shared/platform/runtimeTarget";
import { applyThemeColor } from "../../../shared/theme/appTheme";
import { DEFAULT_CHAT_THEME_ID, chatThemeDisplayName } from "../../../shared/theme/chatTheme";
import { useToast } from "../../../shared/ui";
import { useOptionalChatTheme } from "../../chat-stage/theme/ChatThemeProvider";
import {
  networkProxySourceLabel,
  systemConfigPageSchema,
  type SystemSettingsPageContext,
} from "../systemSettingsContext";

export function useSystemSettingsController() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { language, t } = useI18n();
  const { dispatch } = useAppState();
  const chatTheme = useOptionalChatTheme();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const chatThemesQuery = useQuery({ queryFn: listChatThemes, queryKey: chatThemeQueryKey });
  const { data, isLoading } = configQuery;
  const [draft, setDraft] = useState<SystemConfig | null>(null);
  const [errors, setErrors] = useState<SchemaErrorMap<SystemConfig>>({});
  const [runtimeModeOpen, setRuntimeModeOpen] = useState(false);

  const showCrossPlatformCard =
    !isTauriDesktop() || isStandaloneRuntimeActive() || isRemotePcActive() || canConnectRemotePc();

  const themeOptions = useMemo(
    () =>
      [...(chatThemesQuery.data ?? [])].sort((left, right) =>
        chatThemeDisplayName(left, language).localeCompare(chatThemeDisplayName(right, language)),
      ),
    [chatThemesQuery.data, language],
  );
  const fallbackThemeId =
    themeOptions.find((theme) => theme.id === DEFAULT_CHAT_THEME_ID)?.id ?? themeOptions[0]?.id ?? "";
  const selectedThemeId =
    (themeOptions.some((theme) => theme.id === draft?.chat_ui_theme_id) ? draft?.chat_ui_theme_id : fallbackThemeId) ??
    "";

  useEffect(() => {
    if (data?.system_config) {
      setDraft({ ...data.system_config, chat_ui_runtime_mode: "react" });
      setErrors({});
      applyThemeColor(data.system_config.theme_color);
      if (["zh_CN", "en", "ja"].includes(data.system_config.ui_language)) {
        dispatch({ language: data.system_config.ui_language as "zh_CN" | "en" | "ja", type: "setLanguage" });
      }
    }
  }, [data?.system_config, dispatch]);

  useEffect(() => {
    applyThemeColor(draft?.theme_color);
  }, [draft?.theme_color]);

  useEffect(() => {
    if (!draft || themeOptions.length === 0 || draft.chat_ui_theme_id === selectedThemeId) {
      return;
    }
    setDraft({
      ...draft,
      chat_ui_theme_id: selectedThemeId,
    });
  }, [draft, selectedThemeId, themeOptions.length]);

  const saveMutation = useMutation({
    async mutationFn(payload: SystemConfig) {
      const saved = await saveSystemConfig({ ...payload, chat_ui_runtime_mode: "react" });
      const themeId = (saved.chat_ui_theme_id || payload.chat_ui_theme_id || "").trim();
      if (themeId) {
        const previousThemeId = (data?.system_config.chat_ui_theme_id || "").trim();
        if (themeId !== previousThemeId) {
          if (chatTheme) {
            await chatTheme.switchTheme(themeId);
          } else {
            await setActiveChatTheme(themeId);
          }
        }
      }
      return { ...saved, chat_ui_theme_id: themeId };
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("system.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(saved) {
      queryClient.invalidateQueries({ queryKey: configQueryKey });
      applyThemeColor(saved.theme_color);
      if (["zh_CN", "en", "ja"].includes(saved.ui_language)) {
        dispatch({ language: saved.ui_language as "zh_CN" | "en" | "ja", type: "setLanguage" });
      }
      showToast({ kind: "success", title: t("system.toast.saved") });
    },
  });

  const detectNetworkProxyMutation = useMutation({
    mutationFn: detectNetworkProxy,
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("ops.system.proxy.detectError"),
        title: t("ops.system.proxy.detectFailedTitle"),
      });
    },
    onSuccess(result) {
      const hasProxy = Boolean(result.http_proxy_url || result.https_proxy_url || result.socks5_proxy_url);
      const sourceLabel = networkProxySourceLabel(result.source, t);
      setDraft((current) =>
        current
          ? {
              ...current,
              http_proxy_url: result.http_proxy_url,
              https_proxy_url: result.https_proxy_url,
              network_proxy_enabled: hasProxy || current.network_proxy_enabled,
              socks5_proxy_url: result.socks5_proxy_url,
            }
          : current,
      );
      showToast({
        kind: hasProxy ? "success" : "info",
        message: hasProxy
          ? sourceLabel
            ? t("ops.system.proxy.sourcePrefix", { source: sourceLabel })
            : undefined
          : t("ops.system.proxy.emptyBody"),
        title: hasProxy ? t("ops.system.proxy.detectedTitle") : t("ops.system.proxy.emptyTitle"),
      });
    },
  });

  const handleSave = () => {
    if (!draft) {
      return;
    }
    const nextErrors = validatePayloadFromSchema(systemConfigPageSchema, draft, t);
    setErrors(nextErrors);
    if (hasSchemaErrors(nextErrors)) {
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return;
    }
    saveMutation.mutate({
      ...draft,
      ...buildPayloadFromSchema(systemConfigPageSchema, draft),
      chat_ui_runtime_mode: "react",
    });
  };

  const ctx: SystemSettingsPageContext | null = draft
    ? {
        chatThemesError: chatThemesQuery.error,
        chatThemesIsError: chatThemesQuery.isError,
        chatThemesLoading: chatThemesQuery.isLoading,
        detectNetworkProxyPending: detectNetworkProxyMutation.isPending,
        draft,
        errors,
        openChatThemes: () => navigate("/settings/system/chat-themes"),
        openRuntimeModeDialog: () => setRuntimeModeOpen(true),
        runDetectNetworkProxy: () => detectNetworkProxyMutation.mutate(),
        savePending: saveMutation.isPending,
        selectedThemeId,
        setDraft,
        showCrossPlatformCard,
        themeOptions,
      }
    : null;

  return {
    closeRuntimeModeDialog: () => setRuntimeModeOpen(false),
    configQuery,
    ctx,
    handleSave,
    isLoading,
    runtimeModeOpen,
  };
}
