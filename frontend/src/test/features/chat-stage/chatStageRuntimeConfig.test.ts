import type { CSSProperties } from "react";
import { describe, expect, it } from "vitest";

import {
  chatStageRuntimeStyle,
  chatStageRuntimeConfigVersion,
  clearMaterializedChatStageAppearance,
  defaultChatStageRuntimeConfig,
  effectiveChatStageTextStyle,
  materializeChatStageAppearanceTheme,
  normalizeChatStageRuntimeConfig,
  readChatStageRuntimeConfig,
} from "../../../features/chat-stage/runtimeConfig";
import { CHAT_THEME_SCHEMA, resolveChatTheme, type ChatThemeManifest } from "../../../shared/theme/chatTheme";

describe("chat stage runtime config", () => {
  it("normalizes legacy unversioned persisted config", () => {
    expect(
      normalizeChatStageRuntimeConfig({
        dialogOpacity: 0.2,
        dialogText: {
          align: "invalid",
          direction: "rtl",
          fontSize: 999,
        },
        spriteScale: 1.4,
        typewriterCps: "48",
      }),
    ).toEqual({
      ...defaultChatStageRuntimeConfig,
      dialogOpacity: 0.35,
      dialogText: {
        ...defaultChatStageRuntimeConfig.dialogText,
        direction: "rtl",
        fontSize: 64,
      },
      spriteScales: { __default__: 1.4 },
      typewriterCps: 48,
    });
  });

  it("normalizes versioned persisted config envelopes", () => {
    expect(
      normalizeChatStageRuntimeConfig({
        config: {
          autoHideInput: false,
          autoHideTopTools: false,
          configThemeColor: "#123abc",
          configUseMainThemeColor: false,
          dialogScale: 1.1,
          immersiveMode: true,
        },
        version: chatStageRuntimeConfigVersion,
      }),
    ).toEqual({
      ...defaultChatStageRuntimeConfig,
      autoHideInput: false,
      autoHideTopTools: false,
      configThemeColor: "#123abc",
      configUseMainThemeColor: false,
      dialogScale: 1.1,
      immersiveMode: true,
    });
  });

  it("falls back safely when persisted JSON is malformed", () => {
    window.localStorage.setItem("shinsekai-chat-stage-runtime-config", "{not-json");

    expect(readChatStageRuntimeConfig()).toEqual(defaultChatStageRuntimeConfig);

    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
  });

  it("uses theme alignment until the runtime config explicitly overrides it", () => {
    const themeStyle = { "--chat-dialog-text-theme-align": "left" } as CSSProperties;
    const runtimeStyle = chatStageRuntimeStyle(defaultChatStageRuntimeConfig, themeStyle) as unknown as Record<
      string,
      unknown
    >;

    expect(
      effectiveChatStageTextStyle(
        defaultChatStageRuntimeConfig.dialogText,
        defaultChatStageRuntimeConfig.dialogText,
        themeStyle,
        "dialogText",
      ).align,
    ).toBe("left");
    expect(runtimeStyle["--chat-dialog-text-align"]).toBe("var(--chat-dialog-text-theme-align, center)");

    const overridden = {
      ...defaultChatStageRuntimeConfig,
      dialogText: {
        ...defaultChatStageRuntimeConfig.dialogText,
        align: "center" as const,
        alignOverride: true,
      },
    };
    const overriddenStyle = chatStageRuntimeStyle(overridden, themeStyle) as unknown as Record<string, unknown>;
    expect(overriddenStyle["--chat-dialog-text-align"]).toBe("center");
  });

  it("materializes compatible session appearance values into an inheritable theme", () => {
    const base: ChatThemeManifest = {
      id: "base-theme",
      name: { en: "Base", zh_CN: "基础" },
      schema: CHAT_THEME_SCHEMA,
      tokens: { dialog: { background: "#111111" }, global: { themeColor: "#445566" } },
    };
    const config = {
      ...defaultChatStageRuntimeConfig,
      dialogFill: {
        ...defaultChatStageRuntimeConfig.dialogFill,
        color: "#223344",
        opacity: 0.75,
      },
      dialogOpacity: 0.65,
      dialogScale: 1.1,
      dialogText: {
        ...defaultChatStageRuntimeConfig.dialogText,
        bold: true,
        boldOverride: true,
        color: "#fefefe",
        fontFamily: "Story Font",
        fontSize: 22,
      },
      nameText: { ...defaultChatStageRuntimeConfig.nameText, color: "#ffddaa" },
      spriteOffsetX: 40,
      typewriterCps: 72,
      windowScale: 0.9,
    };

    const result = materializeChatStageAppearanceTheme(base, config, "base-theme-appearance");

    expect(result).toMatchObject({
      id: "base-theme-appearance",
      name: { en: "Base (Current appearance)", zh_CN: "基础（当前外观）" },
      tokens: {
        dialog: {
          background: "rgba(34, 51, 68, 0.75)",
          color: "#fefefe",
          fontFamily: "Story Font",
          opacity: 0.65,
          scale: 1.1,
          textSizePx: 22,
          textWeight: 700,
        },
        global: { themeColor: "#445566", windowScale: 0.9 },
        name: { color: "#ffddaa" },
        typewriter: { cps: 72 },
      },
    });
    expect(result.tokens).not.toHaveProperty("spriteOffsetX");

    const cleared = clearMaterializedChatStageAppearance(config);
    expect(cleared.spriteOffsetX).toBe(40);
    expect(cleared.dialogOpacity).toBe(1);
    expect(cleared.typewriterCps).toBeNull();
  });

  it("lets theme scale and opacity provide the baseline until the session overrides them", () => {
    const resolved = resolveChatTheme(
      {
        id: "scaled",
        name: { en: "Scaled" },
        schema: CHAT_THEME_SCHEMA,
        tokens: { dialog: { opacity: 0.7, scale: 1.1 }, global: { windowScale: 0.9 } },
      },
      (path) => path,
    );
    const inherited = chatStageRuntimeStyle(defaultChatStageRuntimeConfig, resolved.style) as Record<string, string>;
    expect(inherited["--chat-dialog-runtime-opacity"]).toBe("0.7");
    expect(inherited["--chat-dialog-runtime-scale"]).toBe("1.1");
    expect(inherited["--chat-ui-window-scale"]).toBe("0.9");

    const overridden = chatStageRuntimeStyle(
      { ...defaultChatStageRuntimeConfig, dialogOpacity: 0.8, dialogScale: 0.95, windowScale: 1.15 },
      resolved.style,
    ) as Record<string, string>;
    expect(overridden["--chat-dialog-runtime-opacity"]).toBe("0.8");
    expect(overridden["--chat-dialog-runtime-scale"]).toBe("0.95");
    expect(overridden["--chat-ui-window-scale"]).toBe("1.15");
  });
});
