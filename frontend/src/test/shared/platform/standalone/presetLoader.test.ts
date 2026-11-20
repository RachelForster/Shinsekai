import { describe, expect, it } from "vitest";

import type { Character } from "../../../../shared/platform/slices/characterTypes";
import type { Background } from "../../../../shared/platform/slices/workspaceTypes";
import {
  BUNDLED_HOSHINA_SPRITES,
  BUNDLED_STARTER_BG_URL,
  BUNDLED_STARTER_SPRITE_URL,
  STARTER_HOSHINA_PORTRAIT_CROP,
  advancePrologueStep,
  createInitialPrologueState,
  createStarterBackground,
  createStarterCharacter,
  resolveBundledStarterAssetUrl,
  upgradeStarterPresetsInPlace,
} from "../../../../shared/platform/standalone/packages/presetLoader";

describe("bundled starter Hoshina & Observatory presetLoader", () => {
  it("builds starter character 星奈 with 10 distinct .webp sprites, 10 emotion tags, pink theme color, and head portrait crop", () => {
    const hoshina = createStarterCharacter();
    expect(hoshina.name).toBe("星奈");
    expect(hoshina.color).toBe("#f472b6");
    expect(hoshina.sprite_prefix).toBe("starter_hoshina");
    expect(hoshina.portrait_crop).toEqual(STARTER_HOSHINA_PORTRAIT_CROP);
    expect(hoshina.sprites).toHaveLength(10);

    const uniquePaths = new Set(hoshina.sprites.map((sp) => sp.path));
    expect(uniquePaths.size).toBe(10);
    for (const sprite of hoshina.sprites) {
      expect(sprite.path).toMatch(/\.webp(?:$|\?)/i);
      expect(sprite.group).toBe("常服");
      expect(sprite.portrait_crop).toEqual(STARTER_HOSHINA_PORTRAIT_CROP);
    }

    const tagLines = hoshina.emotion_tags.split("\n").filter(Boolean);
    expect(tagLines).toHaveLength(10);
    expect(hoshina.character_setting).toContain("双半丸子头");
    expect(hoshina.character_setting).toContain("星星手环");
  });

  it("builds starter background 星海观测台 using observatory_bg.webp rather than shinsekai.png", () => {
    const bg = createStarterBackground();
    expect(bg.name).toBe("星海观测台");
    expect(bg.sprite_prefix).toBe("starter_observatory");
    expect(bg.sprites).toHaveLength(1);
    expect(bg.sprites[0].path).toBe(BUNDLED_STARTER_BG_URL);
    expect(bg.sprites[0].path).toContain("observatory_bg");
    expect(bg.sprites[0].path).toMatch(/\.webp(?:$|\?)/i);
    expect(bg.sprites[0].path).not.toContain("shinsekai.png");
  });

  it("upgrades legacy 3-sprite starter_hoshina and shinsekai.png starter_observatory while leaving custom characters untouched", () => {
    const legacyHoshina: Character = {
      ...createStarterCharacter(),
      color: "#7dd3fc",
      portrait_crop: undefined,
      refer_audio_path: "vfs://characters/starter_hoshina/models/custom_ref.wav",
      sprites: [
        { path: "/assets/present_example.png", group: "常服", voice_text: "欢迎" },
        { path: "/assets/present_example.png", group: "常服" },
        { path: "/assets/present_example.png", group: "常服" },
      ],
      emotion_tags: "立绘 1：微笑\n立绘 2：欣喜\n立绘 3：若有所思",
    };
    const customChar: Character = {
      ...createStarterCharacter(),
      name: "原创旅伴",
      color: "#38bdf8",
      sprite_prefix: "custom_companion",
      sprites: [{ path: "vfs://characters/custom/1.png", group: "常服" }],
      emotion_tags: "立绘 1：默认",
    };
    const legacyBg: Background = {
      name: "星海观测台",
      sprite_prefix: "starter_observatory",
      sprites: [{ path: "/assets/system/picture/shinsekai.png" }],
      bg_tags: "旧标签",
      bgm_list: [],
      bgm_tags: "",
    };

    const mutated = upgradeStarterPresetsInPlace([legacyHoshina, customChar], [legacyBg]);
    expect(mutated).toBe(true);

    expect(legacyHoshina.sprites).toHaveLength(10);
    expect(legacyHoshina.sprites[0].path).toBe(BUNDLED_STARTER_SPRITE_URL);
    expect(legacyHoshina.sprites[0].voice_text).toBe("欢迎");
    expect(legacyHoshina.refer_audio_path).toBe("vfs://characters/starter_hoshina/models/custom_ref.wav");
    expect(legacyHoshina.color).toBe("#f472b6");
    expect(legacyHoshina.portrait_crop).toEqual(STARTER_HOSHINA_PORTRAIT_CROP);
    expect(legacyHoshina.emotion_tags.split("\n")).toHaveLength(10);

    expect(legacyBg.sprites[0].path).toBe(BUNDLED_STARTER_BG_URL);
    expect(legacyBg.bg_tags).toContain("玻璃穹顶");

    // Custom user character stays completely intact
    expect(customChar.name).toBe("原创旅伴");
    expect(customChar.sprites).toEqual([{ path: "vfs://characters/custom/1.png", group: "常服" }]);
    expect(customChar.color).toBe("#38bdf8");

    // Second pass is idempotent
    expect(upgradeStarterPresetsInPlace([legacyHoshina, customChar], [legacyBg])).toBe(false);
  });

  it("rewrites legacy and hashed starter asset URLs cleanly while ignoring unrelated assets", () => {
    expect(resolveBundledStarterAssetUrl("/assets/present_example.png")).toBe(BUNDLED_STARTER_SPRITE_URL);
    expect(resolveBundledStarterAssetUrl("./web-assets/present_example-Ab12Cd34.png")).toBe(
      BUNDLED_STARTER_SPRITE_URL,
    );
    expect(resolveBundledStarterAssetUrl("/assets/system/picture/shinsekai.png")).toBe(BUNDLED_STARTER_BG_URL);
    expect(resolveBundledStarterAssetUrl("https://example.com/web-assets/shinsekai-99ff0011.png")).toBe(
      BUNDLED_STARTER_BG_URL,
    );
    expect(resolveBundledStarterAssetUrl("./web-assets/observatory_bg-12ab34cd.webp")).toBe(BUNDLED_STARTER_BG_URL);
    expect(resolveBundledStarterAssetUrl("./web-assets/hoshina_08_wink-cafe5678.webp")).toBe(
      BUNDLED_HOSHINA_SPRITES[7].url,
    );
    expect(resolveBundledStarterAssetUrl("./web-assets/shinsekai-github-banner-1234.png")).toBeNull();
    expect(resolveBundledStarterAssetUrl("vfs://characters/custom/sprite.png")).toBeNull();
    expect(resolveBundledStarterAssetUrl("blob:http://localhost/123")).toBeNull();
  });

  it("assigns valid 0..9 expression indices across prologue branches", () => {
    const initial = createInitialPrologueState("星奈");
    expect(initial.segments.every((seg) => seg.spriteIndex >= 0 && seg.spriteIndex < 10)).toBe(true);

    const explore = advancePrologueStep("intro_0", "四处看看，这里都可以做什么？", "星奈");
    const importStep = advancePrologueStep("intro_0", "我有自己的角色卡，怎么导入这里？", "星奈");
    const apiStep = advancePrologueStep("intro_0", "我想直接配置 API Key 开启自由对话！", "星奈");
    const mobileStep = advancePrologueStep("intro_explore_1", "如果是手机版，还能连回电脑端吗？", "星奈");
    const fallbackStep = advancePrologueStep("intro_complete", "你好呀星奈", "星奈");

    const allIndices = [
      ...explore.segments,
      ...importStep.segments,
      ...apiStep.segments,
      ...mobileStep.segments,
      ...fallbackStep.segments,
    ].map((seg) => seg.spriteIndex);

    expect(new Set(allIndices).size).toBeGreaterThanOrEqual(5);
    for (const idx of allIndices) {
      expect(idx).toBeGreaterThanOrEqual(0);
      expect(idx).toBeLessThan(10);
    }
  });
});
