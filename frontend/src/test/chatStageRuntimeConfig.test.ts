import { describe, expect, it } from "vitest";

import {
  chatStageRuntimeConfigVersion,
  defaultChatStageRuntimeConfig,
  normalizeChatStageRuntimeConfig,
} from "../features/chat-stage/runtimeConfig";

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
          configThemeColor: "#123abc",
          configUseMainThemeColor: false,
          dialogScale: 1.1,
        },
        version: chatStageRuntimeConfigVersion,
      }),
    ).toEqual({
      ...defaultChatStageRuntimeConfig,
      configThemeColor: "#123abc",
      configUseMainThemeColor: false,
      dialogScale: 1.1,
    });
  });
});
