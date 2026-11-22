import { describe, expect, it } from "vitest";

import {
  DEFAULT_SPRITE_GROUP,
  LLM_PROVIDER_DOUBAO,
  LLM_PROVIDER_QWEN,
  LLM_PROVIDER_SILICONFLOW,
  TRANSPARENT_BACKGROUND_NAME,
} from "../../../shared/constants";
import {
  formatBackgroundName,
  formatCharacterDisplayName,
  formatLlmProviderLabel,
  formatSpriteGroupLabel,
  translateMessage,
  type FrontendLanguage,
} from "../../../shared/i18n";
import { SELF_PERSONA_NAME } from "../../../shared/playerCharacterOptions";

const tFor =
  (language: FrontendLanguage) =>
  (key: Parameters<typeof translateMessage>[1], values?: Record<string, number | string>) =>
    translateMessage(language, key, values);

describe("domainLabels display-layer formatters", () => {
  it("formats canonical CJK LLM provider storage values per active UI language", () => {
    expect(formatLlmProviderLabel(LLM_PROVIDER_DOUBAO, tFor("zh_CN"))).toBe("豆包");
    expect(formatLlmProviderLabel(LLM_PROVIDER_DOUBAO, tFor("en"))).toBe("Doubao");
    expect(formatLlmProviderLabel(LLM_PROVIDER_QWEN, tFor("en"))).toBe("Qwen");
    expect(formatLlmProviderLabel(LLM_PROVIDER_SILICONFLOW, tFor("en"))).toBe("SiliconFlow");
    expect(formatLlmProviderLabel("Deepseek", tFor("ja"))).toBe("Deepseek");
    expect(formatLlmProviderLabel("custom_llm", tFor("en"), "Custom LLM")).toBe("Custom LLM");
  });

  it("formats transparent background sentinel without mutating custom names", () => {
    expect(formatBackgroundName(TRANSPARENT_BACKGROUND_NAME, tFor("zh_CN"))).toBe("透明场景");
    expect(formatBackgroundName(TRANSPARENT_BACKGROUND_NAME, tFor("en"))).toBe(
      translateMessage("en", "domain.background.transparent"),
    );
    expect(formatBackgroundName(TRANSPARENT_BACKGROUND_NAME, tFor("ja"))).toBe(
      translateMessage("ja", "domain.background.transparent"),
    );
    expect(formatBackgroundName("Classroom Sunset", tFor("en"))).toBe("Classroom Sunset");
  });

  it("formats self persona sentinel while respecting explicit display_name overrides", () => {
    expect(formatCharacterDisplayName(SELF_PERSONA_NAME, tFor("en"))).toBe("User persona");
    expect(formatCharacterDisplayName(SELF_PERSONA_NAME, tFor("ja"))).toBe(
      translateMessage("ja", "domain.character.selfPersona"),
    );
    expect(formatCharacterDisplayName({ name: SELF_PERSONA_NAME, display_name: "Takina" }, tFor("en"))).toBe("Takina");
    expect(formatCharacterDisplayName({ name: SELF_PERSONA_NAME, display_name: "" }, tFor("en"))).toBe("User persona");
    expect(
      formatCharacterDisplayName({ name: "Nanami", display_name: "ShouldNotOverrideNormalChar" }, tFor("en")),
    ).toBe("Nanami");
  });

  it("formats default sprite group sentinel and empty group names", () => {
    expect(formatSpriteGroupLabel(DEFAULT_SPRITE_GROUP, tFor("zh_CN"))).toBe("默认");
    expect(formatSpriteGroupLabel(DEFAULT_SPRITE_GROUP, tFor("en"))).toBe("Default");
    expect(formatSpriteGroupLabel("", tFor("ja"))).toBe("デフォルト");
    expect(formatSpriteGroupLabel(undefined, tFor("en"))).toBe("Default");
    expect(formatSpriteGroupLabel("casual", tFor("en"))).toBe("casual");
  });
});
