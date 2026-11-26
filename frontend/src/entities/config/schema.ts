import type { AdapterExtraFieldSchema, ApiConfig, SystemConfig } from "./types";
import { LLM_PROVIDER_DOUBAO, LLM_PROVIDER_QWEN, LLM_PROVIDER_SILICONFLOW } from "../../shared/constants";
import type { FieldKind, FormFieldSchema, FormGroupSchema, FormOption } from "../../shared/form-schema";
import { translateMessage, type TranslateFn } from "../../shared/i18n/I18nProvider";

export const llmProviderOptions: readonly FormOption[] = [
  { label: "Deepseek", value: "Deepseek" },
  { label: "ChatGPT", value: "ChatGPT" },
  { label: "Gemini", value: "Gemini" },
  { label: "Claude", value: "Claude" },
  { labelKey: "domain.llmProvider.doubao", value: LLM_PROVIDER_DOUBAO },
  { labelKey: "domain.llmProvider.qwen", value: LLM_PROVIDER_QWEN },
  { labelKey: "domain.llmProvider.siliconflow", value: LLM_PROVIDER_SILICONFLOW },
  { label: "Moonshot", value: "Moonshot" },
  { label: "OpenRouter", value: "OpenRouter" },
  { label: "Ollama", value: "Ollama" },
] as const;

export const llmDefaultBaseUrls: Record<string, string> = {
  ChatGPT: "https://api.openai.com/v1",
  Claude: "https://api.anthropic.com/v1",
  Deepseek: "https://api.deepseek.com/v1",
  Gemini: "https://generativelanguage.googleapis.com/v1beta/openai",
  [LLM_PROVIDER_DOUBAO]: "https://ark.cn-beijing.volces.com/api/v3",
  [LLM_PROVIDER_QWEN]: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  [LLM_PROVIDER_SILICONFLOW]: "https://api.siliconflow.cn/v1",
  Moonshot: "https://api.moonshot.cn/v1",
  OpenRouter: "https://openrouter.ai/api/v1",
  Ollama: "http://127.0.0.1:11434/v1",
};

export function compactTargetRatioMax(draft: Pick<ApiConfig, "compact_threshold">) {
  const threshold = Number(draft.compact_threshold ?? 0.4);
  const safeThreshold = Number.isFinite(threshold) ? threshold : 0.4;
  return Math.round(Math.max(0.05, safeThreshold - 0.05) * 100) / 100;
}

export const apiConfigFormSchema: Array<FormGroupSchema<ApiConfig>> = [
  {
    id: "llm",
    titleKey: "api.schema.llm.title",
    descriptionKey: "api.schema.llm.description",
    fields: [
      { labelKey: "api.schema.llm.streaming", name: "is_streaming", type: "checkbox" },
      { labelKey: "api.schema.llm.temperature", max: 2, min: 0, name: "temperature", step: 0.05, type: "number" },
      {
        labelKey: "api.schema.llm.repetitionPenalty",
        max: 2,
        min: 0.5,
        name: "repetition_penalty",
        step: 0.05,
        type: "number",
      },
      {
        labelKey: "api.schema.llm.presencePenalty",
        max: 2,
        min: -2,
        name: "presence_penalty",
        step: 0.05,
        type: "number",
      },
      {
        labelKey: "api.schema.llm.frequencyPenalty",
        max: 2,
        min: -2,
        name: "frequency_penalty",
        step: 0.05,
        type: "number",
      },
      {
        labelKey: "api.schema.llm.maxContextTokens",
        max: 2000000,
        min: 0,
        name: "max_context_tokens",
        step: 1,
        type: "integer",
      },
      {
        descriptionKey: "api.schema.llm.compactThresholdDesc",
        labelKey: "api.schema.llm.compactThreshold",
        max: 0.95,
        min: 0.1,
        name: "compact_threshold",
        step: 0.05,
        type: "number",
      },
      {
        descriptionKey: "api.schema.llm.compactTargetRatioDesc",
        labelKey: "api.schema.llm.compactTargetRatio",
        max: compactTargetRatioMax,
        min: 0.05,
        name: "compact_target_ratio",
        step: 0.05,
        type: "number",
      },
      {
        descriptionKey: "api.schema.llm.historyRecentMessagesDesc",
        labelKey: "api.schema.llm.historyRecentMessages",
        max: 200,
        min: 1,
        name: "history_recent_messages",
        step: 1,
        type: "integer",
      },
      {
        descriptionKey: "api.schema.llm.maxToolResultCharsDesc",
        labelKey: "api.schema.llm.maxToolResultChars",
        max: 200000,
        min: 100,
        name: "max_tool_result_chars",
        step: 1,
        type: "integer",
      },
      {
        descriptionKey: "api.schema.llm.maxActiveToolGroupsDesc",
        labelKey: "api.schema.llm.maxActiveToolGroups",
        max: 20,
        min: 1,
        name: "max_active_tool_groups",
        step: 1,
        type: "integer",
      },
    ],
  },
  {
    id: "tts",
    titleKey: "api.schema.tts.title",
    descriptionKey: "api.schema.tts.description",
    fields: [
      {
        labelKey: "api.schema.tts.provider",
        name: "tts_provider",
        options: [
          { labelKey: "api.schema.tts.providerNone", value: "none" },
          { label: "Genie TTS", value: "genie-tts" },
          { label: "GPT SoVITS", value: "gpt-sovits" },
          { label: "Qwen3-TTS (llama.cpp GGUF)", value: "qwen3-tts-gguf" },
          { label: "IndexTTS", value: "index-tts" },
          { label: "CosyVoice", value: "cosyvoice" },
        ],
        required: true,
        type: "select",
      },
      { labelKey: "api.schema.tts.apiPath", name: "gpt_sovits_api_path", pathKind: "directory", type: "file" },
      { labelKey: "api.schema.tts.url", name: "gpt_sovits_url", type: "url" },
      { labelKey: "api.schema.tts.splitEnabled", name: "tts_split_enabled", type: "checkbox" },
      {
        labelKey: "api.schema.tts.maxSentenceLength",
        max: 100,
        min: 5,
        name: "tts_max_sentence_length",
        type: "integer",
        visibleWhen: (draft) => Boolean(draft.tts_split_enabled),
      },
    ],
  },
  {
    id: "t2i",
    titleKey: "api.schema.t2i.title",
    descriptionKey: "api.schema.t2i.description",
    fields: [
      {
        labelKey: "api.schema.t2i.provider",
        name: "t2i_provider",
        options: [
          { label: "ComfyUI", value: "comfyui" },
          { label: "Stable Diffusion", value: "stable diffusion" },
        ],
        required: true,
        type: "select",
      },
      { labelKey: "api.schema.t2i.workPath", name: "t2i_work_path", pathKind: "directory", type: "file" },
      { labelKey: "api.schema.t2i.apiUrl", name: "t2i_api_url", type: "url" },
      { labelKey: "api.schema.t2i.defaultWorkflow", name: "t2i_default_workflow_path", type: "file" },
      { labelKey: "api.schema.t2i.promptNode", name: "t2i_prompt_node_id", type: "text" },
      { labelKey: "api.schema.t2i.outputNode", name: "t2i_output_node_id", type: "text" },
    ],
  },
];

export const systemConfigFormSchema: Array<FormGroupSchema<SystemConfig>> = [
  {
    id: "ui",
    titleKey: "system.schema.ui.title",
    fields: [
      { labelKey: "system.schema.ui.baseFontSize", min: 12, name: "base_font_size_px", step: 1, type: "integer" },
      {
        labelKey: "system.schema.ui.language",
        name: "ui_language",
        options: [
          { labelKey: "api.language.zh", value: "zh_CN" },
          { labelKey: "api.language.en", value: "en" },
          { labelKey: "api.language.ja", value: "ja" },
        ],
        required: true,
        type: "select",
      },
      { labelKey: "system.schema.ui.themeColor", name: "theme_color", type: "color" },
      { labelKey: "system.schema.ui.chatTheme", name: "chat_ui_theme_id", type: "text" },
    ],
  },
  {
    id: "mirrors",
    titleKey: "system.schema.mirrors.title",
    descriptionKey: "system.schema.mirrors.description",
    fields: [
      {
        labelKey: "system.schema.mirrors.autoDetectChina",
        name: "mirror_auto_detect_china",
        type: "checkbox",
      },
      {
        descriptionKey: "system.schema.mirrors.regionDesc",
        disabledWhen: () => true,
        labelKey: "system.schema.mirrors.region",
        name: "mirror_region",
        type: "text",
      },
      {
        descriptionKey: "system.schema.mirrors.huggingfaceDesc",
        labelKey: "system.schema.mirrors.huggingface",
        name: "huggingface_mirror_url",
        placeholder: "https://hf-mirror.com",
        type: "url",
      },
      {
        descriptionKey: "system.schema.mirrors.hfCacheDirDesc",
        labelKey: "system.schema.mirrors.hfCacheDir",
        name: "huggingface_cache_dir",
        pathKind: "directory",
        placeholder: "./data/cache/huggingface",
        type: "file",
      },
      {
        descriptionKey: "system.schema.mirrors.githubDesc",
        labelKey: "system.schema.mirrors.github",
        name: "github_mirror_url",
        placeholder: "https://gh-proxy.com/",
        type: "url",
      },
      {
        descriptionKey: "system.schema.mirrors.pypiDesc",
        labelKey: "system.schema.mirrors.pypi",
        name: "pypi_mirror_url",
        placeholder: "https://pypi.tuna.tsinghua.edu.cn/simple/",
        type: "url",
      },
    ],
  },
  {
    id: "network-proxy",
    titleKey: "system.schema.proxy.title",
    descriptionKey: "system.schema.proxy.description",
    fields: [
      {
        descriptionKey: "system.schema.proxy.enabledDesc",
        labelKey: "system.schema.proxy.enabled",
        name: "network_proxy_enabled",
        type: "checkbox",
      },
      {
        disabledReasonKey: "system.schema.proxy.disabledReason",
        disabledWhen: (draft) => !draft.network_proxy_enabled,
        descriptionKey: "system.schema.proxy.httpDesc",
        labelKey: "system.schema.proxy.http",
        name: "http_proxy_url",
        placeholder: "http://127.0.0.1:7890",
        type: "text",
      },
      {
        disabledReasonKey: "system.schema.proxy.disabledReason",
        disabledWhen: (draft) => !draft.network_proxy_enabled,
        descriptionKey: "system.schema.proxy.httpsDesc",
        labelKey: "system.schema.proxy.https",
        name: "https_proxy_url",
        placeholder: "http://127.0.0.1:7890",
        type: "text",
      },
      {
        disabledReasonKey: "system.schema.proxy.disabledReason",
        disabledWhen: (draft) => !draft.network_proxy_enabled,
        descriptionKey: "system.schema.proxy.socks5Desc",
        labelKey: "system.schema.proxy.socks5",
        name: "socks5_proxy_url",
        placeholder: "socks5://127.0.0.1:7891",
        type: "text",
      },
    ],
  },
  {
    id: "voice",
    titleKey: "system.schema.voice.title",
    fields: [{ labelKey: "system.schema.voice.language", name: "voice_language", type: "text" }],
  },
  {
    id: "media",
    titleKey: "system.schema.media.title",
    fields: [
      { labelKey: "system.schema.media.bgmVolume", max: 100, min: 0, name: "music_volumn", step: 1, type: "integer" },
      { labelKey: "system.schema.media.bgmPath", name: "bgm_path", type: "file" },
      { labelKey: "system.schema.media.backgroundPath", name: "background_path", type: "file" },
      { labelKey: "system.schema.media.liveRoomId", name: "live_room_id", type: "text" },
    ],
  },
  {
    id: "music-cover",
    titleKey: "system.schema.musicCover.title",
    fields: [
      {
        labelKey: "system.schema.musicCover.workDir",
        name: "music_cover_work_dir",
        pathKind: "directory",
        type: "file",
      },
      { labelKey: "system.schema.musicCover.ytDlp", name: "music_cover_yt_dlp_exe", type: "file" },
      { labelKey: "system.schema.musicCover.ffmpeg", name: "music_cover_ffmpeg_exe", type: "file" },
      {
        labelKey: "system.schema.musicCover.uvrCmd",
        name: "music_cover_uvr_cmd_template",
        span: "full",
        type: "textarea",
      },
      {
        labelKey: "system.schema.musicCover.rvcCmd",
        name: "music_cover_rvc_cmd_template",
        span: "full",
        type: "textarea",
      },
      { labelKey: "system.schema.musicCover.rvcModel", name: "music_cover_rvc_model_path", type: "file" },
      { labelKey: "system.schema.musicCover.rvcIndex", name: "music_cover_rvc_index_path", type: "file" },
      { labelKey: "system.schema.musicCover.rvcDevice", name: "music_cover_rvc_device", type: "text" },
      {
        labelKey: "system.schema.musicCover.modelVersion",
        name: "music_cover_rvc_model_version",
        options: [
          { label: "v1", value: "v1" },
          { label: "v2", value: "v2" },
        ],
        type: "select",
      },
      {
        labelKey: "system.schema.musicCover.f0Method",
        name: "music_cover_rvc_f0_method",
        options: [
          { label: "rmvpe", value: "rmvpe" },
          { label: "harvest", value: "harvest" },
          { label: "crepe", value: "crepe" },
          { label: "pm", value: "pm" },
        ],
        type: "select",
      },
      {
        labelKey: "system.schema.musicCover.pitch",
        max: 12,
        min: -12,
        name: "music_cover_rvc_pitch",
        step: 0.5,
        type: "number",
      },
      {
        labelKey: "system.schema.musicCover.indexRate",
        max: 1,
        min: 0,
        name: "music_cover_rvc_index_rate",
        step: 0.05,
        type: "number",
      },
      {
        labelKey: "system.schema.musicCover.filterRadius",
        max: 7,
        min: 0,
        name: "music_cover_rvc_filter_radius",
        step: 1,
        type: "integer",
      },
      {
        labelKey: "system.schema.musicCover.resampleSr",
        max: 192000,
        min: 0,
        name: "music_cover_rvc_resample_sr",
        step: 1,
        type: "integer",
      },
      {
        labelKey: "system.schema.musicCover.rmsMix",
        max: 1,
        min: 0,
        name: "music_cover_rvc_rms_mix_rate",
        step: 0.05,
        type: "number",
      },
      {
        labelKey: "system.schema.musicCover.protect",
        max: 0.5,
        min: 0,
        name: "music_cover_rvc_protect",
        step: 0.01,
        type: "number",
      },
    ],
  },
];

export type AdapterExtraFormValues = Record<string, unknown>;

export interface AdapterExtraFormGroupOptions {
  disabledKeys?: string[];
  disabledReason?: string;
  id: string;
  schema: Record<string, AdapterExtraFieldSchema>;
  title: string;
}

function adapterFieldType(field: AdapterExtraFieldSchema) {
  return String(field.type || "str").toLowerCase();
}

export function defaultAdapterExtraValue(field: AdapterExtraFieldSchema): unknown {
  const type = adapterFieldType(field);
  if (field.default !== undefined) {
    return field.default;
  }
  if (type === "bool") {
    return false;
  }
  if (type === "int" || type === "float") {
    return 0;
  }
  return "";
}

function adapterFieldKind(field: AdapterExtraFieldSchema): FieldKind {
  const type = adapterFieldType(field);
  if (Array.isArray(field.choices) && field.choices.length) {
    return "select";
  }
  if (type === "bool") {
    return "checkbox";
  }
  if (type === "int") {
    return "integer";
  }
  if (type === "float") {
    return "number";
  }
  return field.secret ? "password" : "text";
}

export function adapterExtraSchemaToFormGroup({
  disabledKeys = [],
  disabledReason,
  id,
  schema,
  title,
}: AdapterExtraFormGroupOptions): FormGroupSchema<AdapterExtraFormValues> {
  const disabledKeySet = new Set(disabledKeys);
  return {
    columns: 2,
    fields: Object.entries(schema).map(([key, field]) => {
      const type = adapterFieldType(field);
      return {
        defaultValue: defaultAdapterExtraValue(field),
        disabledReason: disabledKeySet.has(key) ? disabledReason : undefined,
        disabledWhen: disabledKeySet.has(key) ? () => true : undefined,
        label: field.label || key,
        max: field.max,
        min: field.min,
        name: key,
        options: field.choices?.map((choice) => ({ label: choice, value: choice })),
        step: field.step ?? (type === "int" ? 1 : type === "float" ? 0.01 : undefined),
        type: adapterFieldKind(field),
      };
    }),
    id,
    title,
  };
}

export function buildPayloadFromSchema<T extends object>(schema: Array<FormGroupSchema<T>>, draft: T): Partial<T> {
  const payload: Partial<T> = {};
  for (const group of schema) {
    for (const field of group.fields) {
      payload[field.name] = draft[field.name];
    }
  }
  return payload;
}

export type SchemaErrorMap<T extends object> = Partial<Record<keyof T, string>>;

function isBlank(value: unknown) {
  return value === null || value === undefined || String(value).trim() === "";
}

function isValidUrl(value: string) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function resolveNumericBound<T extends object>(bound: FormFieldSchema<T>["max"] | FormFieldSchema<T>["min"], draft: T) {
  return typeof bound === "function" ? bound(draft) : bound;
}

const defaultValidatorTranslator: TranslateFn = (key, values) => translateMessage("zh_CN", key, values);

function validateField<T extends object>(field: FormFieldSchema<T>, value: unknown, draft: T, t: TranslateFn): string {
  if (field.required && isBlank(value)) {
    return t("form.validation.required");
  }

  if (field.type === "url" && !isBlank(value) && !isValidUrl(String(value))) {
    return t("form.validation.invalidUrl");
  }

  if ((field.type === "number" || field.type === "integer") && !isBlank(value)) {
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue)) {
      return t("form.validation.invalidNumber");
    }
    if (field.type === "integer" && !Number.isInteger(numberValue)) {
      return t("form.validation.invalidInteger");
    }
    const min = resolveNumericBound(field.min, draft);
    const max = resolveNumericBound(field.max, draft);
    if (typeof min === "number" && numberValue < min) {
      return t("form.validation.min", { min });
    }
    if (typeof max === "number" && numberValue > max) {
      return t("form.validation.max", { max });
    }
  }

  if (field.type === "file" && !isBlank(value) && String(value).includes("\0")) {
    return t("form.validation.invalidPath");
  }

  return "";
}

export function validatePayloadFromSchema<T extends object>(
  schema: Array<FormGroupSchema<T>>,
  draft: T,
  t: TranslateFn = defaultValidatorTranslator,
): SchemaErrorMap<T> {
  const errors: SchemaErrorMap<T> = {};
  for (const group of schema) {
    for (const field of group.fields) {
      if (field.visibleWhen && !field.visibleWhen(draft)) {
        continue;
      }
      const error = validateField(field, draft[field.name], draft, t);
      if (error) {
        errors[field.name] = error;
      }
    }
  }
  return errors;
}

export function hasSchemaErrors<T extends object>(errors: SchemaErrorMap<T>) {
  return Object.values(errors).some(Boolean);
}
