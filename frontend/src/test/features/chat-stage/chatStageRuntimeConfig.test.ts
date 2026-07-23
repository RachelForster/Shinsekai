import type { CSSProperties } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const desktopEventMocks = vi.hoisted(() => ({
  emit: vi.fn(),
  listen: vi.fn(),
}));

vi.mock("../../../shared/desktop/desktopApi", () => ({
  emitDesktopChatStageRuntimeConfigChange: (config: unknown) => desktopEventMocks.emit(config),
  onDesktopChatStageRuntimeConfigChange: (listener: (config: unknown) => void) => desktopEventMocks.listen(listener),
}));

import {
  chatStageRuntimeStyle,
  chatStageRuntimeConfigVersion,
  defaultChatStageRuntimeConfig,
  effectiveChatStageTextStyle,
  normalizeChatStageRuntimeConfig,
  readChatStageRuntimeConfig,
  resetChatStageRuntimeThemeAppearance,
  resetPersistedChatStageRuntimeThemeAppearance,
  runtimeSpriteScale,
  subscribeChatStageRuntimeConfig,
} from "../../../features/chat-stage/runtimeConfig";

describe("chat stage runtime config", () => {
  beforeEach(() => {
    desktopEventMocks.emit.mockReset();
    desktopEventMocks.emit.mockResolvedValue(undefined);
    desktopEventMocks.listen.mockReset();
    desktopEventMocks.listen.mockResolvedValue(() => undefined);
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
  });

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

  it("restores theme-owned appearance without clearing behavior and layout preferences", () => {
    const customized = {
      ...defaultChatStageRuntimeConfig,
      configThemeColor: "#ff3355",
      configUseMainThemeColor: true,
      dialogFill: {
        color: "#112233",
        color2: "#445566",
        gradient: true,
        gradientDirection: "to-top" as const,
        gradientMode: "dual" as const,
        opacity: 0.7,
      },
      dialogOpacity: 0.55,
      dialogText: {
        align: "right" as const,
        alignOverride: true,
        bold: true,
        boldOverride: true,
        color: "#ddeeff",
        direction: "rtl" as const,
        fontFamily: "Verdana",
        fontSize: 24,
      },
      nameText: {
        bold: false,
        boldOverride: true,
        color: "#ffeeaa",
        fontFamily: "Georgia",
        fontSize: 20,
      },
      spriteScales: { Mio: 1.4 },
      typewriterCps: 96,
      windowScale: 1.1,
    };

    expect(resetChatStageRuntimeThemeAppearance(customized, "rgb(34, 170, 136)")).toEqual({
      ...customized,
      configThemeColor: "#22aa88",
      configUseMainThemeColor: false,
      dialogFill: defaultChatStageRuntimeConfig.dialogFill,
      dialogText: {
        ...defaultChatStageRuntimeConfig.dialogText,
        direction: "rtl",
      },
      nameText: defaultChatStageRuntimeConfig.nameText,
    });
  });

  it("persists and broadcasts restored theme appearance in the current window and across webviews", () => {
    window.localStorage.setItem(
      "shinsekai-chat-stage-runtime-config",
      JSON.stringify({
        config: {
          configThemeColor: "#ff3355",
          dialogOpacity: 0.6,
          dialogText: { color: "#112233" },
        },
        version: chatStageRuntimeConfigVersion,
      }),
    );
    const listener = vi.fn();
    const unsubscribe = subscribeChatStageRuntimeConfig(listener);

    const next = resetPersistedChatStageRuntimeThemeAppearance("#336699");

    expect(listener).toHaveBeenCalledWith(next);
    expect(desktopEventMocks.emit).toHaveBeenCalledWith(next);
    expect(next.configThemeColor).toBe("#336699");
    expect(next.dialogOpacity).toBe(0.6);
    expect(next.dialogText).toEqual(defaultChatStageRuntimeConfig.dialogText);
    expect(JSON.parse(window.localStorage.getItem("shinsekai-chat-stage-runtime-config") || "{}")).toMatchObject({
      config: {
        configThemeColor: "#336699",
        configUseMainThemeColor: false,
        dialogOpacity: 0.6,
      },
      version: chatStageRuntimeConfigVersion,
    });

    unsubscribe();
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
  });

  it("applies runtime config received from another webview", async () => {
    const listener = vi.fn();
    let desktopListener: (config: unknown) => void = () => {
      throw new Error("desktop listener was not registered");
    };
    const unlisten = vi.fn();
    desktopEventMocks.listen.mockImplementation(async (callback: (config: unknown) => void) => {
      desktopListener = callback;
      return unlisten;
    });
    const unsubscribe = subscribeChatStageRuntimeConfig(listener);
    await vi.waitFor(() => expect(desktopEventMocks.listen).toHaveBeenCalledTimes(1));

    desktopListener({
      configThemeColor: "#4a6cff",
      dialogOpacity: 0.7,
      dialogText: { color: "#abcdef" },
    });

    expect(listener).toHaveBeenCalledWith({
      ...defaultChatStageRuntimeConfig,
      configThemeColor: "#4a6cff",
      dialogOpacity: 0.7,
      dialogText: {
        ...defaultChatStageRuntimeConfig.dialogText,
        color: "#abcdef",
      },
    });

    unsubscribe();
    expect(unlisten).toHaveBeenCalledTimes(1);
  });

  it("re-reads persisted config after the desktop listener is ready", async () => {
    let finishDesktopSubscription: ((unlisten: () => void) => void) | undefined;
    desktopEventMocks.listen.mockImplementation(
      () =>
        new Promise<() => void>((resolve) => {
          finishDesktopSubscription = resolve;
        }),
    );
    const listener = vi.fn();
    const unsubscribe = subscribeChatStageRuntimeConfig(listener);
    const next = {
      ...defaultChatStageRuntimeConfig,
      configThemeColor: "#55aacc",
      dialogOpacity: 0.65,
    };
    window.localStorage.setItem(
      "shinsekai-chat-stage-runtime-config",
      JSON.stringify({
        config: next,
        version: chatStageRuntimeConfigVersion,
      }),
    );

    finishDesktopSubscription?.(() => undefined);

    await vi.waitFor(() => expect(listener).toHaveBeenCalledWith(next));
    unsubscribe();
  });

  it("reloads runtime config when another browser context changes local storage", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeChatStageRuntimeConfig(listener);
    const next = {
      ...defaultChatStageRuntimeConfig,
      configThemeColor: "#aa44cc",
      dialogOpacity: 0.8,
    };

    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "shinsekai-chat-stage-runtime-config",
        newValue: JSON.stringify({
          config: next,
          version: chatStageRuntimeConfigVersion,
        }),
      }),
    );

    expect(listener).toHaveBeenCalledWith(next);
    unsubscribe();
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
});
