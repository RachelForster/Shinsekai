import type { CSSProperties } from "react";
import { describe, expect, it } from "vitest";

import {
  chatStageRuntimeStyle,
  chatStageRuntimeConfigVersion,
  defaultChatStageRuntimeConfig,
  effectiveChatStageTextStyle,
  normalizeChatStageRuntimeConfig,
  readChatStageRuntimeConfig,
  runtimeSpriteScale,
} from "../../../features/chat-stage/runtimeConfig";

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

  it("migrates legacy sprite-id scale keys to stable character keys", () => {
    const config = normalizeChatStageRuntimeConfig({
      config: {
        spriteScales: {
          "Mio-1": 0.8,
          "Mio-0": 1.35,
        },
      },
      version: 3,
    });

    expect(config.spriteScales).toEqual({ "Mio-0": 1.35, "Mio-1": 0.8, Mio: 1.35 });
    expect(
      runtimeSpriteScale(config, { characterName: "Mio", id: "Mio-0", label: "Mio", path: "asset://mio.png" }, 0),
    ).toBe(1.35);
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

  it("combines runtime opacity with the theme background layer without dimming text", () => {
    const config = { ...defaultChatStageRuntimeConfig, dialogOpacity: 0.5 };
    const runtimeStyle = chatStageRuntimeStyle(config, {
      "--chat-dialog-background-opacity": "0.4",
      "--chat-dialog-text-opacity": "0.95",
    } as CSSProperties) as unknown as Record<string, unknown>;

    expect(runtimeStyle["--chat-dialog-runtime-opacity"]).toBe("0.2");
    expect(runtimeStyle["--chat-dialog-text-opacity"]).toBe("0.95");
  });
});
