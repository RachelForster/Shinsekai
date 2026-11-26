import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DownloadCloud, PlugZap, Save, Search } from "lucide-react";

import {
  configQueryKey,
  downloadTtsBundle,
  fetchLlmModels,
  getAppConfig,
  getTtsBundleRecommendation,
  saveApiConfig,
  testLlmConnection,
  ttsBundleRecommendationQueryKey,
} from "../../../entities/config/repository";
import type { ApiConfig } from "../../../entities/config/types";
import { formatLlmProviderLabel, useI18n } from "../../../shared/i18n";
import type { TaskSnapshot, TtsBundleDownloadResult, TtsBundleKind } from "../../../shared/platform/types";
import {
  applyDownloadedTtsBundle,
  llmDefaultBaseUrls,
  normalizeProviderBaseUrls,
  normalizeTtsProvider,
} from "../../api-settings/apiSettingsUtils";
import {
  AsyncButton,
  Button,
  EmptyState,
  QueryErrorState,
  Select,
  TaskProgress,
  TextInput,
  useToast,
} from "../../../shared/ui";
import { FieldBlock, OnboardingPanelLayout, OnboardingTaskPanel } from "../OnboardingPanelLayout";

interface ApiSetupPanelProps {
  onSaved?: () => void;
}

function activeProviderValue(record: Record<string, string> | undefined, provider: string) {
  return record?.[provider] ?? "";
}

function updateProviderValue(record: Record<string, string> | undefined, provider: string, value: string) {
  return { ...(record ?? {}), [provider]: value };
}

export function ApiSetupPanel({ onSaved }: ApiSetupPanelProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const ttsBundleRecommendationQuery = useQuery({
    queryFn: getTtsBundleRecommendation,
    queryKey: ttsBundleRecommendationQueryKey,
  });
  const [draft, setDraft] = useState<ApiConfig | null>(null);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [ttsBundleTask, setTtsBundleTask] = useState<TaskSnapshot<TtsBundleDownloadResult> | null>(null);

  useEffect(() => {
    if (configQuery.data?.api_config) {
      setDraft(normalizeProviderBaseUrls(configQuery.data.api_config));
    }
  }, [configQuery.data?.api_config]);

  const providerOptions = configQuery.data?.adapter_catalog?.llm ?? [];
  const provider = draft?.llm_provider || providerOptions[0]?.value || "";
  const ttsBundleKind = ttsBundleRecommendationQuery.data?.kind ?? "genie";
  const apiKey = activeProviderValue(draft?.llm_api_key, provider);
  const model = activeProviderValue(draft?.llm_model, provider);
  const baseUrl = draft?.llm_base_url ?? "";
  const hasVerifiedBundledQwen3Tts = Boolean(configQuery.data?.tts_bundle_installed_paths?.["qwen3-tts-gguf"]?.trim());
  const isBundledQwen3TtsReady =
    normalizeTtsProvider(draft?.tts_provider ?? "") === "qwen3-tts-gguf" && hasVerifiedBundledQwen3Tts;
  const canSave = Boolean(draft && provider && baseUrl.trim() && apiKey.trim() && model.trim());
  const providerChoices = useMemo(() => {
    if (providerOptions.length) {
      return providerOptions;
    }
    return provider ? [{ label: provider, value: provider }] : [];
  }, [provider, providerOptions]);

  const saveMutation = useMutation({
    mutationFn: (next: ApiConfig) => saveApiConfig(next),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("onboarding.toastFailed"),
      });
    },
    onSuccess(saved) {
      queryClient.setQueryData(configQueryKey, (current: typeof configQuery.data) =>
        current ? { ...current, api_config: saved } : current,
      );
      onSaved?.();
      showToast({ kind: "success", title: t("onboarding.actions.saved") });
    },
  });

  const ttsBundleMutation = useMutation({
    mutationFn: (kind: TtsBundleKind) => downloadTtsBundle({ kind }, { onTaskUpdate: setTtsBundleTask }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("onboarding.toastFailed"),
      });
    },
    onMutate() {
      setTtsBundleTask(null);
    },
    onSuccess(result) {
      if (draft) {
        const next = applyDownloadedTtsBundle(draft, result);
        setDraft(next);
        saveMutation.mutate(next);
      }
      showToast({
        kind: "success",
        message: t("onboarding.api.bundleDone"),
        title: t("onboarding.api.voiceTitle"),
      });
    },
  });

  const modelsMutation = useMutation({
    mutationFn: () => fetchLlmModels({ apiKey, baseUrl, provider }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("onboarding.toastFailed"),
      });
    },
    onSuccess(result) {
      const ids = result.map((item) => item.id).filter(Boolean);
      setModelOptions(ids);
      showToast({
        kind: "success",
        message: String(ids.length),
        title: t("onboarding.actions.fetchModels"),
      });
    },
  });

  const testMutation = useMutation({
    mutationFn: () => testLlmConnection({ apiKey, baseUrl, model, provider }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : "",
        title: t("onboarding.toastFailed"),
      });
    },
    onSuccess() {
      showToast({ kind: "success", title: t("onboarding.api.connected") });
      if (draft) {
        saveMutation.mutate(draft);
      }
    },
  });

  if (configQuery.isLoading || !draft) {
    return <EmptyState title={t("onboarding.common.loading")} />;
  }

  if (configQuery.isError) {
    return (
      <QueryErrorState
        error={configQuery.error}
        onRetry={() => void configQuery.refetch()}
        retryLabel={t("onboarding.actions.retry")}
        title={t("onboarding.toastFailed")}
      />
    );
  }

  return (
    <OnboardingPanelLayout
      description={t("onboarding.api.description")}
      title={t("onboarding.api.title")}
      actions={
        <AsyncButton
          disabled={!canSave}
          icon={<Save aria-hidden size={16} />}
          loading={saveMutation.isPending}
          onClick={() => draft && saveMutation.mutate(draft)}
        >
          {t("onboarding.actions.save")}
        </AsyncButton>
      }
    >
      <OnboardingTaskPanel defaultOpen description={t("onboarding.api.description")} title={t("onboarding.api.title")}>
        <div className="onboarding-form-grid">
          <FieldBlock label={t("onboarding.api.provider")}>
            <Select
              onChange={(event) => {
                const nextProvider = event.target.value;
                setDraft((current) => {
                  if (!current) return current;
                  const nextBaseUrl =
                    activeProviderValue(current.llm_base_urls, nextProvider) || llmDefaultBaseUrls[nextProvider] || "";
                  return {
                    ...current,
                    llm_base_url: nextBaseUrl,
                    llm_base_urls: updateProviderValue(current.llm_base_urls, nextProvider, nextBaseUrl),
                    llm_provider: nextProvider,
                  };
                });
              }}
              value={provider}
            >
              {providerChoices.map((option) => (
                <option key={option.value} value={option.value}>
                  {formatLlmProviderLabel(option.value, t, option.label)}
                </option>
              ))}
            </Select>
          </FieldBlock>
          <FieldBlock label={t("onboarding.api.baseUrl")}>
            <TextInput
              onChange={(event) => {
                const nextBaseUrl = event.target.value;
                setDraft((current) =>
                  current
                    ? {
                        ...current,
                        llm_base_url: nextBaseUrl,
                        llm_base_urls: updateProviderValue(current.llm_base_urls, provider, nextBaseUrl),
                      }
                    : current,
                );
              }}
              placeholder="https://api.openai.com/v1"
              value={baseUrl}
            />
          </FieldBlock>
          <FieldBlock label={t("onboarding.api.apiKey")}>
            <TextInput
              onChange={(event) =>
                setDraft((current) =>
                  current
                    ? {
                        ...current,
                        llm_api_key: updateProviderValue(current.llm_api_key, provider, event.target.value),
                      }
                    : current,
                )
              }
              type="password"
              value={apiKey}
            />
          </FieldBlock>
          <FieldBlock label={t("onboarding.api.model")}>
            {modelOptions.length ? (
              <Select
                onChange={(event) =>
                  setDraft((current) =>
                    current
                      ? {
                          ...current,
                          llm_model: updateProviderValue(current.llm_model, provider, event.target.value),
                        }
                      : current,
                  )
                }
                value={model}
              >
                <option value="">{t("onboarding.common.selectPlaceholder")}</option>
                {modelOptions.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
            ) : (
              <TextInput
                onChange={(event) =>
                  setDraft((current) =>
                    current
                      ? {
                          ...current,
                          llm_model: updateProviderValue(current.llm_model, provider, event.target.value),
                        }
                      : current,
                  )
                }
                placeholder="gpt-4o-mini"
                value={model}
              />
            )}
          </FieldBlock>
        </div>
        <div className="onboarding-panel-inline-actions">
          <Button
            disabled={!baseUrl.trim() || !apiKey.trim() || !provider}
            icon={<Search aria-hidden size={16} />}
            loading={modelsMutation.isPending}
            onClick={() => modelsMutation.mutate()}
          >
            {t("onboarding.actions.fetchModels")}
          </Button>
          <AsyncButton
            disabled={!canSave}
            icon={<PlugZap aria-hidden size={16} />}
            loading={testMutation.isPending || saveMutation.isPending}
            onClick={() => testMutation.mutate()}
            variant="primary"
          >
            {t("onboarding.actions.test")}
          </AsyncButton>
        </div>
      </OnboardingTaskPanel>
      <OnboardingTaskPanel
        defaultOpen={!isBundledQwen3TtsReady}
        description={t(
          isBundledQwen3TtsReady ? "onboarding.api.voiceBundledDescription" : "onboarding.api.voiceDescription",
        )}
        title={t("onboarding.api.voiceTitle")}
      >
        <div className="onboarding-resource-note">
          <div>
            <strong>{t("onboarding.api.voiceTitle")}</strong>
            <span>{t(isBundledQwen3TtsReady ? "onboarding.api.voiceBundledHint" : "onboarding.api.bundleHint")}</span>
          </div>
          <AsyncButton
            disabled={!ttsBundleRecommendationQuery.isSuccess}
            icon={<DownloadCloud aria-hidden size={16} />}
            loading={ttsBundleMutation.isPending || saveMutation.isPending || ttsBundleRecommendationQuery.isLoading}
            onClick={() => ttsBundleMutation.mutate(ttsBundleKind)}
            variant="primary"
          >
            {t("onboarding.api.bundleButton")}
          </AsyncButton>
        </div>
        <TaskProgress logLimit={0} task={ttsBundleTask} />
      </OnboardingTaskPanel>
    </OnboardingPanelLayout>
  );
}
