import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { platformErrorCode } from "../../../../shared/platform/errors";
import { resetPlatformForModeSwitch } from "../../../../shared/platform/platform";
import { sampleConfig } from "../../../../shared/platform/sampleData";
import type { Character } from "../../../../shared/platform/slices/characterTypes";
import type { ChatSnapshot, ChatStageEvent } from "../../../../shared/platform/slices/chatTypes";
import type { Background, Effect } from "../../../../shared/platform/slices/workspaceTypes";
import { createStandalonePlatform } from "../../../../shared/platform/standalone";
import { parseStandaloneDialogOutput } from "../../../../shared/platform/standalone/ai/dialogOutputParser";
import { buildStandaloneDialogSystemPrompt } from "../../../../shared/platform/standalone/ai/dialogPromptBuilder";
import { standaloneHttpRequest } from "../../../../shared/platform/standalone/ai/httpClient";
import { StandaloneChatTurnDriver } from "../../../../shared/platform/standalone/ai/standaloneChatTurn";
import {
  buildStandaloneEffectCatalogBlock,
  generateStandaloneDialogSystemTemplate,
} from "../../../../shared/platform/standalone/ai/templateGenerator";
import { clearAllStandaloneStorage } from "../../../../shared/platform/standalone/storage/indexedDbStore";
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
    emotion_tags: "1:微笑、温柔\n2:害羞、低头",
    ...overrides,
  };
}

function makeBackground(overrides: Partial<Background> = {}): Background {
  return {
    name: "星海观测台",
    sprite_prefix: "observatory",
    sprites: [{ path: "/bg/obs-night.png" }, { path: "/bg/obs-dawn.png" }],
    bg_tags: "1:夜晚、星海观测台\n2:清晨、露台阳光",
    bgm_list: ["/bgm/night-piano.mp3", "/bgm/dawn-breeze.mp3"],
    bgm_tags: "1:安静、温柔钢琴、夜色\n2:轻快、清晨微风",
    ...overrides,
  };
}

function makeEffect(overrides: Partial<Effect> = {}): Effect {
  return {
    name: "观测室音效",
    color: "#38bdf8",
    prompt_text: "",
    audio_list: ["/eff/chime.mp3", "/eff/rain.mp3"],
    audio_tags: "风铃声, chime\n雨声",
    image_list: ["/eff/star-map.png", "/eff/meteor.png"],
    image_tags: "星图投影\n流星闪过",
    image_audio_list: ["", "/eff/meteor.mp3"],
    ...overrides,
  };
}

describe("standalone template generation & dialog protocol", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(async () => {
    await clearAllStandaloneStorage();
    window.localStorage?.clear();
    resetPlatformForModeSwitch();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = originalFetch;
    resetPlatformForModeSwitch();
  });

  it("seeds starter template with generated system prompt and implements templates.generate + ensureBriefs", async () => {
    const platform = createStandalonePlatform({ target: "toy" });

    const starterList = await platform.templates.list();
    expect(starterList.length).toBeGreaterThan(0);
    expect(starterList[0].system).toContain('"dialog"');
    expect(starterList[0].content).toContain(starterList[0].scenario || "");

    const charA = makeCharacter({ name: "Hoshina", character_setting: "星海观测台的天文学少女，冷静又细心。" });
    const charB = makeCharacter({
      name: "Mina",
      character_setting: "来自地下城的机械师。",
      character_brief: "直爽的机械师同伴。",
    });
    await platform.characters.save(charA);
    await platform.characters.save(charB);
    await platform.backgrounds.save(makeBackground());

    const briefBatch = await platform.characters.ensureBriefs(["hoshina", "Mina", "已删除角色"]);
    expect(briefBatch.generatedNames).toEqual(["Hoshina"]);
    expect(briefBatch.characters.map((c) => c.name)).toEqual(["Hoshina", "Mina"]);
    expect(briefBatch.characters[0].character_brief?.trim().length).toBeGreaterThan(0);
    expect(briefBatch.characters[1].character_brief).toBe("直爽的机械师同伴。");

    const updatedChars = await platform.characters.list();
    expect(updatedChars.find((c) => c.name === "Hoshina")?.character_brief).toBe(
      briefBatch.characters[0].character_brief,
    );

    const generated = await platform.templates.generate({
      name: "星夜协奏",
      scenario: "两人在天文台观测流星雨。",
      characters: ["hoshina", "已删除角色", "MINA"],
      backgroundName: "星海观测台",
      voiceLanguage: "en",
      useTranslation: true,
    });
    expect(generated.resolvedCharacters).toEqual(["Hoshina", "Mina"]);
    expect(generated.system).toContain("以下是Hoshina的角色设定");
    expect(generated.system).toContain("以下是Mina的角色设定");
    expect(generated.system).toContain("英语译文");
    expect(generated.content).toContain("两人在天文台观测流星雨。");

    const cfgAfter = await platform.config.get();
    expect(cfgAfter.system_config.voice_language).toBe("en");

    let capturedErr: unknown;
    try {
      await platform.templates.generate({
        name: "无效角色",
        scenario: "无人舞台",
        characters: ["不存在的角色1", "不存在的角色2"],
        backgroundName: "",
      });
    } catch (err) {
      capturedErr = err;
    }
    expect(platformErrorCode(capturedErr)).toBe("no_valid_characters");
  });

  it("handles compact mode, outfit sprite filtering, semantic vibe vs full sprite IDs, and background vs transparent scene", () => {
    const lead = makeCharacter({
      name: "星奈",
      character_setting: "女主星奈完整设定：星海观测台守护者。",
      character_brief: "星奈简介",
      sprite_groups: ["默认", "礼服"],
      default_sprite_group: "礼服",
      sprites: [
        { path: "/s/01.png", group: "默认" },
        { path: "/s/02.png", group: "礼服" },
        { path: "/s/03.png", group: "礼服" },
      ],
      emotion_tags: "1:日常微笑\n2:晚礼服浅笑\n3:晚礼服惊讶",
      relation_graph: {
        nodes: [{ key: "星奈" }, { key: "米娜" }, { key: "路人甲" }],
        edges: [
          { source: "星奈", target: "米娜", temperature: 8, content: "值得信赖的搭档" },
          { source: "星奈", target: "未选中", temperature: 2, content: "普通熟人" },
          { source: "陌生人", target: "路人", temperature: 0, content: "" },
        ],
      },
    });
    const support = makeCharacter({
      name: "米娜",
      character_setting: "次要角色米娜的超长完整设定（compact 模式不应展开）",
      character_brief: "热情开朗的辅助研究员。",
      relation_graph: {
        nodes: [{ key: "米娜" }, { key: "星奈" }],
        edges: [{ source: "米娜", target: "星奈", temperature: 7, content: "敬佩前辈" }],
      },
    });
    const bg = makeBackground();

    const compactRes = generateStandaloneDialogSystemTemplate({
      input: {
        name: "compact-test",
        characters: ["星奈", "米娜"],
        primaryCharacters: ["星奈"],
        characterPromptMode: "compact",
        backgroundName: "星海观测台",
        mediaSelectionMode: "indexed",
      },
      characters: [lead, support],
      backgrounds: [bg],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
    });

    expect(compactRes.system).toContain("以下是星奈的角色设定");
    expect(compactRes.system).not.toContain("次要角色米娜的超长完整设定");
    expect(compactRes.system).toContain("次要角色简介");
    expect(compactRes.system).toContain("米娜：热情开朗的辅助研究员。");
    expect(compactRes.system).toContain("2:晚礼服浅笑, 3:晚礼服惊讶");
    expect(compactRes.system).not.toContain("1:日常微笑");
    expect(compactRes.system).toContain("星奈的关系图谱：");
    expect(compactRes.system).toContain("星奈对米娜：值得信赖的搭档(亲密度：8)");
    expect(compactRes.system).not.toContain("米娜的关系图谱：");
    expect(compactRes.system).not.toContain("陌生人对路人");
    expect(compactRes.system).toContain("场景说明：");
    expect(compactRes.system).toContain("BGM说明：");
    expect(compactRes.system).toContain("两位数字代号（例如 01, 02）");

    const semanticTransparentRes = generateStandaloneDialogSystemTemplate({
      input: {
        name: "semantic-transparent",
        characters: ["星奈"],
        backgroundName: "透明场景",
        mediaSelectionMode: "semantic",
      },
      characters: [lead],
      backgrounds: [bg],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
    });

    expect(semanticTransparentRes.mediaSelectionMode).toBe("semantic");
    expect(semanticTransparentRes.system).toContain('"vibe"');
    expect(semanticTransparentRes.system).not.toContain("立绘说明:");
    expect(semanticTransparentRes.system).not.toContain("场景说明：");
    expect(semanticTransparentRes.system).not.toContain("BGM说明：");
    expect(semanticTransparentRes.system).not.toContain("SCENE");
    expect(semanticTransparentRes.system).not.toContain(", bgm");

    const hugeSpriteChar = makeCharacter({
      name: "千咲",
      sprites: Array.from({ length: 105 }, (_, i) => ({ path: `/huge/${i + 1}.png`, group: "默认" })),
      emotion_tags: "1:普通",
    });
    const fullSpriteRes = generateStandaloneDialogSystemTemplate({
      input: { name: "full-sprite-ids", characters: ["千咲"], backgroundName: "", mediaSelectionMode: "indexed" },
      characters: [hugeSpriteChar],
      backgrounds: [],
      systemConfig: { ui_language: "zh_CN" },
    });
    expect(fullSpriteRes.system).toContain("完整的立绘 ID 字符串");
  });

  it("handles player control modes, 自设 persona injection, translation gating, and UI localization (en/ja)", () => {
    const hero = makeCharacter({ name: "主人公", character_setting: "观测站新任实习生。" });
    const heroine = makeCharacter({ name: "星奈", character_setting: "温柔的天文台前辈。" });
    const selfPersona = makeCharacter({
      name: "自设",
      character_setting: "喜欢夜间喝热可可、随身带着怀表的旅人。",
    });

    const userControlledNoRead = generateStandaloneDialogSystemTemplate({
      input: {
        name: "player-no-read",
        characters: ["主人公", "星奈"],
        backgroundName: "",
        playerCharacter: "主人公",
        allowPlayerDialogue: false,
        readPlayerSpeech: false,
      },
      characters: [hero, heroine],
      backgrounds: [],
      systemConfig: { ui_language: "zh_CN", voice_language: "zh" },
    });
    expect(userControlledNoRead.system).toContain("出场人物有：星奈");
    expect(userControlledNoRead.system).toContain("用户控制的主控人物：主人公");
    expect(userControlledNoRead.system).toContain("不要为主人公输出朗读项");
    expect(userControlledNoRead.system).not.toContain("translate");

    const userControlledWithReadAndTrans = generateStandaloneDialogSystemTemplate({
      input: {
        name: "player-read-trans",
        characters: ["主人公", "星奈"],
        backgroundName: "",
        playerCharacter: "主人公",
        allowPlayerDialogue: false,
        readPlayerSpeech: true,
        useTranslation: true,
        voiceLanguage: "ja",
      },
      characters: [hero, heroine],
      backgrounds: [],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
    });
    expect(userControlledWithReadAndTrans.system).toContain("朗读主控输入时，在头像项之前添加一个独立 dialog 项");
    expect(userControlledWithReadAndTrans.system).toContain("日语译文");

    const aiControlledWithSelf = generateStandaloneDialogSystemTemplate({
      input: {
        name: "player-ai",
        characters: ["主人公", "星奈"],
        backgroundName: "",
        playerCharacter: "主人公",
        allowPlayerDialogue: true,
      },
      characters: [hero, heroine],
      backgrounds: [],
      systemConfig: { ui_language: "zh_CN" },
    });
    expect(aiControlledWithSelf.system).toContain("允许 AI 为主人公编写新的台词和回答");

    const selfInjected = generateStandaloneDialogSystemTemplate({
      input: {
        name: "self-persona",
        characters: ["星奈"],
        backgroundName: "",
      },
      characters: [heroine, selfPersona],
      backgrounds: [],
      systemConfig: { ui_language: "zh_CN" },
    });
    expect(selfInjected.system).toContain("【用户自设设定】");
    expect(selfInjected.system).toContain("喜欢夜间喝热可可");

    const enRes = generateStandaloneDialogSystemTemplate({
      input: {
        name: "en-locale",
        characters: ["星奈"],
        backgroundName: "星海观测台",
        useTranslation: true,
        voiceLanguage: "ja",
      },
      characters: [heroine],
      backgrounds: [makeBackground()],
      systemConfig: { ui_language: "en", voice_language: "ja" },
    });
    expect(enRes.system).toContain("Cast includes: 星奈");
    expect(enRes.system).toContain("Requirements:");
    expect(enRes.system).toContain("Japanese rendering of the speech line");

    const jaSameVoiceRes = generateStandaloneDialogSystemTemplate({
      input: {
        name: "ja-locale",
        characters: ["星奈"],
        backgroundName: "",
        useTranslation: true,
        voiceLanguage: "ja",
      },
      characters: [heroine],
      backgrounds: [],
      systemConfig: { ui_language: "ja", voice_language: "ja" },
    });
    expect(jaSameVoiceRes.system).toContain("登場人物：星奈");
    expect(jaSameVoiceRes.system).not.toContain('"translate"');
  });

  it("builds runtime system prompts with effect catalogs and parses full protocol entries", () => {
    const hoshina = makeCharacter({
      name: "星奈",
      sprite_groups: ["默认", "礼服"],
      default_sprite_group: "默认",
    });
    const effect = makeEffect();
    const effectCatalog = buildStandaloneEffectCatalogBlock([effect], ["观测室音效"], "zh_CN");
    expect(effectCatalog).toContain("可用特效标签：");
    expect(effectCatalog).toContain("- 风铃声 [音频; before, after, loop, stop]");
    expect(effectCatalog).toContain("- chime [音频; before, after, loop, stop]");
    expect(effectCatalog).toContain("- 星图投影 [图片; before, after]");
    expect(effectCatalog).toContain("- 流星闪过 [图片及绑定音频; before, after]");

    const fullPrompt = buildStandaloneDialogSystemPrompt({
      characters: [hoshina],
      backgrounds: [makeBackground()],
      effects: [effect],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
      payload: {
        templateId: "tpl-custom",
        characters: ["星奈"],
        backgroundName: "星海观测台",
        effectNames: ["观测室音效"],
        scenario: "星奈正在调试赤道仪。",
        historyPath: "./data/history/tpl-custom.json",
      },
      outfits: {
        星奈: { characterName: "星奈", activeGroup: "礼服", locked: true, updatedAtMs: 1 },
      },
      stats: [{ icon: "heart", label: "信赖", value: 75, max: 100 }],
      userDisplayName: "观测者",
    });
    expect(fullPrompt).toContain('"dialog"');
    expect(fullPrompt).toContain("【当前主控称呼】观测者");
    expect(fullPrompt).toContain("【当前服装状态】星奈: 礼服（已锁定，请勿更换）");
    expect(fullPrompt).toContain("【当前舞台数值】信赖: 75/100");
    expect(fullPrompt).toContain("星奈正在调试赤道仪。");
    expect(fullPrompt).toContain("必须以规定的 JSON 格式回复。");

    const parsed = parseStandaloneDialogOutput(
      JSON.stringify({
        dialog: [
          { character_name: "COT", sprite: "-1", speech: "<摘要>测试</摘要><动机>无</动机><剧情走向>继续</剧情走向>" },
          { character_name: "CG", sprite: "-1", speech: "1girl, starlight" },
          { character_name: "STAT", sprite: "-1", speech: "heart|信赖|82|100\nstar|星尘|15" },
          { character_name: "SCENE", sprite: "02", speech: "" },
          { character_name: "bgm", vibe: "清晨微风", speech: "" },
          { character_name: "星奈", sprite: "02", speech: "早上好。", effect: "风铃声" },
          { character_name: "星奈", sprite: "-1", speech: "我先去整理观测记录。", effect: "LEAVE" },
          { character_name: "米娜", vibe: "害羞", effect: "LEAVE" },
          { character_name: "CHOICE", sprite: "-1", speech: "帮忙拿笔记本 / 目送她离开 / 泡两杯热茶" },
        ],
      }),
      "星奈",
    );

    expect(
      parsed.some((item) => "characterName" in item && (item.characterName === "COT" || item.characterName === "CG")),
    ).toBe(false);
    expect(parsed).toEqual([
      {
        kind: "stat",
        stats: [
          { icon: "heart", label: "信赖", value: 82, max: 100 },
          { icon: "star", label: "星尘", value: 15 },
        ],
      },
      { kind: "scene", sprite: "02", vibe: undefined },
      { kind: "bgm", sprite: undefined, vibe: "清晨微风" },
      {
        kind: "speech",
        characterName: "星奈",
        speech: "早上好。",
        translate: undefined,
        sprite: "02",
        vibe: undefined,
        outfit: undefined,
        isNarration: false,
      },
      {
        kind: "speech",
        characterName: "星奈",
        speech: "我先去整理观测记录。",
        translate: undefined,
        sprite: "-1",
        vibe: undefined,
        outfit: undefined,
        leave: true,
        isNarration: false,
      },
      {
        kind: "portrait",
        characterName: "米娜",
        sprite: undefined,
        vibe: "害羞",
        outfit: undefined,
        leave: true,
      },
      {
        kind: "choice",
        options: ["帮忙拿笔记本", "目送她离开", "泡两杯热茶"],
      },
    ]);
  });

  it("drives a complete turn handling SCENE, bgm, -1 keep sprite, semantic vibe, and LEAVE removal", async () => {
    const store = new StandaloneSessionStore();
    await store.hydrate();
    const hoshina = makeCharacter({
      name: "星奈",
      sprites: [{ path: "/s/h-01.png" }, { path: "/s/h-02.png" }],
      emotion_tags: "1:微笑、温柔\n2:害羞、脸红",
    });
    const mina = makeCharacter({
      name: "米娜",
      sprites: [{ path: "/s/m-01.png" }, { path: "/s/m-02.png" }],
      emotion_tags: "1:得意、自信\n2:惊喜、挥手",
    });
    const chisaki = makeCharacter({
      name: "千咲",
      sprites: [{ path: "/s/c-01.png" }, { path: "/s/c-02.png" }],
      emotion_tags: "1:平静\n2:微笑",
    });
    const background = makeBackground();

    const session = await store.ensureSession({
      historyPath: "./data/history/turn-protocol.json",
      title: "协议联调",
      payload: {
        templateId: "tpl-protocol",
        characters: ["星奈", "米娜", "千咲"],
        backgroundName: "星海观测台",
        mediaSelectionMode: "semantic",
        effectNames: ["观测室音效"],
        historyPath: "./data/history/turn-protocol.json",
      },
    });

    let chatSnapshot: ChatSnapshot = {
      status: "idle",
      dialogText: "",
      inputDraft: "",
      options: [],
      sprites: [
        {
          id: "sprite-星奈",
          identityKey: "星奈",
          label: "星奈",
          path: "/s/h-initial.png",
          scale: 1,
          avatarType: "static",
          modelUrl: "",
        },
      ],
      stats: [],
      backgroundPath: "/bg/obs-night.png",
      bgmPath: "/bgm/night-piano.mp3",
    };
    const events: ChatStageEvent[] = [];

    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            choices: [
              {
                message: {
                  content: JSON.stringify({
                    dialog: [
                      {
                        character_name: "COT",
                        sprite: "-1",
                        speech: "<摘要>切换晨景</摘要><动机>告别</动机><剧情走向>下一幕</剧情走向>",
                      },
                      { character_name: "STAT", sprite: "-1", speech: "heart|羁绊|90|100" },
                      { character_name: "SCENE", sprite: "02", speech: "" },
                      { character_name: "bgm", vibe: "清晨微风", speech: "" },
                      { character_name: "星奈", sprite: "-1", speech: "看，天亮了。" },
                      { character_name: "千咲", sprite: "02", speech: "" },
                      { character_name: "千咲", effect: "LEAVE", speech: "" },
                      { character_name: "米娜", vibe: "惊喜", speech: "早上好呀，我先回工坊啦。", effect: "LEAVE" },
                      { character_name: "CHOICE", sprite: "-1", speech: "陪星奈收起望远镜 / 追上米娜" },
                    ],
                  }),
                },
              },
            ],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    globalThis.fetch = fetchMock as typeof fetch;

    let driver!: StandaloneChatTurnDriver;
    driver = new StandaloneChatTurnDriver({
      getApiConfig: () => ({
        ...sampleConfig.api_config,
        llm_provider: "ChatGPT",
        llm_api_key: { ChatGPT: "sk-test-token" },
        llm_base_urls: { ChatGPT: "https://api.openai.com/v1" },
        llm_model: { ChatGPT: "gpt-4o-mini" },
        tts_provider: "none",
      }),
      getCharacters: () => [hoshina, mina, chisaki],
      getBackgrounds: () => [background],
      getEffects: () => [makeEffect()],
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

    await driver.runTurn({ session, userText: "早安，太阳升起来了吗？" });

    expect(fetchMock).toHaveBeenCalledOnce();
    const firstCallInit = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    const reqBody = JSON.parse(String(firstCallInit.body)) as { messages: Array<{ role: string; content: string }> };
    expect(reqBody.messages[0]?.role).toBe("system");
    expect(reqBody.messages[0]?.content).toContain("可用特效标签：");

    expect(chatSnapshot.backgroundPath).toBe("/bg/obs-dawn.png");
    expect(chatSnapshot.bgmPath).toBe("/bgm/dawn-breeze.mp3");
    expect(chatSnapshot.stats).toEqual([{ icon: "heart", label: "羁绊", value: 90, max: 100 }]);
    expect(chatSnapshot.options).toEqual(["陪星奈收起望远镜", "追上米娜"]);
    expect(chatSnapshot.sprites.map((s) => [s.label, s.path])).toEqual([["星奈", "/s/h-initial.png"]]);

    expect(events.some((e) => e.type === "background.change" && e.url === "/bg/obs-dawn.png")).toBe(true);
    expect(events.some((e) => e.type === "bgm.change" && e.url === "/bgm/dawn-breeze.mp3")).toBe(true);
    expect(events.some((e) => e.type === "sprite.show" && e.characterName === "千咲" && e.url === "/s/c-02.png")).toBe(
      true,
    );
    expect(events.some((e) => e.type === "sprite.remove" && e.characterName === "千咲")).toBe(true);
    expect(events.some((e) => e.type === "sprite.show" && e.characterName === "米娜" && e.url === "/s/m-02.png")).toBe(
      true,
    );
    expect(events.some((e) => e.type === "sprite.show" && e.characterName === "星奈")).toBe(false);
    expect(events.some((e) => e.type === "sprite.remove" && e.characterName === "米娜")).toBe(true);
  });

  it("switches self-persona and runtime state supplements together with ui_language across zh_CN, en, and ja", () => {
    const heroine = makeCharacter({
      name: "星奈",
      character_setting: "Observatory senpai.",
      sprite_groups: ["默认", "礼服"],
      default_sprite_group: "默认",
    });
    const selfPersona = makeCharacter({
      name: "自设",
      character_setting: "Traveler carrying a pocket watch.",
    });

    const cases = [
      {
        ui_language: "zh_CN",
        personaHeader: "【用户自设设定】",
        playerMarker: "【当前主控称呼】旅人",
        outfitMarker: "【当前服装状态】星奈: 礼服（已锁定，请勿更换）",
        statsMarker: "【当前舞台数值】HP: 80/100，MP: 40",
        emptyScenario: "你扮演一个RPG系统。",
        fallbackPrompt: '请严格依据场景设定，用 JSON `{ "dialog": [...] }` 格式驱动交互对话。',
      },
      {
        ui_language: "en",
        personaHeader: "[User Persona]",
        playerMarker: "[Current Player] 旅人",
        outfitMarker: "[Current Outfit State] 星奈: 礼服 (locked, do not change)",
        statsMarker: "[Current Stage Stats] HP: 80/100, MP: 40",
        emptyScenario: "You act as an RPG system.",
        fallbackPrompt:
          'Strictly follow the scenario setting and drive the interactive dialogue in JSON `{ "dialog": [...] }` format.',
      },
      {
        ui_language: "ja",
        personaHeader: "【ユーザー自設設定】",
        playerMarker: "【現在の主控呼称】旅人",
        outfitMarker: "【現在の衣装状態】星奈: 礼服（ロック中・変更不可）",
        statsMarker: "【現在の舞台ステータス】HP: 80/100、MP: 40",
        emptyScenario: "あなたはRPGシステムとして振る舞います。",
        fallbackPrompt: 'シナリオ設定に厳密に従い、JSON `{ "dialog": [...] }` 形式で対話を進行してください。',
      },
    ] as const;

    for (const c of cases) {
      const prompt = buildStandaloneDialogSystemPrompt({
        characters: [heroine, selfPersona],
        systemConfig: { ui_language: c.ui_language, voice_language: "ja" },
        payload: {
          templateId: `tpl-${c.ui_language}`,
          characters: ["星奈"],
          backgroundName: "",
          historyPath: `./data/history/${c.ui_language}.json`,
          scenario: "",
        },
        userDisplayName: "旅人",
        outfits: { 星奈: { characterName: "星奈", activeGroup: "礼服", locked: true, updatedAtMs: 1 } },
        stats: [
          { icon: "heart", label: "HP", value: 80, max: 100 },
          { icon: "zap", label: "MP", value: 40 },
        ],
      });
      expect(prompt).toContain(c.personaHeader);
      expect(prompt).toContain(c.playerMarker);
      expect(prompt).toContain(c.outfitMarker);
      expect(prompt).toContain(c.statsMarker);
      expect(prompt).toContain(c.emptyScenario);

      const fallback = buildStandaloneDialogSystemPrompt({
        characters: [],
        systemConfig: { ui_language: c.ui_language },
        payload: {
          templateId: `tpl-fallback-${c.ui_language}`,
          characters: [],
          backgroundName: "",
          historyPath: `./data/history/fallback-${c.ui_language}.json`,
          scenario: "",
        },
      });
      expect(fallback).toContain(c.fallbackPrompt);
      expect(fallback).toContain(c.emptyScenario);
    }
  });
});
