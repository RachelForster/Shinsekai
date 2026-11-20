import type { LlmModelOption } from "../../../../slices/configTypes";
import { standaloneHttpJson, type StandaloneHttpClient } from "../../httpClient";
import type { StandaloneLlmAdapter, StandaloneLlmInput, StandaloneLlmResult } from "../types";
import { filterUnsupportedSamplingParams, getLlmProviderPreset } from "./presets";

interface OpenAiChatCompletionResponse {
  model?: string;
  choices?: Array<{
    message?: {
      content?: string | Array<{ type?: string; text?: string }>;
      reasoning_content?: string;
    };
    text?: string;
  }>;
  usage?: {
    total_tokens?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
  };
}

interface OpenAiModelsListResponse {
  data?: Array<{ id?: string }>;
}

function normalizeBaseUrl(rawUrl: string, provider: string): string {
  const fallback = getLlmProviderPreset(provider).defaultBaseUrl;
  const trimmed = (rawUrl || fallback).trim().replace(/\/+$/, "");
  return trimmed.replace(/\/chat\/completions$/i, "");
}

function extractChoiceText(data: OpenAiChatCompletionResponse): string {
  const first = data.choices?.[0];
  if (!first) return "";
  const msgContent = first.message?.content;
  if (typeof msgContent === "string") {
    return msgContent;
  }
  if (Array.isArray(msgContent)) {
    return msgContent.map((part) => (typeof part?.text === "string" ? part.text : "")).join("");
  }
  return typeof first.text === "string" ? first.text : "";
}

function buildHeaders(provider: string, apiKey: string): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const trimmedKey = apiKey.trim();
  if (trimmedKey) {
    headers.Authorization = `Bearer ${trimmedKey}`;
  }
  if (provider.trim().toLowerCase() === "openrouter") {
    headers["X-Title"] = "Shinsekai";
  }
  return headers;
}

export const openaiCompatibleLlmAdapter: StandaloneLlmAdapter = {
  id: "openai-compatible",
  label: "OpenAI Compatible (DeepSeek / SiliconFlow / Qwen / ChatGPT / Custom)",
  browserCors: "supported",
  supportsProvider(provider) {
    return provider.trim().toLowerCase() !== "claude";
  },
  async complete(input: StandaloneLlmInput, http: StandaloneHttpClient): Promise<StandaloneLlmResult> {
    const preset = getLlmProviderPreset(input.provider);
    const baseUrl = normalizeBaseUrl(input.baseUrl, input.provider);
    const model = (input.model || preset.defaultModel).trim();
    const apiKey = input.apiKey.trim();
    if (!apiKey && input.provider !== "Ollama") {
      throw new Error(`请先填写 ${input.provider} 的 API Key。`);
    }

    const basePayload: Record<string, unknown> = {
      model,
      messages: input.messages.map((m) => ({
        role: m.role,
        content: m.content,
      })),
      stream: false,
      ...(input.temperature !== undefined ? { temperature: input.temperature } : {}),
      ...(input.presencePenalty !== undefined ? { presence_penalty: input.presencePenalty } : {}),
      ...(input.frequencyPenalty !== undefined ? { frequency_penalty: input.frequencyPenalty } : {}),
      ...(input.repetitionPenalty !== undefined ? { repetition_penalty: input.repetitionPenalty } : {}),
      ...(input.maxTokens !== undefined ? { max_tokens: input.maxTokens } : {}),
    };

    const filteredPayload = filterUnsupportedSamplingParams(input.provider, model, basePayload);

    const { data } = await standaloneHttpJson<OpenAiChatCompletionResponse>({
      url: `${baseUrl}/chat/completions`,
      method: "POST",
      headers: buildHeaders(input.provider, apiKey),
      body: JSON.stringify(filteredPayload),
      timeoutMs: 90_000,
      signal: input.signal,
    });

    const content = extractChoiceText(data);
    if (!content.trim()) {
      throw new Error("LLM 返回内容为空，请检查模型名称与配额。");
    }

    const usageTokens =
      typeof data.usage?.total_tokens === "number"
        ? data.usage.total_tokens
        : typeof data.usage?.prompt_tokens === "number" && typeof data.usage?.completion_tokens === "number"
          ? data.usage.prompt_tokens + data.usage.completion_tokens
          : undefined;

    return {
      content,
      usageTokens,
      model: data.model ?? model,
    };
  },
  async fetchModels(input, http): Promise<LlmModelOption[]> {
    const preset = getLlmProviderPreset(input.provider);
    const baseUrl = normalizeBaseUrl(input.baseUrl, input.provider);
    const fallback = preset.suggestedModels.map((id) => ({ id, tags: [] }));
    const apiKey = input.apiKey.trim();
    if (!apiKey && input.provider !== "Ollama") {
      return fallback;
    }

    try {
      const { data } = await standaloneHttpJson<OpenAiModelsListResponse>({
        url: `${baseUrl}/models`,
        method: "GET",
        headers: buildHeaders(input.provider, apiKey),
        timeoutMs: 15_000,
      });
      const ids = (data.data ?? []).map((item) => item?.id?.trim() ?? "").filter(Boolean);
      if (!ids.length) return fallback;
      const merged = Array.from(new Set([...ids, ...preset.suggestedModels]));
      return merged.map((id) => ({ id, tags: [] }));
    } catch {
      return fallback;
    }
  },
  async testConnection(input, http): Promise<{ message: string }> {
    const preset = getLlmProviderPreset(input.provider);
    const model = (input.model || preset.defaultModel).trim();
    const result = await this.complete(
      {
        provider: input.provider,
        apiKey: input.apiKey,
        baseUrl: input.baseUrl,
        model,
        messages: [{ role: "user", content: "Reply with OK only." }],
        maxTokens: 16,
        temperature: 0,
      },
      http,
    );
    return {
      message: `连接成功 (${result.model || model})`,
    };
  },
};
