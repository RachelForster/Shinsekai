import type { CSSProperties } from "react";

import type { ChatStageRuntimeConfig } from "./runtimeConfig";

export interface StageViewportState {
  width: number;
  height: number;
  expanded: boolean;
}

export const VN_STAGE_BASE_WIDTH = 1280;
export const VN_STAGE_BASE_HEIGHT = 820;
export const VN_STAGE_MAX_ASPECT = 1.9;
export const VN_SCALE_MAX = 1.85;
export const VN_RESPONSIVE_MIN_WIDTH = 861;

function clamp(value: number, min: number, max: number): number {
  const safeMax = Math.max(min, max);
  return Math.min(safeMax, Math.max(min, value));
}

function parseSinglePx(value: unknown): number | null {
  if (typeof value !== "string") {
    return null;
  }
  const match = /^\s*(-?\d+(?:\.\d+)?)px\s*$/i.exec(value);
  if (!match) {
    return null;
  }
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseResponsivePx(value: unknown, baseHeight = VN_STAGE_BASE_HEIGHT): number | null {
  const single = parseSinglePx(value);
  if (single != null) {
    return single;
  }
  if (typeof value !== "string") {
    return null;
  }
  const clampMatch = /^\s*clamp\(\s*(\d+(?:\.\d+)?)px\s*,\s*(\d+(?:\.\d+)?)svh\s*,\s*(\d+(?:\.\d+)?)px\s*\)\s*$/i.exec(
    value,
  );
  if (!clampMatch) {
    return null;
  }
  const minPx = Number(clampMatch[1]);
  const svhPct = Number(clampMatch[2]);
  const maxPx = Number(clampMatch[3]);
  if (!Number.isFinite(minPx) || !Number.isFinite(svhPct) || !Number.isFinite(maxPx)) {
    return null;
  }
  return clamp((baseHeight * svhPct) / 100, minPx, maxPx);
}

function parseThemeDialogWidthPct(themeStyle: Record<string, unknown>): number {
  const raw = themeStyle["--chat-dialog-width"];
  if (typeof raw !== "string") {
    return 86;
  }
  const trimmed = raw.trim();
  const minMatch = /^min\(\s*(\d+(?:\.\d+)?)vw\s*,/i.exec(trimmed);
  const vwMatch = minMatch ?? /^(\d+(?:\.\d+)?)vw$/i.exec(trimmed);
  if (!vwMatch) {
    return 86;
  }
  const parsed = Number(vwMatch[1]);
  return Number.isFinite(parsed) ? clamp(parsed, 30, 100) : 86;
}

function parseGapSvhPct(raw: unknown): number {
  if (typeof raw !== "string") {
    return 20;
  }
  const match = /(\d+(?:\.\d+)?)svh/i.exec(raw);
  if (!match) {
    return 20;
  }
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) ? clamp(parsed, 1, 60) : 20;
}

export function shouldApplyVnDialogAdaptation(viewport?: StageViewportState | null): boolean {
  if (
    !viewport ||
    !Number.isFinite(viewport.width) ||
    !Number.isFinite(viewport.height) ||
    viewport.width < VN_RESPONSIVE_MIN_WIDTH ||
    viewport.height <= 0
  ) {
    return false;
  }
  return Boolean(viewport.expanded || viewport.width > VN_STAGE_BASE_WIDTH || viewport.height > VN_STAGE_BASE_HEIGHT);
}

export function resolveVnDialogViewportStyle({
  config,
  defaultConfig,
  dialogComposedScale,
  themeStyle,
  viewport,
}: {
  config: ChatStageRuntimeConfig;
  defaultConfig: ChatStageRuntimeConfig;
  dialogComposedScale: number;
  themeStyle: CSSProperties;
  viewport?: StageViewportState | null;
}): Record<string, string> {
  if (!shouldApplyVnDialogAdaptation(viewport) || !viewport) {
    return {};
  }

  const widthRatio = viewport.width / VN_STAGE_BASE_WIDTH;
  const heightRatio = viewport.height / VN_STAGE_BASE_HEIGHT;
  const vnScale = Number(clamp(Math.min(widthRatio, heightRatio), 1, VN_SCALE_MAX).toFixed(4));
  const styleRecord = themeStyle as Record<string, unknown>;
  const result: Record<string, string> = {};

  if (config.dialogWidthPct == null) {
    const widthPct = parseThemeDialogWidthPct(styleRecord);
    const fullBleed = widthPct >= 100;
    const vnCanvasWidth = fullBleed ? viewport.width : Math.min(viewport.width, viewport.height * VN_STAGE_MAX_ASPECT);
    const maxOnScreenWidth = fullBleed ? viewport.width : Math.max(0, viewport.width - 40);
    const targetVisualWidthPx = Math.min(maxOnScreenWidth, Math.round((vnCanvasWidth * widthPct) / 100));
    const scaleDivisor = dialogComposedScale > 1 ? dialogComposedScale : 1;
    const layoutWidthPx = Math.min(targetVisualWidthPx, Math.floor(maxOnScreenWidth / scaleDivisor));
    if (layoutWidthPx > 0) {
      result["--chat-dialog-width"] = `${layoutWidthPx}px`;
      result["--chat-dialog-runtime-width"] = `${layoutWidthPx}px`;
      result["--chat-dialog-max-width"] = `${layoutWidthPx}px`;
    }
  }

  const themeHeightPx = parseSinglePx(styleRecord["--chat-dialog-height"]);
  if (themeHeightPx != null) {
    const scaledHeightPx = Math.round(clamp(themeHeightPx * vnScale, themeHeightPx, viewport.height * 0.34));
    result["--chat-dialog-height"] = `${scaledHeightPx}px`;
    if (typeof styleRecord["--chat-dialog-name-input-gap"] === "string") {
      const vhPct = parseGapSvhPct(styleRecord["--chat-dialog-name-input-gap"]);
      const desiredGapFromVh = Math.round((viewport.height * vhPct) / 100);
      const minGapForDialog = Math.round(scaledHeightPx + 18 * vnScale);
      const scaledGapPx = Math.round(
        clamp(Math.max(desiredGapFromVh, minGapForDialog), 84, Math.max(minGapForDialog, viewport.height * 0.38)),
      );
      result["--chat-dialog-name-input-gap"] = `${scaledGapPx}px`;
    }
  } else {
    const minHeightPx = Math.round(clamp(viewport.height * 0.2, 156, 320));
    const bodyMaxHeightPx = Math.round(clamp(viewport.height * 0.3, 260, 460));
    result["--chat-dialog-min-height"] = `${minHeightPx}px`;
    result["--chat-dialog-body-max-height"] = `${bodyMaxHeightPx}px`;
    result["--chat-dialog-portrait-height"] = `${minHeightPx}px`;
  }
  result["--chat-player-portrait-max-size"] = `${Math.round(clamp(160 * vnScale, 160, 240))}px`;

  const rawPad = styleRecord["--chat-dialog-padding"];
  const rawPadInline = styleRecord["--chat-dialog-padding-inline"];
  if (rawPad == null) {
    const padY = Math.round(clamp(22 * vnScale, 22, 42));
    const padX = Math.round(clamp(30 * vnScale, 30, 56));
    result["--chat-dialog-padding"] = `${padY}px ${padX}px`;
    result["--chat-dialog-padding-inline"] = `${padX}px`;
  } else {
    const basePad = parseSinglePx(rawPad);
    if (basePad != null) {
      result["--chat-dialog-padding"] = `${Math.round(clamp(basePad * vnScale, basePad, 72))}px`;
    }
    const basePadInline = parseSinglePx(rawPadInline);
    if (basePadInline != null) {
      result["--chat-dialog-padding-inline"] = `${Math.round(clamp(basePadInline * vnScale, basePadInline, 168))}px`;
    }
  }

  if (styleRecord["--chat-dialog-border-radius"] == null) {
    result["--chat-dialog-border-radius"] = `${Math.round(clamp(10 * vnScale, 10, 18))}px`;
  }

  result["--chat-name-max-width"] = `min(52vw, ${Math.round(360 * vnScale)}px)`;
  result["--chat-name-min-height"] = `${Math.round(clamp(28 * vnScale, 28, 48))}px`;
  const rawNamePad = styleRecord["--chat-name-padding"];
  if (rawNamePad == null) {
    result["--chat-name-padding"] =
      `${Math.round(clamp(5 * vnScale, 5, 10))}px ${Math.round(clamp(18 * vnScale, 18, 32))}px`;
  } else {
    const baseNamePad = parseSinglePx(rawNamePad);
    if (baseNamePad != null) {
      result["--chat-name-padding"] = `${Math.round(clamp(baseNamePad * vnScale, baseNamePad, 20))}px`;
    }
  }

  if (config.dialogText.fontSize === defaultConfig.dialogText.fontSize) {
    const themeDialogFontPx = parseSinglePx(styleRecord["--chat-dialog-text-theme-font-size"]);
    if (themeDialogFontPx != null) {
      result["--chat-dialog-text-runtime-font-size"] =
        `${Math.round(clamp(themeDialogFontPx * vnScale, themeDialogFontPx, 52))}px`;
    } else {
      result["--chat-dialog-text-runtime-font-size"] = `${Math.round(clamp(18 * vnScale, 18, 34))}px`;
    }
  }

  if (config.nameText.fontSize === defaultConfig.nameText.fontSize) {
    const themeNameFontPx = parseSinglePx(styleRecord["--chat-name-theme-font-size"]);
    if (themeNameFontPx != null) {
      result["--chat-name-runtime-font-size"] =
        `${Math.round(clamp(themeNameFontPx * vnScale, themeNameFontPx, 42))}px`;
    } else {
      result["--chat-name-runtime-font-size"] = `${Math.round(clamp(16 * vnScale, 16, 30))}px`;
    }
  }

  const themeOptionFontPx = parseResponsivePx(styleRecord["--chat-option-font-size"]);
  const optionFontPx =
    themeOptionFontPx != null
      ? Math.round(clamp(themeOptionFontPx * vnScale, themeOptionFontPx, 42))
      : Math.round(clamp(17 * vnScale, 17, 32));
  result["--chat-option-font-size"] = `${optionFontPx}px`;

  const themeOptionMinHeightPx = parseResponsivePx(styleRecord["--chat-option-min-height"]);
  const baseOptionMinHeightPx = themeOptionMinHeightPx ?? 48;
  const maxOptionMinHeightPx = Math.max(
    Math.round(baseOptionMinHeightPx),
    Math.min(112, Math.round(viewport.height * 0.11)),
  );
  const scaledOptionMinHeightPx = Math.round(
    clamp(
      Math.max(baseOptionMinHeightPx * vnScale, Math.round(optionFontPx * 2.5)),
      baseOptionMinHeightPx,
      maxOptionMinHeightPx,
    ),
  );
  result["--chat-option-min-height"] = `${scaledOptionMinHeightPx}px`;

  if (styleRecord["--chat-option-icon-opacity"] === "1") {
    const baseOptionIconPx = parseResponsivePx(styleRecord["--chat-option-icon-size"]) ?? 31;
    const scaledIconPx = Math.round(clamp(baseOptionIconPx * vnScale, 28, 48));
    const padY = Math.round(clamp(8 * vnScale, 8, 16));
    const padRight = Math.round(clamp(18 * vnScale, 18, 34));
    const padLeft = 14 + scaledIconPx + Math.round(clamp(12 * vnScale, 12, 22));
    result["--chat-option-icon-size"] = `${scaledIconPx}px`;
    result["--chat-option-padding"] = `${padY}px ${padRight}px ${padY}px ${padLeft}px`;
  } else {
    const rawOptionPad = styleRecord["--chat-option-padding"];
    if (rawOptionPad == null) {
      const padY = Math.round(clamp(12 * vnScale, 12, 22));
      const padX = Math.round(clamp(22 * vnScale, 22, 40));
      result["--chat-option-padding"] = `${padY}px ${padX}px`;
    } else {
      const baseOptionPad = parseSinglePx(rawOptionPad);
      if (baseOptionPad != null) {
        result["--chat-option-padding"] = `${Math.round(clamp(baseOptionPad * vnScale, baseOptionPad, 48))}px`;
      }
    }
  }

  const baseOptionGapPx = parseSinglePx(styleRecord["--chat-options-gap"]) ?? 10;
  if (baseOptionGapPx > 0) {
    result["--chat-options-gap"] = `${Math.round(clamp(baseOptionGapPx * vnScale, baseOptionGapPx, 28))}px`;
  }

  return result;
}
