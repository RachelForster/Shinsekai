import {
  apiConfigFormSchema,
  compactTargetRatioMax,
  llmDefaultBaseUrls,
  llmProviderOptions,
} from "../../entities/config/schema";
import type {
  AdapterCatalog,
  AdapterExtraFieldSchema,
  AdapterOption,
  ApiConfig,
  SystemConfig,
} from "../../entities/config/types";
import type { FormGroupSchema } from "../../shared/form-schema";
import type { LlmModelOption, TaskSnapshot } from "../../shared/platform/types";

export type UiLanguage = "zh_CN" | "en" | "ja";

export const resourceLinks = [
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

export const VOSK_MODEL_PATH = "./assets/system/models/vosk-model-small-cn-0.22";
export const VOSK_MODELS_URL = "https://alphacephei.com/vosk/models";
export const DEFAULT_T2I_PROVIDER = "comfyui";
export const DEFAULT_T2I_API_URL = "http://127.0.0.1:8188";
export const DEFAULT_T2I_PROMPT_NODE_ID = "6";
export const DEFAULT_T2I_OUTPUT_NODE_ID = "9";
export const LEGACY_DEFAULT_TTS_SERVER_URL = "http://127.0.0.1:9880";
export const HTTPS_DEFAULT_TTS_SERVER_URL = "https://127.0.0.1:9880";
export const DEFAULT_TTS_SERVER_URL = LEGACY_DEFAULT_TTS_SERVER_URL;
const LOCAL_SERVER_TTS_PROVIDERS = new Set(["gpt-sovits", "genie-tts", "index-tts"]);
const REMOTE_SERVER_TTS_PROVIDERS = new Set(["kaggle-gpt-sovits"]);
const SERVER_CONFIG_TTS_PROVIDERS = new Set([...LOCAL_SERVER_TTS_PROVIDERS, ...REMOTE_SERVER_TTS_PROVIDERS]);
const TTS_PROVIDER_DEFAULT_URLS: Record<string, string> = {
  "genie-tts": DEFAULT_TTS_SERVER_URL,
  "gpt-sovits": DEFAULT_TTS_SERVER_URL,
  "index-tts": LEGACY_DEFAULT_TTS_SERVER_URL,
};
const BUILTIN_TTS_SERVER_URLS = new Set([
  LEGACY_DEFAULT_TTS_SERVER_URL,
  HTTPS_DEFAULT_TTS_SERVER_URL,
  DEFAULT_TTS_SERVER_URL,
]);
const TTS_PROVIDER_ALIASES: Record<string, string> = {
  "genie tts": "genie-tts",
  "gpt sovits": "gpt-sovits",
  "gpt-sovits": "gpt-sovits",
  kaggle: "kaggle-gpt-sovits",
  "kaggle gpt sovits": "kaggle-gpt-sovits",
  "kaggle gpt-sovits": "kaggle-gpt-sovits",
  "kaggle-gpt-sovits": "kaggle-gpt-sovits",
};

export type T2iSetupMode = "custom" | "local" | "skip";

export const asrProviderOptions = [
  { label: "Vosk", value: "vosk" },
  { label: "faster-whisper", value: "faster_whisper" },
  { label: "RealtimeSTT", value: "realtime_stt" },
] as const;

export const asrWhisperModelPresets = [
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

export const asrComputeOptions = [
  { labelKey: "system.asr.computeAuto", value: "" },
  { label: "int8", value: "int8" },
  { label: "float16", value: "float16" },
  { label: "int8_float16", value: "int8_float16" },
  { label: "int16", value: "int16" },
  { label: "float32", value: "float32" },
] as const;

export function withCurrentOption(options: Array<{ label: string; value: string }>, currentValue: string) {
  const cleanValue = String(currentValue || "").trim();
  if (!cleanValue || options.some((option) => option.value === cleanValue)) {
    return options;
  }
  return [...options, { label: cleanValue, value: cleanValue }];
}

export function normalizeUiLanguage(language: string): UiLanguage {
  return language === "en" || language === "ja" ? language : "zh_CN";
}

export function normalizeAsrProvider(provider: string) {
  const normalized = (provider || "vosk").trim().toLowerCase().replace(/-/g, "_");
  if (normalized === "fasterwhisper" || normalized === "whisper") {
    return "faster_whisper";
  }
  if (normalized === "realtimestt") {
    return "realtime_stt";
  }
  return normalized || "vosk";
}

export function normalizeTtsProvider(provider: string) {
  const normalized = String(provider || "")
    .trim()
    .toLowerCase();
  if (!normalized) {
    return "gpt-sovits";
  }
  if (["none", "off", "disable", "disabled", "不使用"].includes(normalized)) {
    return "none";
  }
  return TTS_PROVIDER_ALIASES[normalized] ?? normalized;
}

export function resolveAsrWhisperPresetValue(model: string) {
  const value = (model || "small").trim();
  return (asrWhisperModelPresets as readonly string[]).includes(value) ? value : "__custom__";
}

export function updateAsrExtraConfig(apiConfig: ApiConfig, provider: string, key: string, value: unknown): ApiConfig {
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

export function normalizeSystemAsrForSave(systemConfig: SystemConfig): SystemConfig {
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

export function normalizeApiAsrForSave(apiConfig: ApiConfig, systemConfig: SystemConfig): ApiConfig {
  const provider = normalizeAsrProvider(systemConfig.asr_provider);
  if (provider !== "vosk") {
    return apiConfig;
  }
  const current = (apiConfig.asr_extra_configs ?? {}).vosk ?? {};
  const modelPath = String(current.model_path ?? "").trim() || VOSK_MODEL_PATH;
  return updateAsrExtraConfig(apiConfig, "vosk", "model_path", modelPath);
}

export function catalogOptions(
  options: AdapterOption[] | undefined,
  fallback: ReadonlyArray<{ label: string; value: string }>,
) {
  if (!options?.length) {
    return fallback.map((option) => ({ label: option.label, value: option.value }));
  }
  return options.map((option) => ({ label: option.label || option.value, value: option.value }));
}

export function t2iProviderSelectOptions(catalog: AdapterCatalog | undefined, currentValue: string) {
  return withCurrentOption(
    catalogOptions(catalog?.t2i, [
      { label: "ComfyUI", value: DEFAULT_T2I_PROVIDER },
      { label: "Stable Diffusion", value: "stable diffusion" },
    ]),
    currentValue,
  );
}

export function adapterSchema(options: AdapterOption[] | undefined, value: string) {
  return options?.find((option) => option.value === value)?.schema ?? {};
}

function ttsSharedServerFieldCopy(provider: string) {
  switch (normalizeTtsProvider(provider)) {
    case "genie-tts":
      return {
        pathDescription: "当 Genie TTS 服务 URL 指向本机时必填，用于自动启动本地 Genie TTS Server。",
        pathDisabledReason: undefined,
        pathLabel: "Genie TTS 服务启动路径",
        pathPlaceholder: "选择 Genie TTS Server 整合包根目录",
        urlDescription: "Genie TTS Server 的 HTTP 地址。",
        urlLabel: "Genie TTS 服务 URL",
        urlPlaceholder: "如 http://127.0.0.1:9880/",
      };
    case "index-tts":
      return {
        pathDescription: "当 IndexTTS 服务 URL 指向本机时必填，用于自动启动本地 IndexTTS 服务。",
        pathDisabledReason: undefined,
        pathLabel: "IndexTTS 服务启动路径",
        pathPlaceholder: "选择 IndexTTS 服务工程根目录",
        urlDescription: "IndexTTS 服务的 HTTP 地址。",
        urlLabel: "IndexTTS 服务 URL",
        urlPlaceholder: "如 http://127.0.0.1:9880/",
      };
    case "kaggle-gpt-sovits":
      return {
        pathDescription: "Kaggle GPT-SoVITS 通过远端 Notebook URL 调用，本地整合包目录不会参与启动。",
        pathDisabledReason: "Kaggle 模式通过远端 Notebook URL 调用，不使用本地 GPT-SoVITS 路径。",
        pathLabel: "Kaggle GPT-SoVITS 本地路径",
        pathPlaceholder: "Kaggle 模式不使用本地服务启动路径",
        urlDescription: "Kaggle Notebook 暴露出来的 GPT-SoVITS HTTP 地址。",
        urlLabel: "Kaggle Notebook 服务 URL",
        urlPlaceholder: "填写 Kaggle Notebook 暴露的 http(s) URL",
      };
    case "gpt-sovits":
      return {
        pathDescription: "当 GPT-SoVITS 服务 URL 指向本机时必填，用于自动启动本地 GPT-SoVITS 服务。",
        pathDisabledReason: undefined,
        pathLabel: "GPT-SoVITS 服务启动路径",
        pathPlaceholder: "选择 GPT-SoVITS 整合包或工程根目录",
        urlDescription: "GPT-SoVITS API 服务的 HTTP 地址。",
        urlLabel: "GPT-SoVITS 服务 URL",
        urlPlaceholder: "如 http://127.0.0.1:9880/",
      };
    default:
      return {
        pathDescription: "当 TTS 服务 URL 指向本机时必填，用于自动启动本地 TTS 服务。",
        pathDisabledReason: undefined,
        pathLabel: "TTS 服务启动路径",
        pathPlaceholder: "选择 TTS 服务工程或整合包根目录",
        urlDescription: "TTS 服务的 HTTP 地址。",
        urlLabel: "TTS 服务 URL",
        urlPlaceholder: "如 http://127.0.0.1:9880/",
      };
  }
}

export function apiSchemaWithAdapterOptions(
  catalog: AdapterCatalog | undefined,
  draft: ApiConfig | null,
): Array<FormGroupSchema<ApiConfig>> {
  const ttsFieldCopy = ttsSharedServerFieldCopy(draft?.tts_provider ?? "");
  const ttsOptions = withCurrentOption(
    catalogOptions(catalog?.tts, [
      { label: "不使用", value: "none" },
      { label: "Genie TTS", value: "genie-tts" },
      { label: "Kaggle GPT-SoVITS", value: "kaggle-gpt-sovits" },
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
          if (field.name === "gpt_sovits_api_path") {
            return {
              ...field,
              description: ttsFieldCopy.pathDescription,
              disabledReason: ttsFieldCopy.pathDisabledReason,
              disabledWhen: (value: ApiConfig) => normalizeTtsProvider(value.tts_provider) === "kaggle-gpt-sovits",
              label: ttsFieldCopy.pathLabel,
              placeholder: ttsFieldCopy.pathPlaceholder,
            };
          }
          if (field.name === "gpt_sovits_url") {
            return {
              ...field,
              description: ttsFieldCopy.urlDescription,
              label: ttsFieldCopy.urlLabel,
              placeholder: ttsFieldCopy.urlPlaceholder,
            };
          }
          if (field.name === "t2i_provider") {
            return { ...field, options: t2iOptions };
          }
          return field;
        }),
    }))
    .filter((group) => group.fields.length > 0);
}

export function activeMapValue(map: Record<string, string>, provider: string) {
  return map?.[provider] ?? "";
}

function finiteNumber(value: unknown, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function syncCompactRatioDraft(config: ApiConfig): ApiConfig {
  const compactThreshold = finiteNumber(config.compact_threshold, 0.4);
  const compactTargetMax = compactTargetRatioMax({ compact_threshold: compactThreshold });
  return {
    ...config,
    compact_threshold: compactThreshold,
    compact_target_ratio: Math.min(finiteNumber(config.compact_target_ratio, 0.3), compactTargetMax),
  };
}

export function defaultTtsServerUrl(provider: string) {
  return TTS_PROVIDER_DEFAULT_URLS[normalizeTtsProvider(provider)] ?? "";
}

export function ttsServerUrlOrDefault(provider: string, currentUrl: string) {
  const cleanUrl = String(currentUrl || "").trim();
  const defaultUrl = defaultTtsServerUrl(provider);
  if (defaultUrl && (!cleanUrl || BUILTIN_TTS_SERVER_URLS.has(cleanUrl))) {
    return defaultUrl;
  }
  return cleanUrl;
}

export function applyTtsProviderDefaults(config: ApiConfig, installedTtsBundlePath = ""): ApiConfig {
  const ttsProvider = normalizeTtsProvider(config.tts_provider);
  const cleanPath = String(config.gpt_sovits_api_path || "").trim();
  const defaultPath = String(installedTtsBundlePath || "").trim();
  return {
    ...config,
    gpt_sovits_api_path:
      ttsProvider === "kaggle-gpt-sovits"
        ? ""
        : requiresTtsWorkPath(ttsProvider) && !cleanPath && defaultPath
          ? defaultPath
          : cleanPath,
    gpt_sovits_url: ttsServerUrlOrDefault(ttsProvider, config.gpt_sovits_url),
    tts_provider: ttsProvider,
  };
}

export function normalizeApiConfigForUi(config: ApiConfig, installedTtsBundlePath = ""): ApiConfig {
  const provider = (config.llm_provider || "Deepseek").trim() || "Deepseek";
  return applyTtsProviderDefaults(
    syncCompactRatioDraft({
      ...config,
      history_recent_messages: finiteNumber(config.history_recent_messages, 20),
      llm_api_key: config.llm_api_key ?? {},
      llm_base_url: String(config.llm_base_url || "").trim() || llmDefaultBaseUrls[provider] || "",
      llm_model: config.llm_model ?? {},
      llm_provider: provider,
      max_active_tool_groups: finiteNumber(config.max_active_tool_groups, 3),
      max_tool_result_chars: finiteNumber(config.max_tool_result_chars, 6000),
      t2i_api_url: String(config.t2i_api_url || "").trim() || DEFAULT_T2I_API_URL,
      t2i_output_node_id: String(config.t2i_output_node_id || "").trim() || DEFAULT_T2I_OUTPUT_NODE_ID,
      t2i_prompt_node_id: String(config.t2i_prompt_node_id || "").trim() || DEFAULT_T2I_PROMPT_NODE_ID,
      t2i_provider: String(config.t2i_provider || "").trim() || DEFAULT_T2I_PROVIDER,
    }),
    installedTtsBundlePath,
  );
}

export function inferT2iSetupMode(
  config: Pick<ApiConfig, "t2i_api_url" | "t2i_default_workflow_path" | "t2i_provider" | "t2i_work_path">,
): T2iSetupMode {
  const workflow = String(config.t2i_default_workflow_path || "").trim();
  const workPath = String(config.t2i_work_path || "").trim();
  const url = String(config.t2i_api_url || "")
    .trim()
    .toLowerCase();
  const provider = String(config.t2i_provider || DEFAULT_T2I_PROVIDER)
    .trim()
    .toLowerCase();
  const defaultUrl = !url || url === DEFAULT_T2I_API_URL;
  const defaultProvider = !provider || provider === DEFAULT_T2I_PROVIDER;
  if (!workflow && !workPath && defaultUrl && defaultProvider) {
    return "skip";
  }
  if (/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(?::\d+)?(?:\/.*)?$/.test(url)) {
    return "local";
  }
  return "custom";
}

export function applyT2iSetupMode(config: ApiConfig, mode: T2iSetupMode): ApiConfig {
  const baseDefaults = {
    t2i_output_node_id: config.t2i_output_node_id || DEFAULT_T2I_OUTPUT_NODE_ID,
    t2i_prompt_node_id: config.t2i_prompt_node_id || DEFAULT_T2I_PROMPT_NODE_ID,
    t2i_provider: config.t2i_provider || DEFAULT_T2I_PROVIDER,
  };
  if (mode === "skip") {
    return {
      ...config,
      ...baseDefaults,
      t2i_api_url: DEFAULT_T2I_API_URL,
      t2i_default_workflow_path: "",
      t2i_output_node_id: DEFAULT_T2I_OUTPUT_NODE_ID,
      t2i_prompt_node_id: DEFAULT_T2I_PROMPT_NODE_ID,
      t2i_provider: DEFAULT_T2I_PROVIDER,
      t2i_work_path: "",
    };
  }
  if (mode === "local") {
    return {
      ...config,
      ...baseDefaults,
      t2i_api_url: DEFAULT_T2I_API_URL,
      t2i_output_node_id: DEFAULT_T2I_OUTPUT_NODE_ID,
      t2i_prompt_node_id: DEFAULT_T2I_PROMPT_NODE_ID,
      t2i_provider: DEFAULT_T2I_PROVIDER,
    };
  }
  return {
    ...config,
    ...baseDefaults,
    t2i_api_url: config.t2i_api_url || DEFAULT_T2I_API_URL,
  };
}

export function isT2iReadyForSprites(
  config: Pick<ApiConfig, "t2i_api_url" | "t2i_default_workflow_path" | "t2i_provider">,
) {
  const provider = String(config.t2i_provider || "")
    .trim()
    .toLowerCase();
  const apiUrl = String(config.t2i_api_url || "").trim();
  const workflow = String(config.t2i_default_workflow_path || "").trim();
  if (!provider || !apiUrl) {
    return false;
  }
  if (provider === DEFAULT_T2I_PROVIDER) {
    return Boolean(workflow);
  }
  return true;
}

export function mergeModelOptions(...groups: Array<LlmModelOption[] | undefined>) {
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

export function llmModelFetchKey(config: ApiConfig) {
  return JSON.stringify([
    config.llm_provider,
    String(config.llm_base_url || "").trim(),
    activeMapValue(config.llm_api_key, config.llm_provider),
  ]);
}

export function thinkingUnsupported(model: string) {
  return ["deepseek-v4-flash", "deepseek-chat"].includes(model.trim().toLowerCase());
}

export function isTaskRunning(task: TaskSnapshot | null) {
  return task?.status === "queued" || task?.status === "running";
}

export function isTaskCancelledError(error: unknown) {
  return error instanceof Error && error.name === "TaskCancelledError";
}

export function requiresTtsServerConfig(provider: string) {
  return SERVER_CONFIG_TTS_PROVIDERS.has(normalizeTtsProvider(provider));
}

export function requiresTtsWorkPath(provider: string) {
  return LOCAL_SERVER_TTS_PROVIDERS.has(normalizeTtsProvider(provider));
}

export function containsPathQuotes(value: string) {
  return value.includes('"') || value.includes("'");
}

export function hasAdapterSchema(schema: Record<string, AdapterExtraFieldSchema>) {
  return Object.keys(schema).length > 0;
}

export { llmDefaultBaseUrls, llmProviderOptions };
