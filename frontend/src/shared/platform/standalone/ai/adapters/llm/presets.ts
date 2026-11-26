import { LLM_PROVIDER_DOUBAO, LLM_PROVIDER_QWEN, LLM_PROVIDER_SILICONFLOW } from "../../../../../constants";
import { translateRuntimeMessage } from "../../../../../i18n/runtimeLanguage";

export interface LlmProviderPreset {
  provider: string;
  label: string;
  defaultBaseUrl: string;
  defaultModel: string;
  suggestedModels: string[];
  browserCors: "supported" | "proxy-only";
  dropRepetitionPenalty?: boolean;
  dropFrequencyPresenceOnReasoning?: boolean;
}

export const LLM_PROVIDER_PRESETS: Record<string, LlmProviderPreset> = {
  [LLM_PROVIDER_SILICONFLOW]: {
    provider: LLM_PROVIDER_SILICONFLOW,
    get label() {
      return translateRuntimeMessage("plat.standalone.preset.siliconflow");
    },
    defaultBaseUrl: "https://api.siliconflow.cn/v1",
    defaultModel: "deepseek-ai/DeepSeek-V3",
    suggestedModels: [
      "deepseek-ai/DeepSeek-V3",
      "deepseek-ai/DeepSeek-R1",
      "Qwen/Qwen2.5-72B-Instruct",
      "Qwen/Qwen2.5-32B-Instruct",
    ],
    browserCors: "supported",
  },
  Deepseek: {
    provider: "Deepseek",
    label: "DeepSeek",
    defaultBaseUrl: "https://api.deepseek.com/v1",
    defaultModel: "deepseek-chat",
    suggestedModels: ["deepseek-chat", "deepseek-reasoner"],
    browserCors: "supported",
    dropRepetitionPenalty: true,
    dropFrequencyPresenceOnReasoning: true,
  },
  ChatGPT: {
    provider: "ChatGPT",
    get label() {
      return translateRuntimeMessage("plat.standalone.preset.chatgpt");
    },
    defaultBaseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4o-mini",
    suggestedModels: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
    browserCors: "supported",
    dropRepetitionPenalty: true,
    dropFrequencyPresenceOnReasoning: true,
  },
  Gemini: {
    provider: "Gemini",
    get label() {
      return translateRuntimeMessage("plat.standalone.preset.gemini");
    },
    defaultBaseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    defaultModel: "gemini-2.5-flash",
    suggestedModels: ["gemini-2.5-flash", "gemini-2.5-pro"],
    browserCors: "supported",
    dropRepetitionPenalty: true,
  },
  Claude: {
    provider: "Claude",
    label: "Anthropic Claude",
    defaultBaseUrl: "https://api.anthropic.com/v1",
    defaultModel: "claude-3-5-sonnet-latest",
    suggestedModels: ["claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
    browserCors: "supported",
    dropRepetitionPenalty: true,
  },
  [LLM_PROVIDER_DOUBAO]: {
    provider: LLM_PROVIDER_DOUBAO,
    get label() {
      return translateRuntimeMessage("plat.standalone.preset.doubao");
    },
    defaultBaseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    defaultModel: "doubao-pro-32k",
    suggestedModels: ["doubao-1-5-pro-32k-250115", "doubao-pro-32k"],
    browserCors: "proxy-only",
    dropRepetitionPenalty: true,
  },
  [LLM_PROVIDER_QWEN]: {
    provider: LLM_PROVIDER_QWEN,
    get label() {
      return translateRuntimeMessage("plat.standalone.preset.qwen");
    },
    defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    defaultModel: "qwen-plus",
    suggestedModels: ["qwen-plus", "qwen-turbo", "qwen-max"],
    browserCors: "supported",
    dropRepetitionPenalty: true,
  },
  Moonshot: {
    provider: "Moonshot",
    label: "Kimi (Moonshot AI)",
    defaultBaseUrl: "https://api.moonshot.cn/v1",
    defaultModel: "moonshot-v1-8k",
    suggestedModels: ["moonshot-v1-8k", "moonshot-v1-32k"],
    browserCors: "supported",
    dropRepetitionPenalty: true,
  },
  OpenRouter: {
    provider: "OpenRouter",
    label: "OpenRouter",
    defaultBaseUrl: "https://openrouter.ai/api/v1",
    defaultModel: "openai/gpt-4o-mini",
    suggestedModels: ["openai/gpt-4o-mini", "deepseek/deepseek-chat", "anthropic/claude-3.5-sonnet"],
    browserCors: "supported",
    dropRepetitionPenalty: true,
  },
  Ollama: {
    provider: "Ollama",
    get label() {
      return translateRuntimeMessage("plat.standalone.preset.ollama");
    },
    defaultBaseUrl: "http://127.0.0.1:11434/v1",
    defaultModel: "qwen2.5:7b",
    suggestedModels: ["qwen2.5:7b", "llama3.1:8b"],
    browserCors: "supported",
  },
};

export function getLlmProviderPreset(provider: string): LlmProviderPreset {
  const key = provider.trim();
  return (
    LLM_PROVIDER_PRESETS[key] ?? {
      provider: key || "ChatGPT",
      label: key || "OpenAI Compatible",
      defaultBaseUrl: "https://api.openai.com/v1",
      defaultModel: "gpt-4o-mini",
      suggestedModels: ["gpt-4o-mini"],
      browserCors: "supported",
      dropRepetitionPenalty: true,
    }
  );
}

export function isReasoningModel(model: string): boolean {
  const m = model.toLowerCase();
  return m.includes("reasoner") || m.includes("deepseek-r1") || /(?:^|[/-])o[134](?:-|$)/.test(m) || m.includes("qwq");
}

export function filterUnsupportedSamplingParams(
  provider: string,
  model: string,
  payload: Record<string, unknown>,
): Record<string, unknown> {
  const preset = getLlmProviderPreset(provider);
  const next = { ...payload };
  if (preset.dropRepetitionPenalty) {
    delete next.repetition_penalty;
  }
  if (isReasoningModel(model)) {
    delete next.presence_penalty;
    delete next.frequency_penalty;
    delete next.repetition_penalty;
    if (/^o[134]/.test(model.toLowerCase())) {
      delete next.temperature;
    }
  }
  return next;
}
