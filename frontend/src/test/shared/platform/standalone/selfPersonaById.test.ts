import { describe, expect, it } from "vitest";

import {
  SELF_PERSONA_ID,
  SELF_PERSONA_NAME,
  SELF_PERSONA_SPRITE_PREFIX,
} from "../../../../shared/playerCharacterOptions";
import { sampleConfig } from "../../../../shared/platform/sampleData";
import { createCharactersPreviewPlatform } from "../../../../shared/platform/slices/characterPreviewPlatform";
import type { Character } from "../../../../shared/platform/slices/characterTypes";
import { createBrowserPreviewContext } from "../../../../shared/platform/slices/previewContext";
import type { TemplateLaunchSession } from "../../../../shared/platform/slices/workspaceTypes";
import { buildStandaloneDialogSystemPrompt } from "../../../../shared/platform/standalone/ai/dialogPromptBuilder";
import { generateStandaloneTemplateSummary } from "../../../../shared/platform/standalone/ai/templateGenerator";
import { migrateStandaloneSelfPersonaDisplayName } from "../../../../shared/platform/standalone/storage/selfPersonaMigration";

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

describe("selfPersonaById standalone & preview workflows", () => {
  it("migrates legacy self display_name into name, cascades relations/sessions, skips collisions, and is idempotent", () => {
    const selfPersona = makeCharacter({
      id: SELF_PERSONA_ID,
      name: SELF_PERSONA_NAME,
      display_name: "浅羽",
      is_builtin: true,
      pinned: true,
      undeletable: true,
      sprite_prefix: SELF_PERSONA_SPRITE_PREFIX,
      relation_graph: {
        nodes: [{ key: SELF_PERSONA_NAME }, { key: "星奈" }],
        edges: [{ source: SELF_PERSONA_NAME, target: "星奈", temperature: 6, content: "同学" }],
      },
    });
    const heroine = makeCharacter({
      name: "星奈",
      relation_graph: {
        nodes: [{ key: "星奈" }, { key: SELF_PERSONA_NAME }],
        edges: [{ source: "星奈", target: SELF_PERSONA_NAME, temperature: 7, content: "同伴" }],
      },
    });
    const session: TemplateLaunchSession = {
      background: "",
      effectNames: [],
      filenameStub: "session",
      historyPath: "./data/history/session.json",
      initSpritePath: "",
      maxDialogItems: 4,
      maxSpeechChars: 120,
      playerCharacter: SELF_PERSONA_NAME,
      primaryCharacters: [SELF_PERSONA_NAME],
      roomId: "room-1",
      scenario: "",
      selectedCharacters: [SELF_PERSONA_NAME, "星奈"],
      system: "",
      templateFileDropdown: "",
      useCg: false,
      useChoice: true,
      useCot: false,
      useEffect: true,
      useNarration: true,
      useStat: false,
      useTranslation: false,
      voiceLanguage: "ja",
    };

    const firstRun = migrateStandaloneSelfPersonaDisplayName([selfPersona, heroine], session);
    expect(firstRun).toEqual({ configChanged: true, templateSessionChanged: true });
    expect(selfPersona.id).toBe(SELF_PERSONA_ID);
    expect(selfPersona.name).toBe("浅羽");
    expect(selfPersona.display_name).toBe("");
    expect(heroine.relation_graph?.nodes.map((n) => n.key)).toEqual(["星奈", "浅羽"]);
    expect(heroine.relation_graph?.edges[0]).toMatchObject({ source: "星奈", target: "浅羽" });
    expect(session.playerCharacter).toBe("浅羽");
    expect(session.selectedCharacters).toEqual(["浅羽", "星奈"]);
    expect(session.primaryCharacters).toEqual(["浅羽"]);

    const secondRun = migrateStandaloneSelfPersonaDisplayName([selfPersona, heroine], session);
    expect(secondRun).toEqual({ configChanged: false, templateSessionChanged: false });

    // Collision skip when another character already owns target display_name
    const blockedSelf = makeCharacter({
      id: SELF_PERSONA_ID,
      name: SELF_PERSONA_NAME,
      display_name: "星奈",
      is_builtin: true,
      pinned: true,
      undeletable: true,
      sprite_prefix: SELF_PERSONA_SPRITE_PREFIX,
    });
    const collisionRun = migrateStandaloneSelfPersonaDisplayName([blockedSelf, heroine]);
    expect(collisionRun).toEqual({ configChanged: false, templateSessionChanged: false });
    expect(blockedSelf.name).toBe(SELF_PERSONA_NAME);
    expect(blockedSelf.display_name).toBe("星奈");
  });

  it("renders renamed self-persona name and self identity note in standalone generation and background prompts", () => {
    const heroine = makeCharacter({ name: "星奈", character_setting: "Observatory senpai." });
    const selfPersona = makeCharacter({
      id: SELF_PERSONA_ID,
      name: "浅羽",
      sprite_prefix: SELF_PERSONA_SPRITE_PREFIX,
      is_builtin: true,
      pinned: true,
      undeletable: true,
      character_setting: "Likes stargazing and black coffee.",
    });

    const castCheck = generateStandaloneTemplateSummary(
      { name: "cast", characters: ["浅羽", "星奈"], backgroundName: "" },
      {
        characters: [selfPersona, heroine],
        background_list: [],
        system_config: { ...structuredClone(sampleConfig.system_config), ui_language: "zh_CN" },
      },
    );
    expect(castCheck.system).toContain("以下是浅羽的角色设定：");
    expect(castCheck.system).toContain("该人物是用户自设。");
    expect(castCheck.system).not.toContain("以下是自设的角色设定：");

    const enCast = generateStandaloneTemplateSummary(
      { name: "cast-en", characters: ["浅羽", "星奈"], backgroundName: "" },
      {
        characters: [selfPersona, heroine],
        background_list: [],
        system_config: { ...structuredClone(sampleConfig.system_config), ui_language: "en" },
      },
    );
    expect(enCast.system).toContain("This character is the user's self-persona.");
    expect(enCast.system).toContain("Profile for 浅羽:");

    const jaBg = generateStandaloneTemplateSummary(
      { name: "bg-ja", characters: ["星奈"], backgroundName: "", playerCharacter: "" },
      {
        characters: [selfPersona, heroine],
        background_list: [],
        system_config: { ...structuredClone(sampleConfig.system_config), ui_language: "ja" },
      },
    );
    expect(jaBg.system).toContain("キャラクター名：浅羽（この人物はユーザーの自設です。）");

    const legacySystem = [
      "出场人物有：星奈",
      "",
      "【用户自设设定】",
      "Old setting",
      "（以上是当前与你对话的用户本人的背景与偏好设定；请在互动中自然知晓并贴合，不要将「自设」作为独立台词角色输出。）",
    ].join("\n");
    const runtimePrompt = buildStandaloneDialogSystemPrompt({
      characters: [selfPersona, heroine],
      systemConfig: { ui_language: "zh_CN", voice_language: "ja" },
      payload: {
        templateId: "runtime-self",
        characters: ["浅羽", "星奈"],
        backgroundName: "",
        historyPath: "./data/history/runtime-self.json",
        playerCharacter: "",
        scenario: "天台夜谈",
        system: legacySystem,
      },
    });
    expect(runtimePrompt).not.toContain("不要将「自设」作为独立台词角色输出");
    expect(runtimePrompt).toContain("「浅羽」（用户自设）已作为独立出场角色参与本次对话");
    expect(runtimePrompt).toContain("以下是浅羽的角色设定：");
    expect(runtimePrompt).toContain("该人物是用户自设。");
  });

  it("preserves __self__ invariants, cascades playerCharacter, and normalizes memory agentId in preview platform", async () => {
    const ctx = createBrowserPreviewContext();
    const selfPersona = makeCharacter({
      id: SELF_PERSONA_ID,
      name: SELF_PERSONA_NAME,
      sprite_prefix: SELF_PERSONA_SPRITE_PREFIX,
      is_builtin: true,
      pinned: true,
      undeletable: true,
    });
    ctx.config.characters = [selfPersona, ...ctx.config.characters.filter((c) => c.name !== SELF_PERSONA_NAME)];
    ctx.setTemplateSession({
      background: "",
      effectNames: [],
      filenameStub: "preview-session",
      historyPath: "./data/history/preview.json",
      initSpritePath: "",
      maxDialogItems: 4,
      maxSpeechChars: 120,
      playerCharacter: SELF_PERSONA_NAME,
      roomId: "preview-room",
      scenario: "",
      selectedCharacters: [SELF_PERSONA_NAME],
      system: "",
      templateFileDropdown: "",
      useCg: false,
      useChoice: true,
      useCot: false,
      useEffect: true,
      useNarration: true,
      useStat: false,
      useTranslation: false,
      voiceLanguage: "ja",
    });

    const slice = createCharactersPreviewPlatform(ctx);
    const saved = await slice.save(
      { ...structuredClone(selfPersona), name: "浅羽", sprite_prefix: "hacked_prefix" },
      SELF_PERSONA_NAME,
    );
    expect(saved.id).toBe(SELF_PERSONA_ID);
    expect(saved.name).toBe("浅羽");
    expect(saved.sprite_prefix).toBe(SELF_PERSONA_SPRITE_PREFIX);
    expect(saved.is_builtin).toBe(true);
    expect(saved.pinned).toBe(true);
    expect(saved.undeletable).toBe(true);
    expect(ctx.getTemplateSession()?.playerCharacter).toBe("浅羽");

    await slice.remember("浅羽", "Likes espresso");
    const listed = await slice.listMemories("浅羽");
    expect(listed.agentId).toBe(SELF_PERSONA_ID);
    expect(listed.memories.some((m) => m.memory === "Likes espresso")).toBe(true);
  });
});
