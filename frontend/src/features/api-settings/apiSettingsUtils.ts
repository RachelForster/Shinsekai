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
import { LLM_PROVIDER_DOUBAO, LLM_PROVIDER_QWEN } from "../../shared/constants";
import { resolveFormOptionLabel, type FormGroupSchema, type FormOption } from "../../shared/form-schema";
import { formatLlmProviderLabel, translateRuntimeMessage, type TranslateFn } from "../../shared/i18n";
import { perceptionModelSettings } from "../../shared/platform/perceptionModel";
import type { LlmModelOption, TaskSnapshot } from "../../shared/platform/types";
import {
  DEFAULT_T2I_API_URL,
  DEFAULT_T2I_OUTPUT_NODE_ID,
  DEFAULT_T2I_PROMPT_NODE_ID,
  DEFAULT_T2I_PROVIDER,
  applyT2iSetupMode,
  inferT2iSetupMode,
  isT2iReadyForSprites,
  type T2iSetupMode,
} from "./t2iSetupUtils";
import {
  DEFAULT_TTS_SERVER_URL,
  HTTPS_DEFAULT_TTS_SERVER_URL,
  LEGACY_DEFAULT_TTS_SERVER_URL,
  QWEN3_TTS_GGUF_DEFAULT_URL,
  applyDownloadedTtsBundle,
  applyTtsProviderDefaults,
  defaultTtsServerUrl,
  normalizeTtsProvider,
  requiresTtsServerConfig,
  requiresTtsWorkPath,
  ttsServerUrlOrDefault,
  ttsSharedServerFieldCopy,
} from "./ttsProviderUtils";

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
export const DEFAULT_PERCEPTION_BASE_URL = "http://127.0.0.1:8091/v1";
export const DEFAULT_PERCEPTION_API_KEY = "EMPTY";

export const asrProviderOptions = [
  { label: "Sherpa-ONNX", value: "sherpa_onnx" },
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
  const normalized = (provider || "sherpa_onnx").trim().toLowerCase().replace(/-/g, "_");
  if (normalized === "sherpa" || normalized === "sherpaonnx" || normalized === "sherpa_onnx") {
    return "sherpa_onnx";
  }
  if (normalized === "fasterwhisper" || normalized === "whisper") {
    return "faster_whisper";
  }
  if (normalized === "realtimestt") {
    return "realtime_stt";
  }
  return normalized || "sherpa_onnx";
}

export function resolveAsrWhisperPresetValue(model: string) {
  const value = String(model ?? "").trim();
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

const defaultCatalogTranslator: TranslateFn = (key, values) => translateRuntimeMessage(key, values);

export function catalogOptions(
  options: AdapterOption[] | undefined,
  fallback: ReadonlyArray<FormOption>,
  t: TranslateFn = defaultCatalogTranslator,
) {
  if (!options?.length) {
    return fallback.map((option) => ({ label: resolveFormOptionLabel(option, t), value: option.value }));
  }
  return options.map((option) => ({
    label: formatLlmProviderLabel(option.value, t, option.label || option.value),
    value: option.value,
  }));
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

export function apiSchemaWithAdapterOptions(
  catalog: AdapterCatalog | undefined,
  draft: ApiConfig | null,
  t: TranslateFn = defaultCatalogTranslator,
): Array<FormGroupSchema<ApiConfig>> {
  const ttsFieldCopy = ttsSharedServerFieldCopy(draft?.tts_provider ?? "", t);
  const ttsOptions = withCurrentOption(
    catalogOptions(
      catalog?.tts,
      [
        { labelKey: "ops.api.tts.noneOption", value: "none" },
        { label: "Genie TTS", value: "genie-tts" },
        { label: "Kaggle GPT-SoVITS", value: "kaggle-gpt-sovits" },
        { label: "GPT SoVITS", value: "gpt-sovits" },
        { label: "Qwen3-TTS (llama.cpp GGUF)", value: "qwen3-tts-gguf" },
        { label: "IndexTTS", value: "index-tts" },
        { label: "CosyVoice", value: "cosyvoice" },
      ],
      t,
    ),
    draft?.tts_provider ?? "",
  );
  const t2iOptions = withCurrentOption(
    catalogOptions(
      catalog?.t2i,
      [
        { label: "ComfyUI", value: "comfyui" },
        { label: "Stable Diffusion", value: "stable diffusion" },
      ],
      t,
    ),
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
              descriptionKey: undefined,
              disabledReason: ttsFieldCopy.pathDisabledReason,
              disabledReasonKey: undefined,
              disabledWhen: (value: ApiConfig) => normalizeTtsProvider(value.tts_provider) === "kaggle-gpt-sovits",
              label: ttsFieldCopy.pathLabel,
              labelKey: undefined,
              placeholder: ttsFieldCopy.pathPlaceholder,
              placeholderKey: undefined,
            };
          }
          if (field.name === "gpt_sovits_url") {
            return {
              ...field,
              description: ttsFieldCopy.urlDescription,
              descriptionKey: undefined,
              label: ttsFieldCopy.urlLabel,
              labelKey: undefined,
              placeholder: ttsFieldCopy.urlPlaceholder,
              placeholderKey: undefined,
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

export function clampInt(value: unknown, fallback: number, min: number, max: number) {
  const parsed = Math.round(finiteNumber(value, fallback));
  return Math.min(max, Math.max(min, parsed));
}

export function clampFloat(value: unknown, fallback: number, min: number, max: number) {
  const parsed = finiteNumber(value, fallback);
  return Math.min(max, Math.max(min, parsed));
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

export function normalizeProviderBaseUrls(config: ApiConfig): ApiConfig {
  const provider = (config.llm_provider || "Deepseek").trim() || "Deepseek";
  const llmBaseUrls = { ...(config.llm_base_urls ?? {}) };
  const activeBaseUrl =
    String(llmBaseUrls[provider] || config.llm_base_url || "").trim() || llmDefaultBaseUrls[provider] || "";
  if (activeBaseUrl) {
    llmBaseUrls[provider] = activeBaseUrl;
  }
  return {
    ...config,
    llm_base_url: activeBaseUrl,
    llm_base_urls: llmBaseUrls,
    llm_provider: provider,
  };
}

export function normalizeApiConfigForUi(config: ApiConfig, installedTtsBundlePath = ""): ApiConfig {
  const normalizedProviders = normalizeProviderBaseUrls(config);
  return applyTtsProviderDefaults(
    syncCompactRatioDraft({
      ...normalizedProviders,
      history_recent_messages: finiteNumber(normalizedProviders.history_recent_messages, 20),
      llm_api_key: normalizedProviders.llm_api_key ?? {},
      llm_model: normalizedProviders.llm_model ?? {},
      max_active_tool_groups: finiteNumber(normalizedProviders.max_active_tool_groups, 3),
      max_tool_result_chars: finiteNumber(normalizedProviders.max_tool_result_chars, 6000),
      knowledge_enabled: normalizedProviders.knowledge_enabled ?? false,
      knowledge_search_limit: clampInt(normalizedProviders.knowledge_search_limit, 5, 1, 20),
      memory_auto_enabled: normalizedProviders.memory_auto_enabled ?? false,
      memory_extract_interval_turns: clampInt(normalizedProviders.memory_extract_interval_turns, 5, 1, 50),
      memory_recent_buffer_messages: clampInt(normalizedProviders.memory_recent_buffer_messages, 16, 2, 64),
      memory_search_limit: clampInt(normalizedProviders.memory_search_limit, 5, 1, 20),
      perception_enabled: normalizedProviders.perception_enabled ?? false,
      perception_base_url: String(normalizedProviders.perception_base_url || "").trim() || DEFAULT_PERCEPTION_BASE_URL,
      perception_api_key: String(normalizedProviders.perception_api_key || "").trim() || DEFAULT_PERCEPTION_API_KEY,
      ...perceptionModelSettings(normalizedProviders),
      perception_python_path: String(normalizedProviders.perception_python_path ?? "").trim(),
      perception_interval_sec: clampFloat(normalizedProviders.perception_interval_sec, 2, 0.5, 30),
      perception_capture_interval_sec: clampFloat(normalizedProviders.perception_capture_interval_sec, 0.5, 0.2, 5),
      perception_ocr_interval_sec: clampFloat(normalizedProviders.perception_ocr_interval_sec, 1, 0.5, 10),
      perception_frame_max_side: clampInt(normalizedProviders.perception_frame_max_side, 512, 256, 1280),
      perception_diff_threshold: clampFloat(normalizedProviders.perception_diff_threshold, 0.035, 0, 0.5),
      perception_ocr_enabled: normalizedProviders.perception_ocr_enabled ?? true,
      perception_reflex_enabled: normalizedProviders.perception_reflex_enabled ?? true,
      perception_reflex_cooldown_sec: clampFloat(normalizedProviders.perception_reflex_cooldown_sec, 15, 1, 60),
      perception_proactive_enabled: normalizedProviders.perception_proactive_enabled ?? true,
      perception_salience_threshold: clampFloat(normalizedProviders.perception_salience_threshold, 0.78, 0, 1),
      perception_proactive_cooldown_sec: clampFloat(normalizedProviders.perception_proactive_cooldown_sec, 25, 5, 300),
      t2i_api_url: String(normalizedProviders.t2i_api_url || "").trim() || DEFAULT_T2I_API_URL,
      t2i_output_node_id: String(normalizedProviders.t2i_output_node_id || "").trim() || DEFAULT_T2I_OUTPUT_NODE_ID,
      t2i_prompt_node_id: String(normalizedProviders.t2i_prompt_node_id || "").trim() || DEFAULT_T2I_PROMPT_NODE_ID,
      t2i_provider: String(normalizedProviders.t2i_provider || "").trim() || DEFAULT_T2I_PROVIDER,
    }),
    installedTtsBundlePath,
  );
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

export const visionProviderLlmProviders: Record<string, string> = {
  chatgpt: "ChatGPT",
  claude: "Claude",
  deepseek: "Deepseek",
  doubao: LLM_PROVIDER_DOUBAO,
  gemini: "Gemini",
  ollama: "Ollama",
  qwen: LLM_PROVIDER_QWEN,
};

export const visionDefaultModels: Record<string, string> = {
  chatgpt: "gpt-4o-mini",
  claude: "claude-3-5-sonnet-latest",
  deepseek: "deepseek-flash",
  doubao: "",
  gemini: "gemini-2.5-flash",
  ollama: "llava",
  qwen: "qwen-vl-max",
};

export function providerBaseUrl(config: ApiConfig, provider: string) {
  return (
    activeMapValue(config.llm_base_urls, provider).trim() ||
    (provider === config.llm_provider ? String(config.llm_base_url || "").trim() : "") ||
    llmDefaultBaseUrls[provider] ||
    ""
  );
}

export function resolveVisionProvider(config: ApiConfig) {
  const selected = String(config.vision_provider || "auto")
    .trim()
    .toLowerCase();
  if (selected !== "auto") return selected;
  return (
    Object.entries(visionProviderLlmProviders).find(
      ([, llmProvider]) => llmProvider.toLowerCase() === config.llm_provider.trim().toLowerCase(),
    )?.[0] ?? "auto"
  );
}

export function effectiveVisionModel(config: ApiConfig, provider = resolveVisionProvider(config)) {
  return (
    activeMapValue(config.vision_model, provider).trim() ||
    activeMapValue(config.llm_model, visionProviderLlmProviders[provider] ?? "").trim() ||
    visionDefaultModels[provider] ||
    ""
  );
}

export function effectiveVisionApiKey(config: ApiConfig, provider = resolveVisionProvider(config)) {
  const llmProvider = visionProviderLlmProviders[provider];
  return llmProvider ? activeMapValue(config.llm_api_key, llmProvider) : "";
}

export function effectiveVisionBaseUrl(config: ApiConfig, provider = resolveVisionProvider(config)) {
  const llmProvider = visionProviderLlmProviders[provider];
  return llmProvider ? providerBaseUrl(config, llmProvider) : "";
}

export function visionProviderRequiresApiKey(provider: string) {
  return provider.trim().toLowerCase() !== "ollama";
}

export function visionModelFetchKey(config: ApiConfig) {
  const provider = resolveVisionProvider(config);
  return [
    provider,
    effectiveVisionBaseUrl(config, provider).trim(),
    effectiveVisionApiKey(config, provider).trim(),
  ].join("\u0000");
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

export function containsPathQuotes(value: string) {
  return value.includes('"') || value.includes("'");
}

export function hasAdapterSchema(schema: Record<string, AdapterExtraFieldSchema>) {
  return Object.keys(schema).length > 0;
}

export {
  DEFAULT_T2I_API_URL,
  DEFAULT_T2I_OUTPUT_NODE_ID,
  DEFAULT_T2I_PROMPT_NODE_ID,
  DEFAULT_T2I_PROVIDER,
  DEFAULT_TTS_SERVER_URL,
  HTTPS_DEFAULT_TTS_SERVER_URL,
  LEGACY_DEFAULT_TTS_SERVER_URL,
  QWEN3_TTS_GGUF_DEFAULT_URL,
  applyDownloadedTtsBundle,
  applyT2iSetupMode,
  applyTtsProviderDefaults,
  defaultTtsServerUrl,
  inferT2iSetupMode,
  isT2iReadyForSprites,
  llmDefaultBaseUrls,
  llmProviderOptions,
  normalizeTtsProvider,
  requiresTtsServerConfig,
  requiresTtsWorkPath,
  ttsServerUrlOrDefault,
  type T2iSetupMode,
};
