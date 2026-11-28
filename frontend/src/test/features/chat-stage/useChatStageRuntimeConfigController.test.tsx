import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  emitDesktopConfig: vi.fn().mockResolvedValue(undefined),
  listenDesktopConfig: vi.fn((_listener: (config: unknown) => void) => Promise.resolve(() => undefined)),
  optionalChatTheme: null as {
    resolved?: { typewriter: { cps: number } };
    style: Record<string, string>;
  } | null,
}));

vi.mock("../../../shared/desktop/desktopApi", () => ({
  emitDesktopChatStageRuntimeConfigChange: (config: unknown) => mocks.emitDesktopConfig(config),
  onDesktopChatStageRuntimeConfigChange: (listener: (config: unknown) => void) => mocks.listenDesktopConfig(listener),
}));

vi.mock("../../../features/chat-stage/theme/ChatThemeProvider", () => ({
  useOptionalChatTheme: () => mocks.optionalChatTheme,
}));

import { useChatStageRuntimeConfigController } from "../../../features/chat-stage/controllers/useChatStageRuntimeConfigController";
import { defaultChatStageRuntimeConfig } from "../../../features/chat-stage/runtimeConfig";

describe("useChatStageRuntimeConfigController", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mocks.emitDesktopConfig.mockClear();
    mocks.listenDesktopConfig.mockClear();
    mocks.optionalChatTheme = null;
  });

  it("derives theme tokens and clamps volume, shortcut, sprite framing, and text styles", async () => {
    mocks.optionalChatTheme = {
      resolved: { typewriter: { cps: 42 } },
      style: {
        "--chat-dialog-toolbar-placement": "input",
        "--chat-dialog-toolbar-reveal": "hover",
        "--chat-input-layout": "pill",
        "--chat-theme-color": "#336699",
      },
    };
    const sendCommand = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useChatStageRuntimeConfigController({ sendCommand }));
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.dialogToolbarPlacement).toBe("input");
    expect(result.current.dialogToolbarDetached).toBe(true);
    expect(result.current.dialogToolbarReveal).toBe("hover");
    expect(result.current.inputLayout).toBe("pill");
    expect(result.current.typewriterCps).toBe(42);

    act(() => {
      result.current.updateBgmVolume(2.5);
      result.current.updateEffectVolume(-0.4);
      result.current.updateMiniInputShortcut("  Ctrl+Shift+M  ");
      result.current.updateTextSpeed(88);
      result.current.updateAlwaysOnTop(false);
      result.current.updateImmersiveMode(true);
      result.current.updateAutoHideTopTools(false);
      result.current.updateAutoHideInput(false);
      result.current.updateDialogOpacity(0.5);
      result.current.updateDialogFill({ gradient: true, opacity: 0.7 });
      result.current.updateDialogScale(1.1);
      result.current.updateDialogWidthPct(72);
      result.current.updateSpriteOffsetX(24);
      result.current.updateSpriteOffsetY(-16);
      result.current.updateSpriteScale("character:mio", 1.25);
      result.current.updateSpriteFraming("character:mio", { heightRatio: 0.5, verticalPosition: 2 });
      result.current.updateWindowScale(1.15);
      result.current.updateConfigThemeColor("#abcdef");
      result.current.updateConfigUseMainThemeColor(false);
      result.current.updateTextStyle("dialogText", { direction: "rtl", fontSize: 20 });
    });

    expect(result.current.runtimeConfig.bgmVolume).toBe(1);
    expect(result.current.runtimeConfig.effectVolume).toBe(0);
    expect(result.current.runtimeConfig.miniInputShortcut).toBe("Ctrl+Shift+M");
    expect(result.current.typewriterCps).toBe(88);
    expect(result.current.dialogTextDirection).toBe("rtl");
    expect(result.current.runtimeConfig.dialogFill.gradient).toBe(true);
    expect(result.current.runtimeConfig.dialogFill.opacity).toBe(0.7);
    expect(result.current.runtimeConfig.spriteScales["character:mio"]).toBe(1.25);
    expect(result.current.runtimeConfig.spriteFramings["character:mio"]).toEqual({
      heightRatio: 0.5,
      verticalPosition: 1,
    });
    expect(result.current.runtimeConfig.configThemeColor).toBe("#abcdef");
    expect(result.current.runtimeConfig.configUseMainThemeColor).toBe(false);

    act(() => {
      result.current.resetThemeAppearance();
    });

    expect(result.current.runtimeConfig.dialogFill).toEqual(defaultChatStageRuntimeConfig.dialogFill);
    expect(result.current.runtimeConfig.dialogText.fontSize).toBe(defaultChatStageRuntimeConfig.dialogText.fontSize);
    expect(result.current.runtimeConfig.dialogText.direction).toBe("rtl");
    expect(result.current.runtimeConfig.dialogOpacity).toBe(0.5);
    expect(result.current.runtimeConfig.configThemeColor).toBe("#336699");
    expect(result.current.runtimeConfig.spriteScales["character:mio"]).toBe(1.25);
  });

  it("toggles auto mode and pauses ASR when enabling longPressTalk", async () => {
    const sendCommand = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useChatStageRuntimeConfigController({ sendCommand }));
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.runtimeConfig.auto).toBe(false);
    act(() => result.current.toggleAuto());
    expect(result.current.runtimeConfig.auto).toBe(true);
    act(() => result.current.setAuto(false));
    expect(result.current.runtimeConfig.auto).toBe(false);

    act(() => result.current.updateLongPressTalk(false));
    expect(sendCommand).not.toHaveBeenCalled();

    act(() => result.current.updateLongPressTalk(true));
    expect(result.current.runtimeConfig.longPressTalk).toBe(true);
    expect(sendCommand).toHaveBeenCalledWith({ type: "pause-asr" });
  });
});
