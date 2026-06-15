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
import type { TaskSnapshot, TtsBundleDownloadResult } from "../../../shared/platform/types";
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
import type { OnboardingCopy } from "../onboardingCopy";

interface ApiSetupPanelProps {
  copy: OnboardingCopy;
}

function activeProviderValue(record: Record<string, string> | undefined, provider: string) {
  return record?.[provider] ?? "";
}

function updateProviderValue(record: Record<string, string> | undefined, provider: string, value: string) {
  return { ...(record ?? {}), [provider]: value };
}

function withApiDraftValue<K extends keyof ApiConfig>(draft: ApiConfig | null, key: K, value: ApiConfig[K]) {
  return draft ? { ...draft, [key]: value } : draft;
}

export function ApiSetupPanel({ copy }: ApiSetupPanelProps) {
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
      setDraft(configQuery.data.api_config);
    }
  }, [configQuery.data?.api_config]);

  const providerOptions = configQuery.data?.adapter_catalog?.llm ?? [];
  const provider = draft?.llm_provider || providerOptions[0]?.value || "";
  const ttsBundleKind = ttsBundleRecommendationQuery.data?.kind ?? "genie";
  const apiKey = activeProviderValue(draft?.llm_api_key, provider);
  const model = activeProviderValue(draft?.llm_model, provider);
  const baseUrl = draft?.llm_base_url ?? "";
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
      showToast({ kind: "error", message: error instanceof Error ? error.message : "", title: copy.toastFailed });
    },
    onSuccess(saved) {
      queryClient.setQueryData(configQueryKey, (current: typeof configQuery.data) =>
        current ? { ...current, api_config: saved } : current,
      );
      showToast({ kind: "success", title: copy.actions.saved });
    },
  });

  const ttsBundleMutation = useMutation({
    mutationFn: () => downloadTtsBundle({ kind: ttsBundleKind }, { onTaskUpdate: setTtsBundleTask }),
    onError(error) {
      showToast({ kind: "error", message: error instanceof Error ? error.message : "", title: copy.toastFailed });
    },
    onMutate() {
      setTtsBundleTask(null);
    },
    onSuccess(result) {
      if (draft) {
        const next = {
          ...draft,
          gpt_sovits_api_path: result.path,
          gpt_sovits_url: result.path,
          tts_provider: result.provider,
        };
        setDraft(next);
        saveMutation.mutate(next);
      }
      showToast({ kind: "success", message: copy.api.bundleDone, title: copy.api.voiceTitle });
    },
  });

  const modelsMutation = useMutation({
    mutationFn: () => fetchLlmModels({ apiKey, baseUrl, provider }),
    onError(error) {
      showToast({ kind: "error", message: error instanceof Error ? error.message : "", title: copy.toastFailed });
    },
    onSuccess(result) {
      const ids = result.map((item) => item.id).filter(Boolean);
      setModelOptions(ids);
      showToast({ kind: "success", message: String(ids.length), title: copy.actions.fetchModels });
    },
  });

  const testMutation = useMutation({
    mutationFn: () => testLlmConnection({ apiKey, baseUrl, model, provider }),
    onError(error) {
      showToast({ kind: "error", message: error instanceof Error ? error.message : "", title: copy.toastFailed });
    },
    onSuccess() {
      showToast({ kind: "success", title: copy.api.connected });
      if (draft) {
        saveMutation.mutate(draft);
      }
    },
  });

  if (configQuery.isLoading || !draft) {
    return <EmptyState title={copy.common.loading} />;
  }

  if (configQuery.isError) {
    return (
      <QueryErrorState
        error={configQuery.error}
        onRetry={() => void configQuery.refetch()}
        retryLabel={copy.actions.retry}
        title={copy.toastFailed}
      />
    );
  }

  return (
    <OnboardingPanelLayout
      copy={copy}
      description={copy.api.description}
      title={copy.api.title}
      actions={
        <AsyncButton
          disabled={!canSave}
          icon={<Save aria-hidden size={16} />}
          loading={saveMutation.isPending}
          onClick={() => draft && saveMutation.mutate(draft)}
        >
          {copy.actions.save}
        </AsyncButton>
      }
    >
      <OnboardingTaskPanel defaultOpen description={copy.api.description} title={copy.api.title}>
        <div className="onboarding-form-grid">
          <FieldBlock label={copy.api.provider}>
            <Select
              onChange={(event) =>
                setDraft(
                  (current) => withApiDraftValue(current, "llm_provider", event.target.value) as ApiConfig | null,
                )
              }
              value={provider}
            >
              {providerChoices.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </FieldBlock>
          <FieldBlock label={copy.api.baseUrl}>
            <TextInput
              onChange={(event) =>
                setDraft(
                  (current) => withApiDraftValue(current, "llm_base_url", event.target.value) as ApiConfig | null,
                )
              }
              placeholder="https://api.openai.com/v1"
              value={baseUrl}
            />
          </FieldBlock>
          <FieldBlock label={copy.api.apiKey}>
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
          <FieldBlock label={copy.api.model}>
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
                <option value="">{copy.common.selectPlaceholder}</option>
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
            {copy.actions.fetchModels}
          </Button>
          <AsyncButton
            disabled={!canSave}
            icon={<PlugZap aria-hidden size={16} />}
            loading={testMutation.isPending || saveMutation.isPending}
            onClick={() => testMutation.mutate()}
            variant="primary"
          >
            {copy.actions.test}
          </AsyncButton>
        </div>
      </OnboardingTaskPanel>
      <OnboardingTaskPanel defaultOpen description={copy.api.voiceDescription} title={copy.api.voiceTitle}>
        <div className="onboarding-resource-note">
          <div>
            <strong>{copy.api.voiceTitle}</strong>
            <span>{copy.api.bundleHint}</span>
          </div>
          <AsyncButton
            icon={<DownloadCloud aria-hidden size={16} />}
            loading={ttsBundleMutation.isPending || saveMutation.isPending}
            onClick={() => ttsBundleMutation.mutate()}
            variant="primary"
          >
            {copy.api.bundleButton}
          </AsyncButton>
        </div>
        <TaskProgress logLimit={0} task={ttsBundleTask} />
      </OnboardingTaskPanel>
    </OnboardingPanelLayout>
  );
}
