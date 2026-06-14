import type { AdapterExtraFieldSchema, ApiConfig, SystemConfig } from "./types";
import type { FieldKind, FormFieldSchema, FormGroupSchema } from "../../shared/form-schema";

export const llmProviderOptions = [
  { label: "Deepseek", value: "Deepseek" },
  { label: "ChatGPT", value: "ChatGPT" },
  { label: "Gemini", value: "Gemini" },
  { label: "Claude", value: "Claude" },
  { label: "豆包", value: "豆包" },
  { label: "通义千问", value: "通义千问" },
  { label: "Ollama", value: "Ollama" },
] as const;

export const llmDefaultBaseUrls: Record<string, string> = {
  ChatGPT: "https://api.openai.com/v1",
  Claude: "https://api.anthropic.com/v1",
  Deepseek: "https://api.deepseek.com/v1",
  Gemini: "https://generativelanguage.googleapis.com/v1beta/openai",
  豆包: "https://ark.cn-beijing.volces.com/api/v3",
  通义千问: "https://dashscope.aliyuncs.com/api/v1",
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
    title: "高级参数（采样/上下文）",
    description: "高级生成参数。",
    fields: [
      { label: "流式响应", name: "is_streaming", type: "checkbox" },
      { label: "Temperature", max: 2, min: 0, name: "temperature", step: 0.05, type: "number" },
      { label: "重复惩罚", max: 2, min: 0.5, name: "repetition_penalty", step: 0.05, type: "number" },
      { label: "存在惩罚", max: 2, min: -2, name: "presence_penalty", step: 0.05, type: "number" },
      { label: "频率惩罚", max: 2, min: -2, name: "frequency_penalty", step: 0.05, type: "number" },
      { label: "最大上下文 token", max: 2000000, min: 0, name: "max_context_tokens", step: 1, type: "integer" },
      {
        description: "估算历史达到该上下文占比时触发压缩。",
        label: "压缩阈值",
        max: 0.95,
        min: 0.1,
        name: "compact_threshold",
        step: 0.05,
        type: "number",
      },
      {
        description: "压缩后的目标上下文占比，需低于压缩阈值。",
        label: "压缩目标",
        max: compactTargetRatioMax,
        min: 0.05,
        name: "compact_target_ratio",
        step: 0.05,
        type: "number",
      },
      {
        description: "加载或压缩历史时保留的最近消息数。",
        label: "最近历史消息数",
        max: 200,
        min: 1,
        name: "history_recent_messages",
        step: 1,
        type: "integer",
      },
      {
        description: "写入历史的单次工具结果最大字符数。",
        label: "工具结果字符数",
        max: 200000,
        min: 100,
        name: "max_tool_result_chars",
        step: 1,
        type: "integer",
      },
      {
        description: "同时启用的工具组数量上限。",
        label: "工具组上限",
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
    title: "TTS",
    description: "语音合成引擎与分句规则。",
    fields: [
      {
        label: "引擎",
        name: "tts_provider",
        options: [
          { label: "不使用", value: "none" },
          { label: "Genie TTS", value: "genie-tts" },
          { label: "GPT SoVITS", value: "gpt-sovits" },
          { label: "IndexTTS", value: "index-tts" },
          { label: "CosyVoice", value: "cosyvoice" },
        ],
        required: true,
        type: "select",
      },
      { label: "GPT SoVITS 目录", name: "gpt_sovits_api_path", pathKind: "directory", type: "file" },
      { label: "GPT SoVITS URL", name: "gpt_sovits_url", type: "url" },
      { label: "启用分句", name: "tts_split_enabled", type: "checkbox" },
      {
        label: "分句最大长度",
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
    title: "ComfyUI / 文生图",
    description: "文生图服务端与 ComfyUI 工作流字段。",
    fields: [
      {
        label: "引擎",
        name: "t2i_provider",
        options: [
          { label: "ComfyUI", value: "comfyui" },
          { label: "Stable Diffusion", value: "stable diffusion" },
        ],
        required: true,
        type: "select",
      },
      { label: "工作目录", name: "t2i_work_path", pathKind: "directory", type: "file" },
      { label: "API URL", name: "t2i_api_url", type: "url" },
      { label: "默认工作流", name: "t2i_default_workflow_path", type: "file" },
      { label: "Prompt 节点", name: "t2i_prompt_node_id", type: "text" },
      { label: "输出节点", name: "t2i_output_node_id", type: "text" },
    ],
  },
];

export const systemConfigFormSchema: Array<FormGroupSchema<SystemConfig>> = [
  {
    id: "ui",
    title: "界面",
    fields: [
      { label: "基础字号", min: 12, name: "base_font_size_px", step: 1, type: "integer" },
      {
        label: "界面语言",
        name: "ui_language",
        options: [
          { label: "简体中文", value: "zh_CN" },
          { label: "English", value: "en" },
          { label: "日本語", value: "ja" },
        ],
        required: true,
        type: "select",
      },
      { label: "主题色", name: "theme_color", type: "color" },
      { label: "聊天主题 JSON", name: "chat_ui_theme_path", type: "file" },
    ],
  },
  {
    id: "mirrors",
    title: "镜像源",
    description: "国内网络会自动填入常用镜像；手动填写后会优先生效，并同步设置相关环境变量。",
    fields: [
      {
        label: "自动检测国内网络",
        name: "mirror_auto_detect_china",
        type: "checkbox",
      },
      {
        description: "由后端检测得到，仅用于展示，不会作为手动配置保存。",
        disabledWhen: () => true,
        label: "检测区域",
        name: "mirror_region",
        type: "text",
      },
      {
        description: "保存后写入 HF_ENDPOINT，留空且检测为国内网络时使用 https://hf-mirror.com。",
        label: "Hugging Face",
        name: "huggingface_mirror_url",
        placeholder: "https://hf-mirror.com",
        type: "url",
      },
      {
        description: "保存后写入 HF_HOME / HF_HUB_CACHE，并通过插件上下文暴露给插件。",
        label: "HF Cache 目录",
        name: "huggingface_cache_dir",
        pathKind: "directory",
        placeholder: "./data/cache/huggingface",
        type: "file",
      },
      {
        description: "可填写代理前缀，或使用包含 {url} / {path} 的模板。",
        label: "GitHub",
        name: "github_mirror_url",
        placeholder: "https://gh-proxy.com/",
        type: "url",
      },
      {
        description: "保存后写入 SHINSEKAI_PIP_INDEX_URL，仅用于内置插件依赖安装器。",
        label: "PyPI",
        name: "pypi_mirror_url",
        placeholder: "https://pypi.tuna.tsinghua.edu.cn/simple/",
        type: "url",
      },
    ],
  },
  {
    id: "voice",
    title: "语音与识别",
    fields: [{ label: "语音语言", name: "voice_language", type: "text" }],
  },
  {
    id: "media",
    title: "媒体与直播",
    fields: [
      { label: "BGM 音量", max: 100, min: 0, name: "music_volumn", step: 1, type: "integer" },
      { label: "BGM 路径", name: "bgm_path", type: "file" },
      { label: "背景图片", name: "background_path", type: "file" },
      { label: "直播间 ID", name: "live_room_id", type: "text" },
    ],
  },
  {
    id: "music-cover",
    title: "翻唱流水线",
    fields: [
      { label: "工作目录", name: "music_cover_work_dir", pathKind: "directory", type: "file" },
      { label: "yt-dlp", name: "music_cover_yt_dlp_exe", type: "file" },
      { label: "ffmpeg", name: "music_cover_ffmpeg_exe", type: "file" },
      { label: "UVR 命令模板", name: "music_cover_uvr_cmd_template", span: "full", type: "textarea" },
      { label: "RVC 命令模板", name: "music_cover_rvc_cmd_template", span: "full", type: "textarea" },
      { label: "RVC 模型", name: "music_cover_rvc_model_path", type: "file" },
      { label: "RVC 索引", name: "music_cover_rvc_index_path", type: "file" },
      { label: "RVC 设备", name: "music_cover_rvc_device", type: "text" },
      {
        label: "模型版本",
        name: "music_cover_rvc_model_version",
        options: [
          { label: "v1", value: "v1" },
          { label: "v2", value: "v2" },
        ],
        type: "select",
      },
      {
        label: "F0 方法",
        name: "music_cover_rvc_f0_method",
        options: [
          { label: "rmvpe", value: "rmvpe" },
          { label: "harvest", value: "harvest" },
          { label: "crepe", value: "crepe" },
          { label: "pm", value: "pm" },
        ],
        type: "select",
      },
      { label: "变调", max: 12, min: -12, name: "music_cover_rvc_pitch", step: 0.5, type: "number" },
      { label: "Index Rate", max: 1, min: 0, name: "music_cover_rvc_index_rate", step: 0.05, type: "number" },
      { label: "Filter Radius", max: 7, min: 0, name: "music_cover_rvc_filter_radius", step: 1, type: "integer" },
      { label: "Resample SR", max: 192000, min: 0, name: "music_cover_rvc_resample_sr", step: 1, type: "integer" },
      { label: "RMS Mix", max: 1, min: 0, name: "music_cover_rvc_rms_mix_rate", step: 0.05, type: "number" },
      { label: "Protect", max: 0.5, min: 0, name: "music_cover_rvc_protect", step: 0.01, type: "number" },
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

function validateField<T extends object>(field: FormFieldSchema<T>, value: unknown, draft: T): string {
  if (field.required && isBlank(value)) {
    return "此项必填。";
  }

  if (field.type === "url" && !isBlank(value) && !isValidUrl(String(value))) {
    return "请输入有效的 http(s) URL。";
  }

  if ((field.type === "number" || field.type === "integer") && !isBlank(value)) {
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue)) {
      return "请输入有效数字。";
    }
    if (field.type === "integer" && !Number.isInteger(numberValue)) {
      return "请输入整数。";
    }
    const min = resolveNumericBound(field.min, draft);
    const max = resolveNumericBound(field.max, draft);
    if (typeof min === "number" && numberValue < min) {
      return `不能小于 ${min}。`;
    }
    if (typeof max === "number" && numberValue > max) {
      return `不能大于 ${max}。`;
    }
  }

  if (field.type === "file" && !isBlank(value) && String(value).includes("\0")) {
    return "路径包含非法字符。";
  }

  return "";
}

export function validatePayloadFromSchema<T extends object>(
  schema: Array<FormGroupSchema<T>>,
  draft: T,
): SchemaErrorMap<T> {
  const errors: SchemaErrorMap<T> = {};
  for (const group of schema) {
    for (const field of group.fields) {
      if (field.visibleWhen && !field.visibleWhen(draft)) {
        continue;
      }
      const error = validateField(field, draft[field.name], draft);
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
