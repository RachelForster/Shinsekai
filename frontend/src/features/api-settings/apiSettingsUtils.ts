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

export function apiSchemaWithAdapterOptions(
  catalog: AdapterCatalog | undefined,
  draft: ApiConfig | null,
): Array<FormGroupSchema<ApiConfig>> {
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
              disabledReason: "Kaggle 模式通过远端 Notebook URL 调用，不使用本地 GPT-SoVITS 路径。",
              disabledWhen: (value: ApiConfig) => value.tts_provider === "kaggle-gpt-sovits",
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

export function normalizeApiConfigForUi(config: ApiConfig): ApiConfig {
  const provider = (config.llm_provider || "Deepseek").trim() || "Deepseek";
  const ttsProvider = String(config.tts_provider || "").trim().toLowerCase();
  return syncCompactRatioDraft({
    ...config,
    gpt_sovits_api_path: ttsProvider === "kaggle-gpt-sovits" ? "" : config.gpt_sovits_api_path,
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
  });
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
  return ["genie-tts", "kaggle-gpt-sovits", "gpt-sovits"].includes(provider.trim().toLowerCase());
}

export function containsPathQuotes(value: string) {
  return value.includes('"') || value.includes("'");
}

export function hasAdapterSchema(schema: Record<string, AdapterExtraFieldSchema>) {
  return Object.keys(schema).length > 0;
}

export { llmDefaultBaseUrls, llmProviderOptions };
