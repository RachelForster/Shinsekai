import { describe, expect, it } from "vitest";

import { buildStandaloneAdapterCatalog } from "../../../../shared/platform/standalone/ai/adapters/registry";
import { parseStandaloneDialogOutput } from "../../../../shared/platform/standalone/ai/dialogOutputParser";
import {
  ToyCloudCheckpointBridge,
  computeRateLimitBackoffMs,
  isToyRateLimitError,
} from "../../../../shared/platform/standalone/toy/toySdkBridge";

describe("dialogOutputParser, adapters & toySdkBridge", () => {
  it("parses JSON dialog blocks after stripping <think> and code fences", () => {
    const raw = `
<think>先想一下星奈要怎么回答……</think>
\`\`\`json
{
  "dialog": [
    { "character_name": "星奈", "speech": "星海风声很温柔呢。", "sprite": 2, "outfit": "礼服" },
    { "character_name": "NARR", "speech": "星奈仰起头望着穹顶。" },
    { "character_name": "STAT", "stats": [{ "label": "好感度", "value": 68, "max": 100, "icon": "heart" }] },
    { "character_name": "CHOICE", "options": ["坐下聊聊", "继续观星",] }
  ]
}
\`\`\`
`;
    const entries = parseStandaloneDialogOutput(raw, "星奈");
    expect(entries).toHaveLength(4);
    expect(entries[0]).toMatchObject({
      kind: "speech",
      characterName: "星奈",
      speech: "星海风声很温柔呢。",
      sprite: 2,
      outfit: "礼服",
      isNarration: false,
    });
    expect(entries[1]).toMatchObject({
      kind: "speech",
      isNarration: true,
      characterName: "NARR",
    });
    expect(entries[2]).toMatchObject({
      kind: "stat",
      stats: [{ label: "好感度", value: 68, max: 100, icon: "heart" }],
    });
    expect(entries[3]).toEqual({
      kind: "choice",
      options: ["坐下聊聊", "继续观星"],
    });
  });

  it("falls back to clean spoken segments when model outputs plain prose", () => {
    const entries = parseStandaloneDialogOutput("今晚的星星真美啊。\n\n我们去天台走走好吗？", "星奈");
    expect(entries).toHaveLength(2);
    expect(entries[0]).toMatchObject({ kind: "speech", characterName: "星奈", speech: "今晚的星星真美啊。" });
    expect(entries[1]).toMatchObject({ kind: "speech", characterName: "星奈", speech: "我们去天台走走好吗？" });
  });

  it("builds declarative adapter catalog distinguishing Toy browser CORS vs Mobile native HTTP", () => {
    const toyCatalog = buildStandaloneAdapterCatalog("toy");
    const mobileCatalog = buildStandaloneAdapterCatalog("mobile");

    expect(toyCatalog.tts.some((item) => item.value === "openai-speech" && item.schema?.reuse_llm_key)).toBe(true);
    expect(toyCatalog.tts.some((item) => item.value === "minimax-tts")).toBe(true);
    expect(toyCatalog.tts.some((item) => item.value === "qwen-tts" && item.label.includes("[网页端需支持跨域]"))).toBe(true);
    expect(mobileCatalog.tts.some((item) => item.value === "qwen-tts" && !item.label.includes("[网页端需支持跨域]"))).toBe(true);
  });

  it("detects Bilibili Toy 307044 rate-limit errors and applies exponential backoff", () => {
    expect(isToyRateLimitError({ code: 307044 })).toBe(true);
    expect(isToyRateLimitError(new Error("failed with 307044 rate limit"))).toBe(true);
    expect(isToyRateLimitError(new Error("other error"))).toBe(false);

    const bridge = new ToyCloudCheckpointBridge();
    expect(computeRateLimitBackoffMs(0)).toBe(5_000);
    expect(computeRateLimitBackoffMs(1)).toBe(10_000);
    expect(computeRateLimitBackoffMs(2)).toBe(20_000);

    const wait1 = bridge.recordRateLimitFailure(1_000_000);
    expect(wait1).toBe(5_000);
    expect(bridge.getBackoffState().blockedUntilMs).toBe(1_005_000);
  });
});
