import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StandaloneLlmAdapter } from "../../../../shared/platform/standalone/ai/adapters/types";
import {
  autoCompactIfNeeded,
  binarySearchCapSummary,
  estimateTextTokens,
  trimMessagesToBudget,
} from "../../../../shared/platform/standalone/ai/compactManager";
import { standaloneHttpRequest } from "../../../../shared/platform/standalone/ai/httpClient";
import { clearAllStandaloneStorage } from "../../../../shared/platform/standalone/storage/indexedDbStore";
import { StandaloneSessionStore } from "../../../../shared/platform/standalone/storage/sessionStore";
import { sampleConfig } from "../../../../shared/platform/sampleData";

describe("compactManager", () => {
  beforeEach(async () => {
    await clearAllStandaloneStorage();
  });

  it("caps overly long summaries via binary search without exceeding token budget", () => {
    const longSummary = "第一段关键记忆。".repeat(200);
    const capped = binarySearchCapSummary(longSummary, 120);
    expect(capped.length).toBeLessThan(longSummary.length);
    expect(estimateTextTokens(capped)).toBeLessThanOrEqual(120);
  });

  it("creates non-destructive CompactCheckpoint and degrades safely when summarizer fails", async () => {
    const store = new StandaloneSessionStore();
    await store.hydrate();
    const session = await store.ensureSession({
      sessionId: "s-compact",
      historyPath: "./data/history/s-compact.json",
      title: "压缩测试",
      payload: {
        templateId: "tpl",
        characters: ["星奈"],
        backgroundName: "观测台",
        historyPath: "./data/history/s-compact.json",
      },
    });

    for (let i = 1; i <= 10; i += 1) {
      await store.appendTurn(session.sessionId, {
        role: i % 2 === 1 ? "user" : "assistant",
        speaker: i % 2 === 1 ? "" : "星奈",
        plainText: `第${i}轮详细对话内容：` + "星海旅途的珍贵回忆记录。".repeat(12),
      });
    }

    const apiConfig = {
      ...sampleConfig.api_config,
      llm_provider: "Deepseek",
      max_context_tokens: 2048,
      compact_threshold: 0.25,
      compact_target_ratio: 0.25,
      history_recent_messages: 4,
    };

    const failingAdapter: StandaloneLlmAdapter = {
      id: "mock-fail",
      label: "mock-fail",
      browserCors: "supported",
      supportsProvider: () => true,
      complete: vi.fn().mockRejectedValue(new Error("Network 503")),
      fetchModels: async () => [],
      testConnection: async () => ({ message: "ok" }),
    };

    const failedRes = await autoCompactIfNeeded({
      sessionId: session.sessionId,
      systemPrompt: "SYSTEM",
      sessionStore: store,
      apiConfig,
      llmAdapter: failingAdapter,
      httpClient: standaloneHttpRequest,
      apiKey: "sk-test",
      baseUrl: "https://example.com/v1",
      model: "deepseek-chat",
    });
    expect(failedRes.compacted).toBe(false);
    expect(store.listCheckpoints(session.sessionId)).toHaveLength(0);
    expect(store.listTurns(session.sessionId)).toHaveLength(10);

    // Deterministic budget trim fallback keeps leading system + tail messages
    const view = store.buildActiveLlmMessages(session.sessionId, "SYSTEM");
    const trimmed = trimMessagesToBudget(view.messages, 600);
    expect(trimmed[0].role).toBe("system");
    expect(trimmed.length).toBeLessThan(view.messages.length);
    expect(trimmed[trimmed.length - 1].content).toContain("第10轮");

    const okAdapter: StandaloneLlmAdapter = {
      ...failingAdapter,
      complete: vi.fn().mockResolvedValue({
        content: "早期共6轮对话浓缩：旅人与星奈回顾了观测台的过往。",
        usageTokens: 100,
      }),
    };

    const okRes = await autoCompactIfNeeded({
      sessionId: session.sessionId,
      systemPrompt: "SYSTEM",
      sessionStore: store,
      apiConfig,
      llmAdapter: okAdapter,
      httpClient: standaloneHttpRequest,
      apiKey: "sk-test",
      baseUrl: "https://example.com/v1",
      model: "deepseek-chat",
    });

    expect(okRes.compacted).toBe(true);
    expect(okRes.checkpoint?.upToSeq).toBe(6);
    expect(store.buildFullRawMessages(session.sessionId)).toHaveLength(10);

    const compactedView = store.buildActiveLlmMessages(session.sessionId, "SYSTEM");
    expect(compactedView.tailNodes.map((n) => n.seq)).toEqual([7, 8, 9, 10]);
  });
});
