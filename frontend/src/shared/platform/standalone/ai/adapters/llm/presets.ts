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
  硅基流动: {
    provider: "硅基流动",
    label: "硅基流动 (SiliconFlow · 对话+语音一Key通用)",
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
    label: "OpenAI / 通用兼容",
    defaultBaseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4o-mini",
    suggestedModels: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
    browserCors: "supported",
    dropRepetitionPenalty: true,
    dropFrequencyPresenceOnReasoning: true,
  },
  Gemini: {
    provider: "Gemini",
    label: "Google Gemini (OpenAI 兼容)",
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
  豆包: {
    provider: "豆包",
    label: "字节豆包 (火山引擎)",
    defaultBaseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    defaultModel: "doubao-pro-32k",
    suggestedModels: ["doubao-1-5-pro-32k-250115", "doubao-pro-32k"],
    browserCors: "proxy-only",
    dropRepetitionPenalty: true,
  },
  通义千问: {
    provider: "通义千问",
    label: "阿里通义千问 (DashScope)",
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
    label: "Ollama (本地 / 局域网)",
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
