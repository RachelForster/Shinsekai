import { useCallback, useEffect, useMemo, useState } from "react";

import { normalizeVisualFraming, type VisualFraming } from "../../../modules/character-visual";
import type { ChatCommand } from "../../../shared/platform/types";
import { normalizeThemeColor } from "../../../shared/theme/appTheme";
import { DEFAULT_TYPEWRITER_CPS } from "../../../shared/theme/chatTheme";
import type { ChatConfigDialog } from "../components/ChatConfigDialog";
import { useMainThemeColor } from "../hooks/useMainThemeColor";
import {
  defaultChatStageRuntimeConfig,
  effectiveChatStageTextStyle,
  readChatStageRuntimeConfig,
  resetChatStageRuntimeThemeAppearance,
  subscribeChatStageRuntimeConfig,
  writeChatStageRuntimeConfig,
} from "../runtimeConfig";
import { useOptionalChatTheme } from "../theme/ChatThemeProvider";

export interface UseChatStageRuntimeConfigControllerOptions {
  sendCommand: (command: ChatCommand) => Promise<void>;
}

export function useChatStageRuntimeConfigController({ sendCommand }: UseChatStageRuntimeConfigControllerOptions) {
  const [runtimeConfig, setRuntimeConfig] = useState(readChatStageRuntimeConfig);
  const mainThemeColor = useMainThemeColor();
  const theme = useOptionalChatTheme();
  const themeStyle = theme?.style ?? {};

  useEffect(() => {
    writeChatStageRuntimeConfig(runtimeConfig);
  }, [runtimeConfig]);

  useEffect(() => subscribeChatStageRuntimeConfig(setRuntimeConfig), []);

  const effectiveDialogText = useMemo(
    () =>
      effectiveChatStageTextStyle(
        runtimeConfig.dialogText,
        defaultChatStageRuntimeConfig.dialogText,
        themeStyle,
        "dialogText",
      ),
    [runtimeConfig.dialogText, themeStyle],
  );
  const effectiveNameText = useMemo(
    () =>
      effectiveChatStageTextStyle(
        runtimeConfig.nameText,
        defaultChatStageRuntimeConfig.nameText,
        themeStyle,
        "nameText",
      ),
    [runtimeConfig.nameText, themeStyle],
  );

  const dialogToolbarPlacement =
    typeof themeStyle["--chat-dialog-toolbar-placement"] === "string"
      ? themeStyle["--chat-dialog-toolbar-placement"]
      : "";
  const dialogToolbarDetached = dialogToolbarPlacement === "input" || dialogToolbarPlacement === "dialog-top";
  const dialogToolbarReveal: "hover" | "always" =
    themeStyle["--chat-dialog-toolbar-reveal"] === "hover" ? "hover" : "always";
  const inputLayout: "pill" | "default" = themeStyle["--chat-input-layout"] === "pill" ? "pill" : "default";
  const dialogTextDirection = effectiveDialogText.direction ?? "ltr";
  const typewriterCps = runtimeConfig.typewriterCps ?? theme?.resolved?.typewriter.cps ?? DEFAULT_TYPEWRITER_CPS;

  const setAuto = useCallback((auto: boolean) => {
    setRuntimeConfig((current) => ({ ...current, auto }));
  }, []);

  const toggleAuto = useCallback(() => {
    setRuntimeConfig((current) => ({ ...current, auto: !current.auto }));
  }, []);

  const updateTextSpeed = (typewriterCpsValue: number) => {
    setRuntimeConfig((current) => ({ ...current, typewriterCps: typewriterCpsValue }));
  };

  const updateAlwaysOnTop = (alwaysOnTop: boolean) => {
    setRuntimeConfig((current) => ({ ...current, alwaysOnTop }));
  };

  const updateBgmVolume = (bgmVolume: number) => {
    setRuntimeConfig((current) => ({ ...current, bgmVolume: Math.min(1, Math.max(0, bgmVolume)) }));
  };

  const updateEffectVolume = (effectVolume: number) => {
    setRuntimeConfig((current) => ({ ...current, effectVolume: Math.min(1, Math.max(0, effectVolume)) }));
  };

  const updateLongPressTalk = (longPressTalk: boolean) => {
    setRuntimeConfig((current) => ({ ...current, longPressTalk }));
    if (longPressTalk) {
      void sendCommand({ type: "pause-asr" });
    }
  };

  const updateImmersiveMode = (immersiveMode: boolean) => {
    setRuntimeConfig((current) => ({ ...current, immersiveMode }));
  };

  const updateAutoHideTopTools = (autoHideTopTools: boolean) => {
    setRuntimeConfig((current) => ({ ...current, autoHideTopTools }));
  };

  const updateAutoHideInput = (autoHideInput: boolean) => {
    setRuntimeConfig((current) => ({ ...current, autoHideInput }));
  };

  const updateDialogOpacity = (dialogOpacity: number) => {
    setRuntimeConfig((current) => ({ ...current, dialogOpacity }));
  };

  const updateDialogFill: Parameters<typeof ChatConfigDialog>[0]["onDialogFillChange"] = (patch) => {
    setRuntimeConfig((current) => ({ ...current, dialogFill: { ...current.dialogFill, ...patch } }));
  };

  const updateDialogScale = (dialogScale: number) => {
    setRuntimeConfig((current) => ({ ...current, dialogScale }));
  };

  const updateDialogWidthPct = (dialogWidthPct: number | null) => {
    setRuntimeConfig((current) => ({ ...current, dialogWidthPct }));
  };

  const updateSpriteOffsetX = (spriteOffsetX: number) => {
    setRuntimeConfig((current) => ({ ...current, spriteOffsetX }));
  };

  const updateSpriteOffsetY = (spriteOffsetY: number) => {
    setRuntimeConfig((current) => ({ ...current, spriteOffsetY }));
  };

  const updateSpriteScale = (spriteKey: string, spriteScale: number) => {
    setRuntimeConfig((current) => ({
      ...current,
      spriteScales: {
        ...current.spriteScales,
        [spriteKey]: spriteScale,
      },
    }));
  };

  const updateWindowScale = (windowScale: number) => {
    setRuntimeConfig((current) => ({ ...current, windowScale }));
  };

  const updateSpriteFraming = (spriteKey: string, framing: VisualFraming) => {
    setRuntimeConfig((current) => ({
      ...current,
      spriteFramings: { ...current.spriteFramings, [spriteKey]: normalizeVisualFraming(framing) },
    }));
  };

  const updateConfigThemeColor = (configThemeColor: string) => {
    setRuntimeConfig((current) => ({ ...current, configThemeColor: normalizeThemeColor(configThemeColor) }));
  };

  const updateConfigUseMainThemeColor = (configUseMainThemeColor: boolean) => {
    setRuntimeConfig((current) => ({ ...current, configUseMainThemeColor }));
  };

  const updateMiniInputShortcut = (miniInputShortcut: string) => {
    setRuntimeConfig((current) => ({
      ...current,
      miniInputShortcut: miniInputShortcut.trim(),
    }));
  };

  const resetThemeAppearance = () => {
    const themeColor = (themeStyle as Record<string, unknown>)["--chat-theme-color"];
    setRuntimeConfig((current) =>
      resetChatStageRuntimeThemeAppearance(current, typeof themeColor === "string" ? themeColor : mainThemeColor),
    );
  };

  const updateTextStyle: Parameters<typeof ChatConfigDialog>[0]["onTextStyleChange"] = (target, patch) => {
    setRuntimeConfig((current) => ({
      ...current,
      [target]: {
        ...current[target],
        ...patch,
      },
    }));
  };

  return {
    dialogTextDirection,
    dialogToolbarDetached,
    dialogToolbarPlacement,
    dialogToolbarReveal,
    effectiveDialogText,
    effectiveNameText,
    inputLayout,
    mainThemeColor,
    resetThemeAppearance,
    runtimeConfig,
    setAuto,
    setRuntimeConfig,
    themeStyle,
    toggleAuto,
    typewriterCps,
    updateAlwaysOnTop,
    updateAutoHideInput,
    updateAutoHideTopTools,
    updateBgmVolume,
    updateConfigThemeColor,
    updateConfigUseMainThemeColor,
    updateDialogFill,
    updateDialogOpacity,
    updateDialogScale,
    updateDialogWidthPct,
    updateEffectVolume,
    updateImmersiveMode,
    updateLongPressTalk,
    updateMiniInputShortcut,
    updateSpriteFraming,
    updateSpriteOffsetX,
    updateSpriteOffsetY,
    updateSpriteScale,
    updateTextSpeed,
    updateTextStyle,
    updateWindowScale,
  };
}
