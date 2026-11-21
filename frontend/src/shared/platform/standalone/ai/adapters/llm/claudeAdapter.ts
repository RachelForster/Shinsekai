import type { LlmModelOption } from "../../../../slices/configTypes";
import { standaloneHttpJson, type StandaloneHttpClient } from "../../httpClient";
import type { StandaloneLlmAdapter, StandaloneLlmInput, StandaloneLlmResult } from "../types";
import { getLlmProviderPreset } from "./presets";

interface ClaudeMessageResponse {
  model?: string;
  content?: Array<{ type?: string; text?: string }>;
  usage?: {
    input_tokens?: number;
    output_tokens?: number;
  };
}

function normalizeClaudeBaseUrl(rawUrl: string): string {
  const fallback = getLlmProviderPreset("Claude").defaultBaseUrl;
  return (rawUrl || fallback)
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/messages$/i, "");
}

function convertMessagesForClaude(messages: StandaloneLlmInput["messages"]): {
  system: string;
  turns: Array<{ role: "user" | "assistant"; content: string }>;
} {
  const systemParts: string[] = [];
  const rawTurns: Array<{ role: "user" | "assistant"; content: string }> = [];

  for (const msg of messages) {
    if (msg.role === "system") {
      if (msg.content.trim()) systemParts.push(msg.content.trim());
      continue;
    }
    const role: "user" | "assistant" = msg.role === "assistant" ? "assistant" : "user";
    const text = msg.content.trim() || " ";
    const prev = rawTurns[rawTurns.length - 1];
    if (prev && prev.role === role) {
      prev.content = `${prev.content}\n\n${text}`;
    } else {
      rawTurns.push({ role, content: text });
    }
  }

  if (rawTurns.length && rawTurns[0].role !== "user") {
    rawTurns.unshift({ role: "user", content: "继续对话" });
  }
  if (!rawTurns.length) {
    rawTurns.push({ role: "user", content: "你好" });
  }

  return {
    system: systemParts.join("\n\n"),
    turns: rawTurns,
  };
}

export const claudeLlmAdapter: StandaloneLlmAdapter = {
  id: "claude",
  label: "Anthropic Claude",
  browserCors: "supported",
  supportsProvider(provider) {
    return provider.trim().toLowerCase() === "claude";
  },
  async complete(input: StandaloneLlmInput, http: StandaloneHttpClient): Promise<StandaloneLlmResult> {
    const apiKey = input.apiKey.trim();
    if (!apiKey) {
      throw new Error("请先填写 Claude API Key。");
    }
    const preset = getLlmProviderPreset("Claude");
    const baseUrl = normalizeClaudeBaseUrl(input.baseUrl);
    const model = (input.model || preset.defaultModel).trim();
    const { system, turns } = convertMessagesForClaude(input.messages);

    const payload: Record<string, unknown> = {
      model,
      max_tokens: input.maxTokens ?? 2048,
      messages: turns,
      ...(system ? { system } : {}),
      ...(input.temperature !== undefined ? { temperature: Math.min(1, Math.max(0, input.temperature)) } : {}),
    };

    const { data } = await standaloneHttpJson<ClaudeMessageResponse>({
      url: `${baseUrl}/messages`,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "anthropic-dangerous-direct-browser-access": "true",
      },
      body: JSON.stringify(payload),
      timeoutMs: 90_000,
      signal: input.signal,
    });

    const content = (data.content ?? []).map((item) => (typeof item?.text === "string" ? item.text : "")).join("");
    if (!content.trim()) {
      throw new Error("Claude 返回内容为空。");
    }
    const inputTokens = data.usage?.input_tokens ?? 0;
    const outputTokens = data.usage?.output_tokens ?? 0;
    return {
      content,
      usageTokens: inputTokens + outputTokens > 0 ? inputTokens + outputTokens : undefined,
      model: data.model ?? model,
    };
  },
  async fetchModels(): Promise<LlmModelOption[]> {
    return getLlmProviderPreset("Claude").suggestedModels.map((id) => ({ id, tags: [] }));
  },
  async testConnection(input, http): Promise<{ message: string }> {
    const preset = getLlmProviderPreset("Claude");
    const model = (input.model || preset.defaultModel).trim();
    const res = await this.complete(
      {
        provider: "Claude",
        apiKey: input.apiKey,
        baseUrl: input.baseUrl,
        model,
        messages: [{ role: "user", content: "Reply with OK only." }],
        maxTokens: 16,
      },
      http,
    );
    return { message: `连接成功 (${res.model || model})` };
  },
};
