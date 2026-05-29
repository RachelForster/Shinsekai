import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";

import {
  buildPayloadFromSchema,
  hasSchemaErrors,
  type SchemaErrorMap,
  systemConfigFormSchema,
  validatePayloadFromSchema,
} from "../../entities/config/schema";
import { configQueryKey, getAppConfig, saveSystemConfig } from "../../entities/config/repository";
import type { SystemConfig } from "../../entities/config/types";
import { useAppState } from "../../shared/app-state/AppState";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, EmptyState, QueryErrorState, SchemaDrivenForm, useToast } from "../../shared/ui";

const systemConfigPageSchema = systemConfigFormSchema
  .map((group) => {
    if (group.id !== "ui") {
      return group;
    }
    return {
      ...group,
      fields: group.fields.filter((field) => field.name !== "ui_language"),
    };
  })
  .filter((group) => group.id !== "voice" && group.id !== "music-cover");

const systemGeneralGroups = systemConfigPageSchema.filter((group) => group.id === "ui");
const systemRemainingGroups = systemConfigPageSchema.filter((group) => group.id !== "ui");

export function SystemSettingsPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const { dispatch } = useAppState();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const { data, isLoading } = configQuery;
  const [draft, setDraft] = useState<SystemConfig | null>(null);
  const [errors, setErrors] = useState<SchemaErrorMap<SystemConfig>>({});

  useEffect(() => {
    if (data?.system_config) {
      setDraft(data.system_config);
      setErrors({});
      if (["zh_CN", "en", "ja"].includes(data.system_config.ui_language)) {
        dispatch({ language: data.system_config.ui_language as "zh_CN" | "en" | "ja", type: "setLanguage" });
      }
    }
  }, [data?.system_config, dispatch]);

  const saveMutation = useMutation({
    mutationFn: saveSystemConfig,
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("system.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(saved) {
      queryClient.invalidateQueries({ queryKey: configQueryKey });
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
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("system.title")}</h1>
          <p className="page__description">{t("system.description")}</p>
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
      <SchemaDrivenForm
        disabled={saveMutation.isPending}
        errors={errors}
        groups={systemGeneralGroups}
        onChange={setDraft}
        value={draft}
      />
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
