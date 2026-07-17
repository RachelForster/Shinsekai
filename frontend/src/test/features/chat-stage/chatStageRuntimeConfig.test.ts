import type { CSSProperties } from "react";
import { describe, expect, it } from "vitest";

import {
  chatStageRuntimeStyle,
  chatStageRuntimeConfigVersion,
  defaultChatStageRuntimeConfig,
  effectiveChatStageTextStyle,
  normalizeChatStageRuntimeConfig,
  readChatStageRuntimeConfig,
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
});
