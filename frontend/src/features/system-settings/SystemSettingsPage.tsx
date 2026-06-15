import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Palette, Save } from "lucide-react";

import {
  buildPayloadFromSchema,
  hasSchemaErrors,
  type SchemaErrorMap,
  systemConfigFormSchema,
  validatePayloadFromSchema,
} from "../../entities/config/schema";
import { chatThemeQueryKey, listChatThemes, setActiveChatTheme } from "../../entities/chat/repository";
import { configQueryKey, getAppConfig, saveSystemConfig } from "../../entities/config/repository";
import type { SystemConfig } from "../../entities/config/types";
import { useAppState } from "../../shared/app-state/AppState";
import { useI18n } from "../../shared/i18n";
import { applyThemeColor } from "../../shared/theme/appTheme";
import { DEFAULT_CHAT_THEME_ID, chatThemeDisplayName } from "../../shared/theme/chatTheme";
import { AsyncButton, EmptyState, QueryErrorState, SchemaDrivenForm, Select, useToast } from "../../shared/ui";
import { DesktopRuntimeSection } from "./DesktopRuntimeSection";
// Shared page layout classes (.page, .section, .form-grid, .field-row) come from shared/theme/settings-base.css
import "./SystemSettingsPage.css";

const systemConfigPageSchema = systemConfigFormSchema
  .map((group) => {
    if (group.id !== "ui") {
      return group;
    }
    return {
      ...group,
      fields: group.fields.filter((field) => field.name !== "ui_language" && field.name !== "chat_ui_theme_id"),
    };
  })
  .filter((group) => group.id !== "voice" && group.id !== "music-cover");

const systemGeneralGroups = systemConfigPageSchema.filter((group) => group.id === "ui");
const systemRemainingGroups = systemConfigPageSchema.filter((group) => group.id !== "ui");

export function SystemSettingsPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { language, t } = useI18n();
  const { dispatch } = useAppState();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const chatThemesQuery = useQuery({ queryFn: listChatThemes, queryKey: chatThemeQueryKey });
  const { data, isLoading } = configQuery;
  const [draft, setDraft] = useState<SystemConfig | null>(null);
  const [errors, setErrors] = useState<SchemaErrorMap<SystemConfig>>({});
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
      setDraft(data.system_config);
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
      const saved = await saveSystemConfig(payload);
      const themeId = (saved.chat_ui_theme_id || payload.chat_ui_theme_id || "").trim();
      if (themeId) {
        await setActiveChatTheme(themeId);
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

  if (configQuery.isError) {
    return (
      <QueryErrorState
        body={t("system.error.saveFallback")}
        error={configQuery.error}
        onRetry={() => void configQuery.refetch()}
        retryLabel={t("common.retry")}
        title={t("common.operationFailed")}
      />
    );
  }

  if (isLoading || !draft) {
    return <EmptyState title={t("system.loading")} />;
  }

  return (
    <div className="page system-page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("system.title")}</h1>
        </div>
        <div className="page__actions">
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={saveMutation.isPending}
            onClick={() => {
              const nextErrors = validatePayloadFromSchema(systemConfigPageSchema, draft);
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
              });
            }}
            variant="primary"
          >
            {t("common.save")}
          </AsyncButton>
        </div>
      </header>
      <DesktopRuntimeSection />
      <SchemaDrivenForm
        disabled={saveMutation.isPending}
        errors={errors}
        groups={systemGeneralGroups}
        onChange={setDraft}
        value={draft}
      />
      <section className="section system-chat-theme">
        <div className="section__header">
          <h2 className="section__title">{t("chat.theme.title")}</h2>
        </div>
        <label className="field-row" htmlFor="chat_ui_theme_id">
          <span className="field-row__label">
            <Palette aria-hidden className="system-chat-theme__icon" />
            <span className="field-row__label-text">{t("chat.theme.title")}</span>
          </span>
          <span className="field-row__control">
            <Select
              disabled={saveMutation.isPending || chatThemesQuery.isLoading || themeOptions.length === 0}
              id="chat_ui_theme_id"
              onChange={(event) => setDraft({ ...draft, chat_ui_theme_id: event.target.value })}
              value={selectedThemeId}
            >
              {themeOptions.map((theme) => (
                <option key={theme.id} value={theme.id}>
                  {chatThemeDisplayName(theme, language)}
                  {theme.source === "builtin"
                    ? ` · ${t("chat.theme.sourceBuiltin")}`
                    : ` · ${t("chat.theme.sourceUser")}`}
                </option>
              ))}
            </Select>
            {chatThemesQuery.isLoading ? <span className="field-row__help">{t("system.loading")}</span> : null}
            {!chatThemesQuery.isLoading && themeOptions.length === 0 ? (
              <span className="field-row__help">{t("chat.theme.empty")}</span>
            ) : null}
            {chatThemesQuery.isError ? (
              <span className="field-error">
                {chatThemesQuery.error instanceof Error ? chatThemesQuery.error.message : t("chat.theme.error.apply")}
              </span>
            ) : null}
          </span>
        </label>
      </section>
      <SchemaDrivenForm
        disabled={saveMutation.isPending}
        errors={errors}
        groups={systemRemainingGroups}
        onChange={setDraft}
        value={draft}
      />
    </div>
  );
}
