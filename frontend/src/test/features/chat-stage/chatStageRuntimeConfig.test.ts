import { describe, expect, it } from "vitest";

import {
  chatStageRuntimeConfigVersion,
  defaultChatStageRuntimeConfig,
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
});
