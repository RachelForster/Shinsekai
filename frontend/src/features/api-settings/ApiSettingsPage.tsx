import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, DownloadCloud, ExternalLink, RefreshCw } from "lucide-react";

import {
  adapterExtraSchemaToFormGroup,
  buildPayloadFromSchema,
  apiConfigFormSchema,
  defaultAdapterExtraValue,
  hasSchemaErrors,
  llmDefaultBaseUrls,
  llmProviderOptions,
  type AdapterExtraFormValues,
  type SchemaErrorMap,
  validatePayloadFromSchema,
} from "../../entities/config/schema";
import {
  configQueryKey,
  downloadTtsBundle,
  fetchLlmModels,
  getAppConfig,
  saveApiConfig,
  saveSystemConfig,
} from "../../entities/config/repository";
import type {
  AdapterCatalog,
  AdapterExtraFieldSchema,
  AdapterOption,
  ApiConfig,
  SystemConfig,
} from "../../entities/config/types";
import { useAppState } from "../../shared/app-state/AppState";
import { useI18n } from "../../shared/i18n";
import { openExternal } from "../../entities/files/repository";
import { resumeLastChat } from "../../entities/chat/repository";
import type { FormGroupSchema } from "../../shared/ui/formSchema";
import type { LlmModelOption, TaskSnapshot, TtsBundleDownloadResult, TtsBundleKind } from "../../shared/platform/types";
import {
  AsyncButton,
  Button,
  EmptyState,
  IconButton,
  QueryErrorState,
  SchemaDrivenForm,
  SchemaFieldGrid,
  Select,
  TextInput,
  useToast,
} from "../../shared/ui";

type UiLanguage = "zh_CN" | "en" | "ja";

const resourceLinks = [
  ["api.links.link1", "https://github.com/RVC-Boss/GPT-SoVITS"],
  [
    "api.links.link2",
    "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604.7z",
  ],
  [
    "api.links.link3",
    "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604-nvidia50.7z",
  ],
  ["api.links.link4", "https://github.com/High-Logic/Genie-TTS"],
  [
    "api.links.link5",
    "https://www.modelscope.cn/models/twillzxy/genie-tts-server/resolve/master/Genie-TTS%20Server.7z",
  ],
] as const;

const VOSK_MODEL_PATH = "./assets/system/models/vosk-model-small-cn-0.22";
const VOSK_MODELS_URL = "https://alphacephei.com/vosk/models";

const asrProviderOptions = [
  { label: "Vosk", value: "vosk" },
  { label: "faster-whisper", value: "faster_whisper" },
  { label: "RealtimeSTT", value: "realtime_stt" },
] as const;

const asrWhisperModelPresets = [
  "tiny",
  "base",
  "small",
  "medium",
  "large-v1",
  "large-v2",
  "large-v3",
  "distil-large-v2",
  "distil-large-v3",
] as const;

const asrComputeOptions = [
  { labelKey: "system.asr.computeAuto", value: "" },
  { label: "int8", value: "int8" },
  { label: "float16", value: "float16" },
  { label: "int8_float16", value: "int8_float16" },
  { label: "int16", value: "int16" },
  { label: "float32", value: "float32" },
] as const;

function withCurrentOption(options: Array<{ label: string; value: string }>, currentValue: string) {
  const cleanValue = String(currentValue || "").trim();
  if (!cleanValue || options.some((option) => option.value === cleanValue)) {
    return options;
  }
  return [...options, { label: cleanValue, value: cleanValue }];
}

function normalizeUiLanguage(language: string): UiLanguage {
  return language === "en" || language === "ja" ? language : "zh_CN";
}

function normalizeAsrProvider(provider: string) {
  const normalized = (provider || "vosk").trim().toLowerCase().replace(/-/g, "_");
  if (normalized === "fasterwhisper" || normalized === "whisper") {
    return "faster_whisper";
  }
  if (normalized === "realtimestt") {
    return "realtime_stt";
  }
  return normalized || "vosk";
}

function resolveAsrWhisperPresetValue(model: string) {
  const value = (model || "small").trim();
  return (asrWhisperModelPresets as readonly string[]).includes(value) ? value : "__custom__";
}

function updateAsrExtraConfig(apiConfig: ApiConfig, provider: string, key: string, value: unknown): ApiConfig {
  const providerKey = normalizeAsrProvider(provider);
  return {
    ...apiConfig,
    asr_extra_configs: {
      ...(apiConfig.asr_extra_configs ?? {}),
      [providerKey]: {
        ...((apiConfig.asr_extra_configs ?? {})[providerKey] ?? {}),
        [key]: value,
      },
    },
  };
}

function normalizeSystemAsrForSave(systemConfig: SystemConfig): SystemConfig {
  return {
    ...systemConfig,
    asr_provider: normalizeAsrProvider(systemConfig.asr_provider),
    asr_whisper_compute_type: String(systemConfig.asr_whisper_compute_type ?? "").trim(),
    asr_whisper_device: String(systemConfig.asr_whisper_device || "auto")
      .trim()
      .toLowerCase(),
    asr_whisper_model_size: String(systemConfig.asr_whisper_model_size || "small").trim() || "small",
  };
}

function normalizeApiAsrForSave(apiConfig: ApiConfig, systemConfig: SystemConfig): ApiConfig {
  const provider = normalizeAsrProvider(systemConfig.asr_provider);
  if (provider !== "vosk") {
    return apiConfig;
  }
  const current = (apiConfig.asr_extra_configs ?? {}).vosk ?? {};
  const modelPath = String(current.model_path ?? "").trim() || VOSK_MODEL_PATH;
  return updateAsrExtraConfig(apiConfig, "vosk", "model_path", modelPath);
}

function catalogOptions(
  options: AdapterOption[] | undefined,
  fallback: ReadonlyArray<{ label: string; value: string }>,
) {
  if (!options?.length) {
    return fallback.map((option) => ({ label: option.label, value: option.value }));
  }
  return options.map((option) => ({ label: option.label || option.value, value: option.value }));
}

function adapterSchema(options: AdapterOption[] | undefined, value: string) {
  return options?.find((option) => option.value === value)?.schema ?? {};
}

function apiSchemaWithAdapterOptions(
  catalog: AdapterCatalog | undefined,
  draft: ApiConfig | null,
): Array<FormGroupSchema<ApiConfig>> {
  const ttsOptions = withCurrentOption(
    catalogOptions(catalog?.tts, [
      { label: "不使用", value: "none" },
      { label: "Genie TTS", value: "genie-tts" },
      { label: "GPT SoVITS", value: "gpt-sovits" },
      { label: "IndexTTS", value: "index-tts" },
      { label: "CosyVoice", value: "cosyvoice" },
    ]),
    draft?.tts_provider ?? "",
  );
  const t2iOptions = withCurrentOption(
    catalogOptions(catalog?.t2i, [
      { label: "ComfyUI", value: "comfyui" },
      { label: "Stable Diffusion", value: "stable diffusion" },
    ]),
    draft?.t2i_provider ?? "",
  );

  return apiConfigFormSchema
    .map((group) => ({
      ...group,
      fields: group.fields
        .filter((field) => field.name !== "is_streaming")
        .map((field) => {
          if (field.name === "tts_provider") {
            return { ...field, options: ttsOptions };
          }
          if (field.name === "t2i_provider") {
            return { ...field, options: t2iOptions };
          }
          return field;
        }),
    }))
    .filter((group) => group.fields.length > 0);
}

function activeMapValue(map: Record<string, string>, provider: string) {
  return map?.[provider] ?? "";
}

function normalizeApiConfigForUi(config: ApiConfig): ApiConfig {
  const provider = (config.llm_provider || "Deepseek").trim() || "Deepseek";
  return {
    ...config,
    llm_api_key: config.llm_api_key ?? {},
    llm_base_url: String(config.llm_base_url || "").trim() || llmDefaultBaseUrls[provider] || "",
    llm_model: config.llm_model ?? {},
    llm_provider: provider,
  };
}

function mergeModelOptions(...groups: Array<LlmModelOption[] | undefined>) {
  const out: LlmModelOption[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    for (const option of group ?? []) {
      const id = String(option.id || "").trim();
      if (!id || seen.has(id)) {
        continue;
      }
      seen.add(id);
      out.push({ id, tags: option.tags ?? [] });
    }
  }
  return out;
}

function llmModelFetchKey(config: ApiConfig) {
  return JSON.stringify([
    config.llm_provider,
    String(config.llm_base_url || "").trim(),
    activeMapValue(config.llm_api_key, config.llm_provider),
  ]);
}

function capabilityLabel(tag: string) {
  const labels: Record<string, string> = {
    audio: "Audio",
    file: "File",
    image_out: "Image",
    no_access: "No access",
    not_found: "Missing",
    text: "Text",
    unknown: "Unknown",
    video: "Video",
    vision: "Vision",
  };
  return labels[tag] ?? tag;
}

function thinkingUnsupported(model: string) {
  return ["deepseek-v4-flash", "deepseek-chat"].includes(model.trim().toLowerCase());
}

function EditableModelSelect({
  disabled,
  id,
  onChange,
  options,
  placeholder,
  value,
}: {
  disabled: boolean;
  id: string;
  onChange: (value: string) => void;
  options: LlmModelOption[];
  placeholder: string;
  value: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const listboxId = `${id}-listbox`;
  const query = value.trim().toLowerCase();
  const visibleOptions = query ? options.filter((option) => option.id.toLowerCase().includes(query)) : options;
  const menuOptions = visibleOptions.length ? visibleOptions : options;

  useEffect(() => {
    if (!open) {
      return;
    }
    const closeIfOutside = (target: EventTarget | null) => {
      if (!rootRef.current?.contains(target as Node)) {
        setOpen(false);
      }
    };
    const handlePointerDown = (event: PointerEvent) => closeIfOutside(event.target);
    const handleFocusIn = (event: FocusEvent) => closeIfOutside(event.target);
    const handleWindowBlur = () => setOpen(false);
    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("focusin", handleFocusIn, true);
    window.addEventListener("blur", handleWindowBlur);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("focusin", handleFocusIn, true);
      window.removeEventListener("blur", handleWindowBlur);
    };
  }, [open]);

  useEffect(() => {
    if (!options.length) {
      setOpen(false);
    }
  }, [options.length]);

  const selectOption = (modelId: string) => {
    onChange(modelId);
    setOpen(false);
  };

  return (
    <div className="editable-combo" ref={rootRef}>
      <div className="editable-combo__control">
        <TextInput
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded={open}
          aria-haspopup="listbox"
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onFocus={() => {
            if (options.length) {
              setOpen(true);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" && options.length) {
              event.preventDefault();
              setOpen(true);
            }
            if (event.key === "Escape") {
              setOpen(false);
            }
            if (event.key === "Enter" && open && menuOptions[0]) {
              event.preventDefault();
              selectOption(menuOptions[0].id);
            }
          }}
          placeholder={placeholder}
          role="combobox"
          value={value}
        />
        <IconButton
          aria-expanded={open}
          className="editable-combo__button"
          disabled={disabled || !options.length}
          label={placeholder}
          onClick={() => setOpen((current) => (options.length ? !current : false))}
        >
          <ChevronDown aria-hidden className="icon-button__icon" />
        </IconButton>
      </div>
      {open && options.length ? (
        <div className="editable-combo__menu" id={listboxId} role="listbox">
          {menuOptions.map((option) => (
            <button
              aria-selected={option.id === value}
              className="editable-combo__option"
              key={option.id}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectOption(option.id)}
              role="option"
              type="button"
            >
              <span className="editable-combo__option-main">
                <span className="editable-combo__option-id">{option.id}</span>
                {option.tags.length ? (
                  <span className="editable-combo__option-tags">
                    {option.tags.map((tag) => (
                      <span className="llm-model-badge llm-model-badge--ghost" data-tag={tag} key={tag}>
                        {capabilityLabel(tag)}
                      </span>
                    ))}
                  </span>
                ) : null}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function requiresTtsServerConfig(provider: string) {
  return ["genie-tts", "gpt-sovits"].includes(provider.trim().toLowerCase());
}

function containsPathQuotes(value: string) {
  return value.includes('"') || value.includes("'");
}

function hasAdapterSchema(schema: Record<string, AdapterExtraFieldSchema>) {
  return Object.keys(schema).length > 0;
}

function AdapterExtraForm({
  disabled,
  modelUnsupportedThinking = false,
  onChange,
  schema,
  values,
}: {
  disabled?: boolean;
  modelUnsupportedThinking?: boolean;
  onChange: (key: string, value: unknown) => void;
  schema: Record<string, AdapterExtraFieldSchema>;
  values: Record<string, unknown>;
}) {
  const entries = Object.entries(schema);
  if (!entries.length) {
    return null;
  }

  const disabledKeys = modelUnsupportedThinking ? ["thinking_enabled", "reasoning_effort"] : [];
  const group = adapterExtraSchemaToFormGroup({
    disabledKeys,
    disabledReason: "该模型不支持思考模式。",
    id: "adapter-extra",
    schema,
    title: "扩展参数",
  });
  const displayValues = entries.reduce<AdapterExtraFormValues>((accumulator, [key, field]) => {
    accumulator[key] = values[key] ?? defaultAdapterExtraValue(field);
    if (modelUnsupportedThinking && key === "thinking_enabled") {
      accumulator[key] = false;
    }
    return accumulator;
  }, {});

  return (
    <SchemaFieldGrid
      className="api-extra-grid"
      disabled={disabled}
      group={group}
      onChange={(nextValues) => {
        for (const [key, value] of Object.entries(nextValues)) {
          if (!Object.is(value, displayValues[key])) {
            onChange(key, value);
            return;
          }
        }
      }}
      value={displayValues}
    />
  );
}

export function ApiSettingsPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const { dispatch } = useAppState();
  const configQuery = useQuery({ queryFn: getAppConfig, queryKey: configQueryKey });
  const { data, isLoading } = configQuery;
  const [draft, setDraft] = useState<ApiConfig | null>(null);
  const [systemDraft, setSystemDraft] = useState<SystemConfig | null>(null);
  const [errors, setErrors] = useState<SchemaErrorMap<ApiConfig>>({});
  const [modelOptions, setModelOptions] = useState<LlmModelOption[]>([]);
  const activeModelFetchKey = useRef<string | null>(null);
  const [ttsBundleKind, setTtsBundleKind] = useState<TtsBundleKind>("genie");
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

  const ttsBundleMutation = useMutation({
    mutationFn: () => downloadTtsBundle({ kind: ttsBundleKind }, { onTaskUpdate: setTtsBundleTask }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("api.tts.bundleFailed"),
        title: t("api.tts.bundleTitle"),
      });
    },
    onMutate() {
      setTtsBundleTask(null);
    },
    onSuccess(result) {
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
  const ttsBundleProgress = ttsBundleTask?.progress == null ? null : Math.round(ttsBundleTask.progress * 100);
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
  const uiLanguageOptions: Array<{ label: string; value: UiLanguage }> = [
    { label: t("api.language.zh"), value: "zh_CN" },
    { label: t("api.language.en"), value: "en" },
    { label: t("api.language.ja"), value: "ja" },
  ];
  const apiLanguageGroup: FormGroupSchema<SystemConfig> = {
    columns: 1,
    fields: [
      {
        label: t("api.language.field"),
        name: "ui_language",
        options: uiLanguageOptions,
        type: "select",
      },
    ],
    id: "api-language",
    title: t("api.language.title"),
  };

  const updateDraft = (patch: Partial<ApiConfig>) => {
    setDraft({ ...draft, ...patch });
  };

  const updateSystemDraft = (patch: Partial<SystemConfig>) => {
    setSystemDraft({ ...systemDraft, ...patch });
  };

  const updateProvider = (provider: string) => {
    activeModelFetchKey.current = null;
    setModelOptions([]);
    setDraft({
      ...draft,
      llm_base_url: llmDefaultBaseUrls[provider] ?? "",
      llm_provider: provider,
    });
  };

  const updateProviderMap = (key: "llm_api_key" | "llm_model", value: string) => {
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
      <div className="api-page__resume-row">
        <AsyncButton
          loading={resumeMutation.isPending}
          onClick={() => resumeMutation.mutate()}
          tooltip={t("api.resume.tip")}
        >
          {t("api.resume.btn")}
        </AsyncButton>
      </div>
      {systemDraft ? (
        <section className="section api-page__language">
          <div className="section__header">
            <div>
              <h2 className="section__title">{t("api.language.title")}</h2>
            </div>
          </div>
          <SchemaFieldGrid
            disabled={languageMutation.isPending}
            group={apiLanguageGroup}
            onChange={(nextSystem) => {
              const language = normalizeUiLanguage(nextSystem.ui_language);
              setSystemDraft({ ...systemDraft, ui_language: language });
              languageMutation.mutate(language);
            }}
            value={systemDraft}
          />
          <p className="section__description">{t("api.language.hint")}</p>
        </section>
      ) : null}
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("api.title")}</h1>
          <p className="page__description">{t("api.description")}</p>
        </div>
      </header>
      <section className="section">
        <div className="section__header">
          <h2 className="section__title">{t("api.llm.connectionTitle")}</h2>
        </div>
        <div className="form-grid form-grid--two">
          <label className="field-row">
            <span className="field-row__label">{t("api.llm.provider")}</span>
            <span className="field-row__control">
              <Select
                disabled={saveMutation.isPending}
                onChange={(event) => updateProvider(event.target.value)}
                value={draft.llm_provider}
              >
                {llmProviderSelectOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("api.llm.baseUrl")}</span>
            <span className="field-row__control">
              <TextInput
                disabled={saveMutation.isPending}
                onChange={(event) => {
                  activeModelFetchKey.current = null;
                  setModelOptions([]);
                  updateDraft({ llm_base_url: event.target.value });
                }}
                placeholder="https://api.example.com/v1"
                type="url"
                value={draft.llm_base_url}
              />
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("api.llm.apiKey")}</span>
            <span className="field-row__control">
              <TextInput
                disabled={saveMutation.isPending}
                onChange={(event) => {
                  activeModelFetchKey.current = null;
                  setModelOptions([]);
                  updateProviderMap("llm_api_key", event.target.value);
                }}
                type="password"
                value={activeApiKey}
              />
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("api.llm.model")}</span>
            <span className="field-row__control">
              <span className="api-page__model-control">
                <EditableModelSelect
                  disabled={saveMutation.isPending}
                  id={modelCandidateListId}
                  onChange={(value) => updateProviderMap("llm_model", value)}
                  options={availableModelOptions}
                  placeholder={t("api.llm.modelPlaceholder")}
                  value={activeModel}
                />
                <AsyncButton
                  icon={<RefreshCw aria-hidden className="button__icon" />}
                  loading={modelFetchMutation.isPending}
                  onClick={() => {
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
                  }}
                >
                  {modelFetchMutation.isPending ? t("api.llm.fetching") : t("api.llm.fetchModels")}
                </AsyncButton>
              </span>
              {selectedOption?.tags.length ? (
                <div className="llm-model-badges">
                  {selectedOption.tags.map((tag) => (
                    <span className="llm-model-badge" data-tag={tag} key={tag}>
                      {capabilityLabel(tag)}
                    </span>
                  ))}
                </div>
              ) : null}
            </span>
          </label>
          <div className="field-row">
            <span className="field-row__label">{t("api.llm.streaming")}</span>
            <span className="field-row__control radio-pair">
              <label>
                <input
                  checked={draft.is_streaming}
                  disabled={saveMutation.isPending}
                  name="api-streaming"
                  onChange={() => updateDraft({ is_streaming: true })}
                  type="radio"
                />
                <span>{t("common.yes")}</span>
              </label>
              <label>
                <input
                  checked={!draft.is_streaming}
                  disabled={saveMutation.isPending}
                  name="api-streaming"
                  onChange={() => updateDraft({ is_streaming: false })}
                  type="radio"
                />
                <span>{t("common.no")}</span>
              </label>
            </span>
          </div>
        </div>
        <AdapterExtraForm
          disabled={saveMutation.isPending}
          modelUnsupportedThinking={thinkingUnsupported(activeModel)}
          onChange={(key, value) => updateAdapterExtra("llm_extra_configs", draft.llm_provider, key, value)}
          schema={llmExtraSchema}
          values={draft.llm_extra_configs?.[draft.llm_provider] ?? {}}
        />
      </section>
      <section className="section">
        <div className="section__header">
          <div>
            <h2 className="section__title">{t("api.tts.bundleTitle")}</h2>
            <p className="section__description">{t("api.tts.bundleHint")}</p>
          </div>
          <AsyncButton
            icon={<DownloadCloud aria-hidden className="button__icon" />}
            loading={ttsBundleMutation.isPending}
            onClick={() => ttsBundleMutation.mutate()}
          >
            {t("api.tts.bundleDownload")}
          </AsyncButton>
        </div>
        <div className="form-grid form-grid--two">
          <label className="field-row">
            <span className="field-row__label">{t("api.tts.bundlePick")}</span>
            <span className="field-row__control">
              <Select
                disabled={ttsBundleMutation.isPending || saveMutation.isPending}
                onChange={(event) => setTtsBundleKind(event.target.value as TtsBundleKind)}
                value={ttsBundleKind}
              >
                <option value="genie">{t("api.tts.bundleGenie")}</option>
                <option value="gptso">{t("api.tts.bundleGptSovits")}</option>
                <option value="gptso50">{t("api.tts.bundleGptSovits50")}</option>
              </Select>
            </span>
          </label>
        </div>
        {ttsBundleTask ? (
          <div className="task-progress" role="status" aria-live="polite">
            <div className="task-progress__meta">
              <strong>{ttsBundleTask.phase}</strong>
              <span>{ttsBundleProgress == null ? ttsBundleTask.status : `${ttsBundleProgress}%`}</span>
            </div>
            {ttsBundleProgress == null ? null : (
              <div className="task-progress__track" aria-hidden>
                <span className="task-progress__fill" style={{ width: `${ttsBundleProgress}%` }} />
              </div>
            )}
            <div className="task-progress__message">{ttsBundleTask.message || ttsBundleTask.status}</div>
          </div>
        ) : null}
      </section>
      <SchemaDrivenForm
        collapsedGroupIds={["llm", "t2i"]}
        disabled={saveMutation.isPending}
        errors={errors}
        groups={apiSchema}
        onChange={setDraft}
        value={draft}
      />
      <section className="section">
        <div className="section__header">
          <div>
            <h2 className="section__title">{t("system.asr.title")}</h2>
            <p className="section__description">{t("system.asr.hint")}</p>
          </div>
        </div>
        {activeAsrProvider === "vosk" ? (
          <div className="asr-vosk-hint">
            <span>{t("system.asr.voskHint")}</span>
            <Button
              icon={<ExternalLink aria-hidden className="button__icon" />}
              onClick={() => openExternal(VOSK_MODELS_URL)}
              variant="ghost"
            >
              {t("system.asr.voskModels")}
            </Button>
          </div>
        ) : null}
        <div className="form-grid form-grid--two">
          <label className="field-row">
            <span className="field-row__label">{t("system.asr.provider")}</span>
            <span className="field-row__control">
              <Select
                disabled={saveMutation.isPending}
                onChange={(event) => updateSystemDraft({ asr_provider: normalizeAsrProvider(event.target.value) })}
                value={activeAsrProvider}
              >
                {asrProviderSelectOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </span>
          </label>
          <label className="field-row">
            <span className="field-row__label">{t("system.asr.language")}</span>
            <span className="field-row__control">
              <Select
                disabled={saveMutation.isPending}
                onChange={(event) => updateSystemDraft({ asr_language: event.target.value })}
                value={systemDraft.asr_language ?? ""}
              >
                <option value="">{t("system.asr.followUi")}</option>
                <option value="en">{t("system.asr.langEn")}</option>
                <option value="zh">{t("system.asr.langZh")}</option>
                <option value="ja">{t("system.asr.langJa")}</option>
                <option value="yue">{t("system.asr.langYue")}</option>
              </Select>
            </span>
          </label>
          {activeAsrProvider === "vosk" ? (
            <label className="field-row">
              <span className="field-row__label">{t("system.asr.voskModelPath")}</span>
              <span className="field-row__control">
                <TextInput
                  disabled={saveMutation.isPending}
                  onChange={(event) => updateAsrExtra("vosk", "model_path", event.target.value)}
                  value={voskModelPath}
                />
              </span>
            </label>
          ) : null}
        </div>
        {showWhisperFields ? (
          <div className="form-grid form-grid--two api-extra-grid">
            <label className="field-row">
              <span className="field-row__label">{t("system.asr.whisperModel")}</span>
              <span className="field-row__control">
                <Select
                  disabled={saveMutation.isPending}
                  onChange={(event) => {
                    const next = event.target.value;
                    updateSystemDraft({
                      asr_whisper_model_size:
                        next === "__custom__"
                          ? (asrWhisperModelPresets as readonly string[]).includes(systemDraft.asr_whisper_model_size)
                            ? ""
                            : systemDraft.asr_whisper_model_size
                          : next,
                    });
                  }}
                  value={whisperPresetValue}
                >
                  {asrWhisperModelPresets.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                  <option value="__custom__">{t("system.asr.modelCustom")}</option>
                </Select>
                {customWhisperModel ? (
                  <TextInput
                    className="asr-custom-model-input"
                    disabled={saveMutation.isPending}
                    onChange={(event) => updateSystemDraft({ asr_whisper_model_size: event.target.value })}
                    placeholder={t("system.asr.modelCustomPlaceholder")}
                    value={
                      (asrWhisperModelPresets as readonly string[]).includes(systemDraft.asr_whisper_model_size)
                        ? ""
                        : systemDraft.asr_whisper_model_size
                    }
                  />
                ) : null}
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("system.asr.device")}</span>
              <span className="field-row__control">
                <Select
                  disabled={saveMutation.isPending}
                  onChange={(event) => updateSystemDraft({ asr_whisper_device: event.target.value })}
                  value={systemDraft.asr_whisper_device || "auto"}
                >
                  <option value="auto">{t("system.asr.deviceAuto")}</option>
                  <option value="cuda">CUDA</option>
                  <option value="cpu">CPU</option>
                </Select>
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("system.asr.computeType")}</span>
              <span className="field-row__control">
                <Select
                  disabled={saveMutation.isPending}
                  onChange={(event) => updateSystemDraft({ asr_whisper_compute_type: event.target.value })}
                  value={currentAsrCompute}
                >
                  {asrComputeSelectOptions.map((option) => (
                    <option key={option.value || "__auto__"} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </span>
            </label>
          </div>
        ) : null}
        {activeAsrProvider !== "vosk" && hasAdapterSchema(activeAsrSchema) ? (
          <AdapterExtraForm
            disabled={saveMutation.isPending}
            onChange={(key, value) => updateAsrExtra(activeAsrProvider, key, value)}
            schema={activeAsrSchema}
            values={draft.asr_extra_configs?.[activeAsrProvider] ?? {}}
          />
        ) : null}
      </section>
      {hasAdapterSchema(ttsExtraSchema) ? (
        <section className="section">
          <div className="section__header">
            <h2 className="section__title">{draft.tts_provider} 扩展参数</h2>
          </div>
          <AdapterExtraForm
            disabled={saveMutation.isPending}
            onChange={(key, value) => updateAdapterExtra("tts_extra_configs", draft.tts_provider, key, value)}
            schema={ttsExtraSchema}
            values={draft.tts_extra_configs?.[draft.tts_provider] ?? {}}
          />
        </section>
      ) : null}
      {hasAdapterSchema(t2iExtraSchema) ? (
        <section className="section">
          <div className="section__header">
            <h2 className="section__title">{draft.t2i_provider} 扩展参数</h2>
          </div>
          <AdapterExtraForm
            disabled={saveMutation.isPending}
            onChange={(key, value) => updateAdapterExtra("t2i_extra_configs", draft.t2i_provider, key, value)}
            schema={t2iExtraSchema}
            values={draft.t2i_extra_configs?.[draft.t2i_provider] ?? {}}
          />
        </section>
      ) : null}
      <section className="section resource-links">
        <div className="section__header">
          <h2 className="section__title">{t("api.links.title")}</h2>
        </div>
        <div className="resource-links__grid">
          {resourceLinks.map(([labelKey, url]) => (
            <Button
              icon={<ExternalLink aria-hidden className="button__icon" />}
              key={url}
              onClick={() => openExternal(url)}
              variant="ghost"
            >
              {t(labelKey)}
            </Button>
          ))}
        </div>
        <p className="section__description resource-links__help">{t("api.links.help")}</p>
      </section>
      <footer className="api-page__save-footer">
        <AsyncButton className="api-page__save-button" loading={saveMutation.isPending} onClick={handleSave}>
          {t("common.save")}
        </AsyncButton>
      </footer>
    </div>
  );
}
