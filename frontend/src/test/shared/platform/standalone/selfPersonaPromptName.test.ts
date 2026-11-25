import { afterEach, describe, expect, it, vi } from "vitest";

import { sampleConfig } from "../../../../shared/platform/sampleData";
import type { Character } from "../../../../shared/platform/slices/characterTypes";
import type { ChatSnapshot, ChatStageEvent } from "../../../../shared/platform/slices/chatTypes";
import { buildStandaloneDialogSystemPrompt } from "../../../../shared/platform/standalone/ai/dialogPromptBuilder";
import { standaloneHttpRequest } from "../../../../shared/platform/standalone/ai/httpClient";
import { StandaloneChatTurnDriver } from "../../../../shared/platform/standalone/ai/standaloneChatTurn";
import {
  findCharacterByPromptName,
  generateStandaloneDialogSystemTemplate,
  resolveCharacterPromptName,
} from "../../../../shared/platform/standalone/ai/templateGenerator";
import { StandaloneSessionStore } from "../../../../shared/platform/standalone/storage/sessionStore";

function makeCharacter(overrides: Partial<Character> & { name: string }): Character {
  const base = sampleConfig.characters[0];
  return {
    ...structuredClone(base),
    character_brief: "",
    relation_graph: undefined,
    sprite_groups: [],
    default_sprite_group: undefined,
    fallback_to_default_group: true,
    sprites: [
      { path: `/sprites/${overrides.name}-01.png`, group: "默认" },
      { path: `/sprites/${overrides.name}-02.png`, group: "默认" },
    ],
    emotion_tags: "1:微笑\n2:沉思",
    ...overrides,
  };
}

describe("self-persona display name in standalone prompts and turn driver", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders display_name with identity note across NPC cast, player modes, background-only, and relations", () => {
    const heroine = makeCharacter({
      name: "星奈",
      character_setting: "观测台学姐。",
      relation_graph: {
        nodes: [{ key: "星奈" }, { key: "自设" }],
        edges: [{ source: "星奈", target: "自设", temperature: 6, content: "默契搭档" }],
      },
    });
    const selfPersona = makeCharacter({
      name: "自设",
      display_name: "浅羽",
      character_setting: "随身携带怀表的调查员。",
      relation_graph: {
        nodes: [{ key: "自设" }, { key: "星奈" }],
        edges: [{ source: "自设", target: "星奈", temperature: 5, content: "信赖学姐" }],
      },
    });

    const castResult = generateStandaloneDialogSystemTemplate({
      input: { name: "cast", characters: ["星奈", "自设"], backgroundName: "", useEffect: false },
      characters: [heroine, selfPersona],
      backgrounds: [],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
    });
    expect(castResult.system).toContain("出场人物有：星奈，浅羽");
    expect(castResult.system).toContain("浅羽有2张立绘：");
    expect(castResult.system).toContain("以下是浅羽的角色设定：\n该人物是用户自设。\n随身携带怀表的调查员。");
    expect(castResult.system).toContain("浅羽的关系图谱：\n浅羽对星奈：信赖学姐(亲密度：5)");
    expect(castResult.system).toContain("星奈的关系图谱：\n星奈对浅羽：默契搭档(亲密度：6)");
    expect(castResult.system).not.toContain("不要将「");

    const playerResult = generateStandaloneDialogSystemTemplate({
      input: {
        name: "player",
        characters: ["星奈", "自设"],
        backgroundName: "",
        playerCharacter: "自设",
        allowPlayerDialogue: false,
        useEffect: false,
      },
      characters: [heroine, selfPersona],
      backgrounds: [],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
    });
    expect(playerResult.system).toContain("用户控制的主控人物：浅羽\n该人物是用户自设。\n随身携带怀表的调查员。");
    expect(playerResult.system).toContain('{"character_name":"浅羽","sprite":"01","speech":""}');

    const bgPrompt = buildStandaloneDialogSystemPrompt({
      characters: [heroine, selfPersona],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
      payload: {
        templateId: "bg-only",
        characters: ["星奈"],
        backgroundName: "",
        historyPath: "./data/history/bg-only.json",
        scenario: "日常",
      },
    });
    expect(bgPrompt).toContain("人物名称：浅羽（该人物是用户自设）\n随身携带怀表的调查员。");
    expect(bgPrompt).toContain("不要将「浅羽」作为独立台词角色输出");

    const playerRuntimePrompt = buildStandaloneDialogSystemPrompt({
      characters: [heroine, selfPersona],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
      payload: {
        templateId: "player-runtime",
        characters: ["星奈", "自设"],
        playerCharacter: "自设",
        backgroundName: "",
        historyPath: "./data/history/player-runtime.json",
        scenario: "日常",
      },
    });
    expect(playerRuntimePrompt).toContain("【当前主控称呼】浅羽");

    // Collision falls back safely to 自设
    const colliding = makeCharacter({ name: "浅羽", character_setting: "同名角色" });
    expect(resolveCharacterPromptName(selfPersona, ["星奈", "浅羽", "自设"])).toBe("自设");
    expect(findCharacterByPromptName([selfPersona, colliding], "浅羽")?.name).toBe("浅羽");
    expect(findCharacterByPromptName([heroine, selfPersona], "浅羽")?.name).toBe("自设");
  });

  it("strips legacy named/unnamed self_persona_block and resolves LLM display_name speaker in StandaloneChatTurnDriver", async () => {
    const heroine = makeCharacter({ name: "星奈", character_setting: "Observatory senpai." });
    const selfPersona = makeCharacter({
      name: "自设",
      display_name: "浅羽",
      character_setting: "Traveler carrying a pocket watch.",
    });

    const legacyNamedSystem = [
      "出场人物有：星奈",
      "",
      "【用户自设设定】",
      "人物名称：浅羽（该人物是用户自设）",
      "Traveler carrying a pocket watch.",
      "（以上是当前与你对话的用户本人的背景与偏好设定；请在互动中自然知晓并贴合，不要将「浅羽」作为独立台词角色输出。）",
      "",
      "必须以规定的 JSON 格式回复。",
    ].join("\n");

    const prompt = buildStandaloneDialogSystemPrompt({
      characters: [heroine, selfPersona],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
      payload: {
        templateId: "legacy-named-self",
        characters: ["自设", "星奈"],
        backgroundName: "",
        historyPath: "./data/history/legacy-named-self.json",
        scenario: "星海观测台",
        system: legacyNamedSystem,
      },
    });
    expect(prompt).not.toContain("不要将「浅羽」作为独立台词角色输出");
    expect(prompt).toContain("以下是浅羽的角色设定：\n该人物是用户自设。\nTraveler carrying a pocket watch.");
    expect(prompt).toContain("「浅羽」（该人物是用户自设）已作为独立出场角色");

    const store = new StandaloneSessionStore();
    const session = await store.ensureSession({
      historyPath: "./data/history/self-turn.json",
      title: "self-turn",
      payload: {
        templateId: "self-turn",
        characters: ["自设", "星奈"],
        backgroundName: "",
        historyPath: "./data/history/self-turn.json",
        playerCharacter: "自设",
        allowPlayerDialogue: true,
        scenario: "测试",
      },
      outfits: {},
    });

    let chatSnapshot: ChatSnapshot = {
      sessionId: session.sessionId,
      historyPath: session.historyPath,
      chatProcessRunning: true,
      chatRuntimeClosing: false,
      status: "idle",
      sprites: [],
      stats: [],
      options: [],
      historyEntries: [],
      characterName: "浅羽",
      dialogText: "",
      dialogHtml: "",
      inputDraft: "",
      userDisplayName: "浅羽",
    };
    const events: ChatStageEvent[] = [];
    globalThis.fetch = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            choices: [
              {
                message: {
                  content: JSON.stringify({
                    dialog: [{ character_name: "浅羽", sprite: "02", speech: "出发吧。" }],
                  }),
                },
              },
            ],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    ) as typeof fetch;

    let driver!: StandaloneChatTurnDriver;
    driver = new StandaloneChatTurnDriver({
      getApiConfig: () => ({
        ...sampleConfig.api_config,
        llm_provider: "ChatGPT",
        llm_api_key: { ChatGPT: "sk-test" },
        llm_base_urls: { ChatGPT: "https://api.openai.com/v1" },
        llm_model: { ChatGPT: "gpt-4o-mini" },
        tts_provider: "none",
      }),
      getCharacters: () => [selfPersona, heroine],
      getSystemConfig: () => ({ ui_language: "zh_CN", voice_language: "ja" }),
      getChat: () => chatSnapshot,
      setChat: (next) => {
        chatSnapshot = next;
      },
      emitChat: () => {},
      emitStageEvent: (event) => {
        events.push(event);
        if (event.type === "dialog.end") {
          globalThis.setTimeout(() => driver.handleDialogAdvance(), 0);
        }
      },
      sessionStore: store,
      httpClient: standaloneHttpRequest,
      resolveFileUrl: (path) => path,
    });

    await driver.runTurn({ session, userText: "走吧" });
    expect(
      events.some((e) => e.type === "sprite.show" && e.characterName === "浅羽" && e.url === "/sprites/自设-02.png"),
    ).toBe(true);
    expect(events.some((e) => e.type === "dialog.end" && e.speaker === "浅羽")).toBe(true);
  });
});
