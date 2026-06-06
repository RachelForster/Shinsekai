import { useEffect, useMemo, useRef, useState } from "react";
import { RotateCcw, Save } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  buildPayloadFromSchema,
  hasSchemaErrors,
  type SchemaErrorMap,
  validatePayloadFromSchema,
} from "../../entities/config/schema";
import {
  cancelTtsBundleDownload,
  configQueryKey,
  downloadTtsBundle,
  fetchLlmModels,
  getAppConfig,
  getTtsBundleRecommendation,
  saveApiConfig,
  saveSystemConfig,
  testLlmConnection,
  ttsBundleRecommendationQueryKey,
} from "../../entities/config/repository";
import type { ApiConfig, SystemConfig } from "../../entities/config/types";
import { useAppState } from "../../shared/app-state/AppState";
import { useI18n } from "../../shared/i18n";
import { resumeLastChat } from "../../entities/chat/repository";
import type { LlmModelOption, TaskSnapshot, TtsBundleDownloadResult, TtsBundleKind } from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, EmptyState, QueryErrorState, SchemaDrivenForm, useToast } from "../../shared/ui";
import { AdapterExtraSection } from "./AdapterExtraSection";
import { ApiLanguageSection } from "./ApiLanguageSection";
import { AsrSettingsSection } from "./AsrSettingsSection";
import { LlmConnectionSection } from "./LlmConnectionSection";
import { ResourceLinksSection } from "./ResourceLinksSection";
import { TtsBundleSection } from "./TtsBundleSection";
import {
  activeMapValue,
  adapterSchema,
  apiSchemaWithAdapterOptions,
  asrComputeOptions,
  asrProviderOptions,
  catalogOptions,
  containsPathQuotes,
  hasAdapterSchema,
  isTaskCancelledError,
  isTaskRunning,
  llmDefaultBaseUrls,
  llmModelFetchKey,
  llmProviderOptions,
  mergeModelOptions,
  normalizeApiAsrForSave,
  normalizeApiConfigForUi,
  normalizeAsrProvider,
  normalizeSystemAsrForSave,
  normalizeUiLanguage,
  requiresTtsServerConfig,
  resolveAsrWhisperPresetValue,
  syncCompactRatioDraft,
  thinkingUnsupported,
  updateAsrExtraConfig,
  withCurrentOption,
  VOSK_MODEL_PATH,
  type UiLanguage,
} from "./apiSettingsUtils";
import "./ApiSettingsPage.css";

type Translate = ReturnType<typeof useI18n>["t"];

function formatTtsBundleFailure(error: unknown, t: Translate) {
  const raw = error instanceof Error ? error.message : "";
  if (!raw.trim()) {
    return t("api.tts.bundleErrorUnknown");
  }
  const archiveMatch = raw.match(/archive saved at (.+)$/);
  const archive = archiveMatch?.[1]?.trim() ?? "";
  const clean = raw.replace(/; archive saved at .+$/, "").trim();
  let message: string;
  if (clean.startsWith("download:")) {
    message = t("api.tts.bundleErrorDownload", { detail: clean.slice("download:".length).trim() || clean });
  } else if (clean.startsWith("extract:")) {
    message = t("api.tts.bundleErrorExtract", { detail: clean.slice("extract:".length).trim() || clean });
  } else {
    message = clean;
  }
  return archive ? `${message}\n${t("api.tts.bundleErrorManual", { path: archive })}` : message;
}

export function ApiSettingsPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const { dispatch } = useAppState();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const ttsBundleRecommendationQuery = useQuery({
    queryFn: getTtsBundleRecommendation,
    queryKey: ttsBundleRecommendationQueryKey,
    staleTime: 300_000,
  });
  const { data, isLoading } = configQuery;
  const [draft, setDraft] = useState<ApiConfig | null>(null);
  const [systemDraft, setSystemDraft] = useState<SystemConfig | null>(null);
  const [errors, setErrors] = useState<SchemaErrorMap<ApiConfig>>({});
  const [modelOptions, setModelOptions] = useState<LlmModelOption[]>([]);
  const [llmConnectionDialog, setLlmConnectionDialog] = useState<{ kind: "error" | "success"; message: string } | null>(
    null,
  );
  const [llmConnectionOk, setLlmConnectionOk] = useState(false);
  const activeModelFetchKey = useRef<string | null>(null);
  const [ttsBundleKind, setTtsBundleKind] = useState<TtsBundleKind>("genie");
  const [ttsBundleKindTouched, setTtsBundleKindTouched] = useState(false);
  const [ttsBundleDialogOpen, setTtsBundleDialogOpen] = useState(false);
  const [ttsBundleError, setTtsBundleError] = useState<string | null>(null);
  const [ttsBundleTask, setTtsBundleTask] = useState<TaskSnapshot<TtsBundleDownloadResult> | null>(null);
  const adapterCatalog = data?.adapter_catalog;
  const apiSchema = useMemo(
    () => apiSchemaWithAdapterOptions(adapterCatalog, draft),
    [adapterCatalog, draft?.t2i_provider, draft?.tts_provider],
  );

  useEffect(() => {
    if (data?.api_config) {
      setDraft(normalizeApiConfigForUi(data.api_config));
      activeModelFetchKey.current = null;
      setModelOptions([]);
      setErrors({});
    }
  }, [data?.api_config]);

  useEffect(() => {
    if (data?.system_config) {
      setSystemDraft(data.system_config);
      dispatch({ language: normalizeUiLanguage(data.system_config.ui_language), type: "setLanguage" });
    }
  }, [data?.system_config, dispatch]);

  const saveMutation = useMutation({
    mutationFn: async (payload: { api: ApiConfig; system: SystemConfig }) => {
      const savedApi = await saveApiConfig(payload.api);
      const savedSystem = await saveSystemConfig(payload.system);
      return { api: savedApi, system: savedSystem };
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess({ system }) {
      queryClient.invalidateQueries({ queryKey: configQueryKey });
      setSystemDraft(system);
      dispatch({ language: normalizeUiLanguage(system.ui_language), type: "setLanguage" });
      showToast({ kind: "success", title: t("api.toast.saved") });
    },
  });

  const languageMutation = useMutation({
    mutationFn: async (language: UiLanguage) => {
      const baseSystem = data?.system_config ?? systemDraft;
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
      setSystemDraft((current) => (current ? { ...current, ui_language: saved.ui_language } : saved));
      queryClient.invalidateQueries({ queryKey: configQueryKey });
      dispatch({ language: normalizeUiLanguage(saved.ui_language), type: "setLanguage" });
    },
  });

  const resumeMutation = useMutation({
    mutationFn: resumeLastChat,
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.resume.tip"),
        title: t("api.resume.title"),
      });
    },
    onSuccess(snapshot) {
      showToast({ kind: "success", message: snapshot.dialogText, title: t("api.resume.title") });
    },
  });

  const modelFetchMutation = useMutation({
    mutationFn: (input: { apiKey: string; baseUrl: string; fetchKey: string; provider: string }) =>
      fetchLlmModels({
        apiKey: input.apiKey,
        baseUrl: input.baseUrl,
        provider: input.provider,
      }),
    onError(error, input) {
      if (activeModelFetchKey.current !== input.fetchKey) {
        return;
      }
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.llm.fetchFailed"),
        title: t("api.llm.fetchTitle"),
      });
    },
    onMutate(input) {
      activeModelFetchKey.current = input.fetchKey;
    },
    onSuccess(options, input) {
      if (activeModelFetchKey.current !== input.fetchKey) {
        return;
      }
      setModelOptions(options);
      if (!options.length) {
        showToast({ kind: "error", message: t("api.llm.fetchEmpty"), title: t("api.llm.fetchTitle") });
        return;
      }
      setDraft((current) => {
        if (!current) {
          return current;
        }
        if (llmModelFetchKey(current) !== input.fetchKey) {
          return current;
        }
        const model = activeMapValue(current.llm_model, current.llm_provider);
        if (model) {
          return current;
        }
        return {
          ...current,
          llm_model: { ...current.llm_model, [current.llm_provider]: options[0].id },
        };
      });
      showToast({
        kind: "success",
        message: t("api.llm.fetchDone", { count: options.length }),
        title: t("api.llm.fetchTitle"),
      });
    },
  });

  const llmConnectionTestMutation = useMutation({
    mutationFn: (input: { apiKey: string; baseUrl: string; model: string; provider: string }) =>
      testLlmConnection(input),
    onError(error) {
      setLlmConnectionOk(false);
      setLlmConnectionDialog({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.llm.testFailed"),
      });
    },
    onSuccess(result) {
      setLlmConnectionOk(true);
      setLlmConnectionDialog({
        kind: "success",
        message: result.message || t("api.llm.testDone"),
      });
    },
  });

  const ttsBundleMutation = useMutation({
    mutationFn: () => downloadTtsBundle({ kind: ttsBundleKind }, { onTaskUpdate: setTtsBundleTask }),
    onError(error) {
      if (isTaskCancelledError(error)) {
        return;
      }
      const message = formatTtsBundleFailure(error, t);
      setTtsBundleError(message);
      showToast({
        kind: "error",
        message,
        title: t("api.tts.bundleTitle"),
      });
    },
    onMutate() {
      setTtsBundleError(null);
      setTtsBundleTask(null);
    },
    onSuccess(result) {
      setTtsBundleDialogOpen(false);
      setTtsBundleError(null);
      setDraft((current) =>
        current
          ? {
              ...current,
              gpt_sovits_api_path: result.path,
              tts_provider: result.provider,
            }
          : current,
      );
      showToast({
        kind: "success",
        message: t("api.tts.bundleDone", { path: result.path }),
        title: t("api.tts.bundleTitle"),
      });
    },
  });

  const ttsBundleCancelMutation = useMutation({
    mutationFn: () => {
      if (!ttsBundleTask?.id) {
        throw new Error(t("api.tts.bundleCancelUnavailable"));
      }
      return cancelTtsBundleDownload(ttsBundleTask.id);
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.tts.bundleCancelFailed"),
        title: t("api.tts.bundleTitle"),
      });
    },
    onSuccess(task) {
      setTtsBundleTask(task);
      showToast({
        kind: "success",
        title: task.status === "cancelled" ? t("api.tts.bundleCancelled") : t("api.tts.bundleCancelRequested"),
      });
    },
  });

  useEffect(() => {
    const recommendation = ttsBundleRecommendationQuery.data;
    if (!recommendation || ttsBundleKindTouched || ttsBundleMutation.isPending) {
      return;
    }
    setTtsBundleKind(recommendation.kind);
  }, [ttsBundleKindTouched, ttsBundleMutation.isPending, ttsBundleRecommendationQuery.data]);

  if (configQuery.isError) {
    return (
      <QueryErrorState
        body={t("api.error.saveFallback")}
        error={configQuery.error}
        onRetry={() => void configQuery.refetch()}
        retryLabel={t("common.retry")}
        title={t("common.operationFailed")}
      />
    );
  }

  if (isLoading || !draft || !systemDraft) {
    return <EmptyState title={t("api.loading")} />;
  }

  const activeModel = activeMapValue(draft.llm_model, draft.llm_provider);
  const activeApiKey = activeMapValue(draft.llm_api_key, draft.llm_provider);
  const availableModelOptions = mergeModelOptions(modelOptions, activeModel ? [{ id: activeModel, tags: [] }] : []);
  const selectedOption = availableModelOptions.find((option) => option.id === activeModel);
  const modelCandidateListId = "llm-model-candidates";
  const canCancelTtsBundleDownload =
    ttsBundleMutation.isPending && isTaskRunning(ttsBundleTask) && !ttsBundleTask?.cancelRequested;
  const openTtsBundleDialog = () => {
    setTtsBundleDialogOpen(true);
    setTtsBundleError(null);
    void ttsBundleRecommendationQuery.refetch();
  };
  const activeAsrProvider = normalizeAsrProvider(systemDraft.asr_provider);
  const asrProviderSelectOptions = withCurrentOption(
    adapterCatalog?.asr?.length
      ? adapterCatalog.asr.map((option) => ({
          label: option.label || option.value,
          value: normalizeAsrProvider(option.value),
        }))
      : [...asrProviderOptions],
    activeAsrProvider,
  );
  const showWhisperFields = activeAsrProvider !== "vosk";
  const whisperPresetValue = resolveAsrWhisperPresetValue(systemDraft.asr_whisper_model_size);
  const customWhisperModel = whisperPresetValue === "__custom__";
  const currentAsrCompute = String(systemDraft.asr_whisper_compute_type ?? "");
  const asrComputeSelectOptions = withCurrentOption(
    asrComputeOptions.map((option) => ({
      label: "label" in option ? option.label : t(option.labelKey),
      value: option.value,
    })),
    currentAsrCompute,
  );
  const activeAsrSchema =
    adapterCatalog?.asr?.find((option) => normalizeAsrProvider(option.value) === activeAsrProvider)?.schema ?? {};
  const voskModelPath = String(draft.asr_extra_configs?.vosk?.model_path ?? VOSK_MODEL_PATH);

  const updateDraft = (patch: Partial<ApiConfig>) => {
    setDraft({ ...draft, ...patch });
  };

  const resetLlmConnectionState = () => {
    setLlmConnectionOk(false);
  };

  const updateDraftAndResetModelFetch = (patch: Partial<ApiConfig>) => {
    if (Object.prototype.hasOwnProperty.call(patch, "llm_base_url")) {
      activeModelFetchKey.current = null;
      setModelOptions([]);
      resetLlmConnectionState();
    }
    updateDraft(patch);
  };

  const updateSystemDraft = (patch: Partial<SystemConfig>) => {
    setSystemDraft({ ...systemDraft, ...patch });
  };

  const handleLanguageChange = (language: UiLanguage) => {
    setSystemDraft({ ...systemDraft, ui_language: language });
    languageMutation.mutate(language);
  };

  const updateProvider = (provider: string) => {
    activeModelFetchKey.current = null;
    setModelOptions([]);
    resetLlmConnectionState();
    setDraft({
      ...draft,
      llm_base_url: llmDefaultBaseUrls[provider] ?? "",
      llm_provider: provider,
    });
  };

  const updateProviderMap = (key: "llm_api_key" | "llm_model", value: string) => {
    if (key === "llm_api_key") {
      activeModelFetchKey.current = null;
      setModelOptions([]);
    }
    resetLlmConnectionState();
    const nextExtra =
      key === "llm_model" && thinkingUnsupported(value)
        ? {
            llm_extra_configs: {
              ...draft.llm_extra_configs,
              [draft.llm_provider]: {
                ...(draft.llm_extra_configs?.[draft.llm_provider] ?? {}),
                thinking_enabled: false,
              },
            },
          }
        : {};
    setDraft({
      ...draft,
      [key]: {
        ...draft[key],
        [draft.llm_provider]: value,
      },
      ...nextExtra,
    });
  };

  const updateAdapterExtra = (
    bucket: "llm_extra_configs" | "t2i_extra_configs" | "tts_extra_configs",
    provider: string,
    key: string,
    value: unknown,
  ) => {
    setDraft({
      ...draft,
      [bucket]: {
        ...draft[bucket],
        [provider]: {
          ...(draft[bucket]?.[provider] ?? {}),
          [key]: value,
        },
      },
    });
  };

  const handleFetchModels = () => {
    if (!draft.llm_base_url.trim() || !activeApiKey.trim()) {
      showToast({ kind: "error", message: t("api.llm.fetchMissing"), title: t("api.llm.fetchTitle") });
      return;
    }
    modelFetchMutation.mutate({
      apiKey: activeApiKey,
      baseUrl: draft.llm_base_url,
      fetchKey: llmModelFetchKey(draft),
      provider: draft.llm_provider,
    });
  };

  const handleTestLlmConnection = () => {
    if (!draft.llm_base_url.trim() || !activeApiKey.trim()) {
      setLlmConnectionOk(false);
      setLlmConnectionDialog({ kind: "error", message: t("api.llm.fetchMissing") });
      return;
    }
    if (!activeModel.trim()) {
      setLlmConnectionOk(false);
      setLlmConnectionDialog({ kind: "error", message: t("api.llm.testMissingModel") });
      return;
    }
    llmConnectionTestMutation.mutate({
      apiKey: activeApiKey,
      baseUrl: draft.llm_base_url,
      model: activeModel,
      provider: draft.llm_provider,
    });
  };

  const updateAsrExtra = (provider: string, key: string, value: unknown) => {
    setDraft(updateAsrExtraConfig(draft, provider, key, value));
  };

  const llmProviderSelectOptions = withCurrentOption(
    catalogOptions(adapterCatalog?.llm, llmProviderOptions),
    draft.llm_provider,
  );
  const llmExtraSchema = adapterSchema(adapterCatalog?.llm, draft.llm_provider);
  const ttsExtraSchema = adapterSchema(adapterCatalog?.tts, draft.tts_provider);
  const t2iExtraSchema = adapterSchema(adapterCatalog?.t2i, draft.t2i_provider);

  const handleSave = () => {
    const nextErrors = validatePayloadFromSchema(apiSchema, draft);
    setErrors(nextErrors);
    if (hasSchemaErrors(nextErrors)) {
      showToast({ kind: "error", message: t("common.fixInvalidFields"), title: t("common.validationFailed") });
      return;
    }
    if (!draft.llm_provider.trim() || !draft.llm_base_url.trim() || !activeApiKey.trim() || !activeModel.trim()) {
      showToast({ kind: "error", message: t("api.llm.required"), title: t("common.validationFailed") });
      return;
    }
    if (containsPathQuotes(draft.llm_base_url)) {
      showToast({ kind: "error", message: "LLM API 基础网址不能包含引号。", title: t("common.validationFailed") });
      return;
    }
    if (requiresTtsServerConfig(draft.tts_provider)) {
      if (!draft.gpt_sovits_url.trim() || !draft.gpt_sovits_api_path.trim()) {
        showToast({
          kind: "error",
          message: "当前 TTS 引擎需要填写 URL 和服务启动路径。",
          title: t("common.validationFailed"),
        });
        return;
      }
      if (containsPathQuotes(draft.gpt_sovits_url) || containsPathQuotes(draft.gpt_sovits_api_path)) {
        showToast({
          kind: "error",
          message: "TTS URL 和服务启动路径不能包含引号。",
          title: t("common.validationFailed"),
        });
        return;
      }
    }
    let nextConfig: ApiConfig = {
      ...draft,
      ...buildPayloadFromSchema(apiSchema, draft),
    };
    const nextSystem = normalizeSystemAsrForSave(systemDraft);
    nextConfig = normalizeApiAsrForSave(nextConfig, nextSystem);
    if (thinkingUnsupported(activeModel)) {
      nextConfig.llm_extra_configs = {
        ...nextConfig.llm_extra_configs,
        [nextConfig.llm_provider]: {
          ...(nextConfig.llm_extra_configs?.[nextConfig.llm_provider] ?? {}),
          thinking_enabled: false,
        },
      };
    }
    saveMutation.mutate({ api: nextConfig, system: nextSystem });
  };

  return (
    <div className="page api-page">
      <header className="page__header api-page__header">
        <div>
          <h1 className="page__title">{t("api.title")}</h1>
          <p className="page__description">{t("api.description")}</p>
        </div>
        <div className="page__actions">
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={saveMutation.isPending}
            onClick={handleSave}
            variant="primary"
          >
            {t("common.save")}
          </AsyncButton>
          <AsyncButton
            icon={<RotateCcw aria-hidden className="button__icon" />}
            loading={resumeMutation.isPending}
            onClick={() => resumeMutation.mutate()}
            tooltip={t("api.resume.tip")}
          >
            {t("api.resume.btn")}
          </AsyncButton>
        </div>
      </header>
      <ApiLanguageSection
        disabled={languageMutation.isPending}
        onChange={handleLanguageChange}
        systemDraft={systemDraft}
      />
      <LlmConnectionSection
        activeApiKey={activeApiKey}
        activeModel={activeModel}
        availableModelOptions={availableModelOptions}
        disabled={saveMutation.isPending}
        draft={draft}
        connectionOk={llmConnectionOk}
        connectionTestPending={llmConnectionTestMutation.isPending}
        fetchModelsPending={modelFetchMutation.isPending}
        llmExtraSchema={llmExtraSchema}
        llmProviderSelectOptions={llmProviderSelectOptions}
        modelCandidateListId={modelCandidateListId}
        modelUnsupportedThinking={thinkingUnsupported(activeModel)}
        onAdapterExtraChange={(key, value) => updateAdapterExtra("llm_extra_configs", draft.llm_provider, key, value)}
        onDraftPatch={updateDraftAndResetModelFetch}
        onFetchModels={handleFetchModels}
        onTestConnection={handleTestLlmConnection}
        onProviderChange={updateProvider}
        onProviderMapChange={updateProviderMap}
        selectedOption={selectedOption}
      />
      <SchemaDrivenForm
        collapsedGroupIds={["llm"]}
        disabled={saveMutation.isPending}
        errors={errors}
        groups={apiSchema.filter((g) => g.id === "llm")}
        onChange={(nextDraft) => setDraft(syncCompactRatioDraft(nextDraft))}
        value={draft}
      />
      <TtsBundleSection
        canCancelDownload={canCancelTtsBundleDownload}
        cancelPending={ttsBundleCancelMutation.isPending}
        dialogOpen={ttsBundleDialogOpen}
        downloadPending={ttsBundleMutation.isPending}
        error={ttsBundleError}
        kind={ttsBundleKind}
        onCancelDownload={() => ttsBundleCancelMutation.mutate()}
        onCloseDialog={() => setTtsBundleDialogOpen(false)}
        onKindChange={(kind) => {
          setTtsBundleKindTouched(true);
          setTtsBundleKind(kind);
        }}
        onOpenDialog={openTtsBundleDialog}
        onStartDownload={() => ttsBundleMutation.mutate()}
        recommendation={ttsBundleRecommendationQuery.data}
        recommendationError={ttsBundleRecommendationQuery.isError}
        recommendationLoading={ttsBundleRecommendationQuery.isLoading}
        savePending={saveMutation.isPending}
        task={ttsBundleTask}
      />
      <SchemaDrivenForm
        collapsedGroupIds={["t2i"]}
        disabled={saveMutation.isPending}
        errors={errors}
        groups={apiSchema.filter((g) => g.id !== "llm")}
        onChange={(nextDraft) => setDraft(syncCompactRatioDraft(nextDraft))}
        value={draft}
      />
      <AsrSettingsSection
        activeAsrProvider={activeAsrProvider}
        activeAsrSchema={activeAsrSchema}
        asrComputeSelectOptions={asrComputeSelectOptions}
        asrProviderSelectOptions={asrProviderSelectOptions}
        currentAsrCompute={currentAsrCompute}
        customWhisperModel={customWhisperModel}
        disabled={saveMutation.isPending}
        draft={draft}
        onAsrExtraChange={updateAsrExtra}
        onSystemPatch={updateSystemDraft}
        showWhisperFields={showWhisperFields}
        systemDraft={systemDraft}
        voskModelPath={voskModelPath}
        whisperPresetValue={whisperPresetValue}
      />
      {hasAdapterSchema(ttsExtraSchema) ? (
        <AdapterExtraSection
          disabled={saveMutation.isPending}
          onChange={(key, value) => updateAdapterExtra("tts_extra_configs", draft.tts_provider, key, value)}
          schema={ttsExtraSchema}
          title={`${draft.tts_provider} 扩展参数`}
          values={draft.tts_extra_configs?.[draft.tts_provider] ?? {}}
        />
      ) : null}
      {hasAdapterSchema(t2iExtraSchema) ? (
        <AdapterExtraSection
          disabled={saveMutation.isPending}
          onChange={(key, value) => updateAdapterExtra("t2i_extra_configs", draft.t2i_provider, key, value)}
          schema={t2iExtraSchema}
          title={`${draft.t2i_provider} 扩展参数`}
          values={draft.t2i_extra_configs?.[draft.t2i_provider] ?? {}}
        />
      ) : null}
      <ResourceLinksSection />
      <Dialog
        closeLabel={t("common.close")}
        footer={
          <Button onClick={() => setLlmConnectionDialog(null)} variant="primary">
            {t("common.close")}
          </Button>
        }
        onClose={() => setLlmConnectionDialog(null)}
        open={llmConnectionDialog !== null}
        title={t("api.llm.testTitle")}
      >
        <div className="api-page__llm-test-dialog-body" data-kind={llmConnectionDialog?.kind ?? "error"}>
          {llmConnectionDialog?.message ?? ""}
        </div>
      </Dialog>
    </div>
  );
}
