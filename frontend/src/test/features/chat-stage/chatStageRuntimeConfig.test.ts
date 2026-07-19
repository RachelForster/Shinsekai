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
  clearMaterializedChatStageAppearance,
  defaultChatStageRuntimeConfig,
  effectiveChatStageTextStyle,
  materializeChatStageAppearanceTheme,
  normalizeChatStageRuntimeConfig,
  readChatStageRuntimeConfig,
  resetChatStageRuntimeThemeAppearance,
  resetPersistedChatStageRuntimeThemeAppearance,
  runtimeSpriteScale,
  subscribeChatStageRuntimeConfig,
} from "../../../features/chat-stage/runtimeConfig";
import { CHAT_THEME_SCHEMA, resolveChatTheme, type ChatThemeManifest } from "../../../shared/theme/chatTheme";

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
