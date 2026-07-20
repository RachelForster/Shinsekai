import type { CSSProperties } from "react";

import type { ChatStageSprite } from "./chatState";
import { DEFAULT_TYPEWRITER_CPS } from "../../shared/theme/chatTheme";
import { DEFAULT_THEME_COLOR, normalizeThemeColor } from "../../shared/theme/appTheme";

export const clickThroughGuardIntervalMs = 32;
const runtimeConfigStorageKey = "shinsekai-chat-stage-runtime-config";
export const chatStageRuntimeConfigVersion = 3;
export const runtimeTextSpeedMin = 1;
export const runtimeTextSpeedMax = 200;
export const runtimeDialogOpacityMin = 0.35;
export const runtimeDialogOpacityMax = 1;
export const runtimeDialogOpacityStep = 0.05;
export const runtimeDialogFillOpacityMin = 0;
export const runtimeDialogFillOpacityMax = 1;
export const runtimeDialogFillOpacityStep = 0.05;
export const runtimeDialogScaleMin = 0.8;
export const runtimeDialogScaleMax = 1.2;
export const runtimeDialogScaleStep = 0.05;
export const runtimeSpriteDefaultScaleKey = "__default__";
export const runtimeSpriteScaleMin = 0;
export const runtimeSpriteScaleMax = 3;
export const runtimeSpriteScaleStep = 0.05;
export const runtimeSpriteOffsetMin = -240;
export const runtimeSpriteOffsetMax = 240;
export const runtimeSpriteOffsetStep = 4;
export const runtimeWindowScaleMin = 0.8;
export const runtimeWindowScaleMax = 1.2;
export const runtimeWindowScaleStep = 0.05;
export const runtimeNameFontSizeMin = 11;
export const runtimeNameFontSizeMax = 56;
export const runtimeDialogFontSizeMin = 12;
export const runtimeDialogFontSizeMax = 64;
export const chatStageTextDirections = ["ltr", "rtl"] as const;
export const chatStageTextAlignments = ["left", "center", "right", "justify"] as const;
export const chatStageDialogFillGradientModes = ["single", "dual"] as const;
export const chatStageDialogFillGradientDirections = ["to-bottom", "to-top"] as const;

export type ChatStageTextDirection = (typeof chatStageTextDirections)[number];
export type ChatStageTextAlign = (typeof chatStageTextAlignments)[number];
export type ChatStageDialogFillGradientMode = (typeof chatStageDialogFillGradientModes)[number];
export type ChatStageDialogFillGradientDirection = (typeof chatStageDialogFillGradientDirections)[number];

export interface ChatStageTextStyleConfig {
  color: string;
  fontFamily: string;
  fontSize: number;
  bold: boolean;
  boldOverride?: boolean;
  align?: ChatStageTextAlign;
  alignOverride?: boolean;
  direction?: ChatStageTextDirection;
}

export interface ChatStageDialogFillConfig {
  color: string;
  color2: string;
  gradient: boolean;
  gradientDirection: ChatStageDialogFillGradientDirection;
  gradientMode: ChatStageDialogFillGradientMode;
  opacity: number;
}

export interface ChatStageRuntimeConfig {
  auto: boolean;
  autoHideInput: boolean;
  autoHideTopTools: boolean;
  configThemeColor: string;
  configUseMainThemeColor: boolean;
  dialogFill: ChatStageDialogFillConfig;
  dialogOpacity: number;
  dialogScale: number;
  immersiveMode: boolean;
  longPressTalk: boolean;
  spriteScales: Record<string, number>;
  spriteOffsetX: number;
  spriteOffsetY: number;
  typewriterCps: number | null;
  windowScale: number;
  nameText: ChatStageTextStyleConfig;
  dialogText: ChatStageTextStyleConfig;
}

export type ChatStageTextStyleTarget = "nameText" | "dialogText";
export type ChatStageTextStylePatch = Partial<ChatStageTextStyleConfig>;
export type ChatStageDialogFillPatch = Partial<ChatStageDialogFillConfig>;

interface ChatStageRuntimeConfigStorageEnvelope {
  config: Partial<ChatStageRuntimeConfig>;
  version: number;
}

export const defaultChatStageRuntimeConfig: ChatStageRuntimeConfig = {
  auto: false,
  autoHideInput: true,
  autoHideTopTools: true,
  configThemeColor: DEFAULT_THEME_COLOR,
  configUseMainThemeColor: true,
  dialogText: {
    align: "center",
    bold: false,
    color: "#f7f1f0",
    direction: "ltr",
    fontFamily: "",
    fontSize: 17,
  },
  dialogFill: {
    color: "#16120f",
    color2: "#16120f",
    gradient: false,
    gradientDirection: "to-bottom",
    gradientMode: "single",
    opacity: 0.86,
  },
  dialogOpacity: 1,
  dialogScale: 1,
  immersiveMode: false,
  longPressTalk: false,
  nameText: {
    bold: true,
    color: "#fff6f4",
    fontFamily: "",
    fontSize: 15,
  },
  spriteScales: {},
  spriteOffsetX: 0,
  spriteOffsetY: 0,
  typewriterCps: null,
  windowScale: 1,
};

export function clampRuntimeNumber(value: unknown, fallback: number, min: number, max: number) {
  const next = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(next)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, next));
}

function readRuntimeSpriteScales(parsed: Partial<ChatStageRuntimeConfig> & { spriteScale?: unknown }) {
  const spriteScales: Record<string, number> = {};
  const rawSpriteScales = parsed.spriteScales;
  if (rawSpriteScales && typeof rawSpriteScales === "object" && !Array.isArray(rawSpriteScales)) {
    for (const [key, value] of Object.entries(rawSpriteScales)) {
      const trimmedKey = key.trim();
      if (!trimmedKey) {
        continue;
      }
      spriteScales[trimmedKey] = clampRuntimeNumber(value, 1, runtimeSpriteScaleMin, runtimeSpriteScaleMax);
    }
  }
  if (!Object.keys(spriteScales).length && parsed.spriteScale != null) {
    spriteScales[runtimeSpriteDefaultScaleKey] = clampRuntimeNumber(
      parsed.spriteScale,
      1,
      runtimeSpriteScaleMin,
      runtimeSpriteScaleMax,
    );
  }
  return spriteScales;
}

function sanitizeRuntimeColor(value: unknown, fallback: string) {
  if (typeof value !== "string") {
    return fallback;
  }
  const trimmed = value.trim();
  return /^#[\da-f]{6}$/i.test(trimmed) ? trimmed : fallback;
}

function sanitizeRuntimeFontFamily(value: unknown) {
  return typeof value === "string" ? value.trim().slice(0, 120) : "";
}

function sanitizeRuntimeTextAlign(value: unknown, fallback: ChatStageTextAlign): ChatStageTextAlign {
  return typeof value === "string" && chatStageTextAlignments.includes(value as ChatStageTextAlign)
    ? (value as ChatStageTextAlign)
    : fallback;
}

function sanitizeRuntimeTextDirection(value: unknown, fallback: ChatStageTextDirection): ChatStageTextDirection {
  return typeof value === "string" && chatStageTextDirections.includes(value as ChatStageTextDirection)
    ? (value as ChatStageTextDirection)
    : fallback;
}

function sanitizeRuntimeDialogFillGradientMode(
  value: unknown,
  fallback: ChatStageDialogFillGradientMode,
): ChatStageDialogFillGradientMode {
  return typeof value === "string" &&
    chatStageDialogFillGradientModes.includes(value as ChatStageDialogFillGradientMode)
    ? (value as ChatStageDialogFillGradientMode)
    : fallback;
}

function sanitizeRuntimeDialogFillGradientDirection(
  value: unknown,
  fallback: ChatStageDialogFillGradientDirection,
): ChatStageDialogFillGradientDirection {
  return typeof value === "string" &&
    chatStageDialogFillGradientDirections.includes(value as ChatStageDialogFillGradientDirection)
    ? (value as ChatStageDialogFillGradientDirection)
    : fallback;
}

function readRuntimeDialogFill(parsed: Partial<ChatStageDialogFillConfig> | undefined): ChatStageDialogFillConfig {
  const fallback = defaultChatStageRuntimeConfig.dialogFill;
  return {
    color: sanitizeRuntimeColor(parsed?.color, fallback.color),
    color2: sanitizeRuntimeColor(parsed?.color2, fallback.color2),
    gradient: typeof parsed?.gradient === "boolean" ? parsed.gradient : fallback.gradient,
    gradientDirection: sanitizeRuntimeDialogFillGradientDirection(
      parsed?.gradientDirection,
      fallback.gradientDirection,
    ),
    gradientMode: sanitizeRuntimeDialogFillGradientMode(parsed?.gradientMode, fallback.gradientMode),
    opacity: clampRuntimeNumber(
      parsed?.opacity,
      fallback.opacity,
      runtimeDialogFillOpacityMin,
      runtimeDialogFillOpacityMax,
    ),
  };
}

function readRuntimeTextStyle(
  parsed: Partial<ChatStageTextStyleConfig> | undefined,
  fallback: ChatStageTextStyleConfig,
  min: number,
  max: number,
) {
  const next: ChatStageTextStyleConfig = {
    alignOverride: typeof parsed?.alignOverride === "boolean" ? parsed.alignOverride : undefined,
    bold: typeof parsed?.bold === "boolean" ? parsed.bold : fallback.bold,
    boldOverride: typeof parsed?.boldOverride === "boolean" ? parsed.boldOverride : undefined,
    color: sanitizeRuntimeColor(parsed?.color, fallback.color),
    fontFamily: sanitizeRuntimeFontFamily(parsed?.fontFamily) || fallback.fontFamily,
    fontSize: Math.round(clampRuntimeNumber(parsed?.fontSize, fallback.fontSize, min, max)),
  };
  if (fallback.align) {
    next.align = sanitizeRuntimeTextAlign(parsed?.align, fallback.align);
  }
  if (fallback.direction) {
    next.direction = sanitizeRuntimeTextDirection(parsed?.direction, fallback.direction);
  }
  return next;
}

function isRuntimeRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function unwrapRuntimeConfigStoragePayload(value: unknown): Partial<ChatStageRuntimeConfig> {
  if (!isRuntimeRecord(value)) {
    return {};
  }
  if (typeof value.version === "number" && isRuntimeRecord(value.config)) {
    return value.config as Partial<ChatStageRuntimeConfig>;
  }
  return value as Partial<ChatStageRuntimeConfig>;
}

export function normalizeChatStageRuntimeConfig(value: unknown): ChatStageRuntimeConfig {
  const parsed = unwrapRuntimeConfigStoragePayload(value);
  return {
    auto: typeof parsed.auto === "boolean" ? parsed.auto : defaultChatStageRuntimeConfig.auto,
    autoHideInput:
      typeof parsed.autoHideInput === "boolean" ? parsed.autoHideInput : defaultChatStageRuntimeConfig.autoHideInput,
    autoHideTopTools:
      typeof parsed.autoHideTopTools === "boolean"
        ? parsed.autoHideTopTools
        : defaultChatStageRuntimeConfig.autoHideTopTools,
    configThemeColor: sanitizeRuntimeColor(parsed.configThemeColor, defaultChatStageRuntimeConfig.configThemeColor),
    configUseMainThemeColor:
      typeof parsed.configUseMainThemeColor === "boolean"
        ? parsed.configUseMainThemeColor
        : defaultChatStageRuntimeConfig.configUseMainThemeColor,
    dialogFill: readRuntimeDialogFill(parsed.dialogFill),
    dialogOpacity: clampRuntimeNumber(
      parsed.dialogOpacity,
      defaultChatStageRuntimeConfig.dialogOpacity,
      runtimeDialogOpacityMin,
      runtimeDialogOpacityMax,
    ),
    dialogScale: clampRuntimeNumber(
      parsed.dialogScale,
      defaultChatStageRuntimeConfig.dialogScale,
      runtimeDialogScaleMin,
      runtimeDialogScaleMax,
    ),
    immersiveMode:
      typeof parsed.immersiveMode === "boolean" ? parsed.immersiveMode : defaultChatStageRuntimeConfig.immersiveMode,
    longPressTalk:
      typeof parsed.longPressTalk === "boolean" ? parsed.longPressTalk : defaultChatStageRuntimeConfig.longPressTalk,
    typewriterCps:
      parsed.typewriterCps == null
        ? null
        : Math.round(
            clampRuntimeNumber(parsed.typewriterCps, DEFAULT_TYPEWRITER_CPS, runtimeTextSpeedMin, runtimeTextSpeedMax),
          ),
    spriteScales: readRuntimeSpriteScales(parsed),
    spriteOffsetX: Math.round(
      clampRuntimeNumber(
        parsed.spriteOffsetX,
        defaultChatStageRuntimeConfig.spriteOffsetX,
        runtimeSpriteOffsetMin,
        runtimeSpriteOffsetMax,
      ),
    ),
    spriteOffsetY: Math.round(
      clampRuntimeNumber(
        parsed.spriteOffsetY,
        defaultChatStageRuntimeConfig.spriteOffsetY,
        runtimeSpriteOffsetMin,
        runtimeSpriteOffsetMax,
      ),
    ),
    windowScale: clampRuntimeNumber(
      parsed.windowScale,
      defaultChatStageRuntimeConfig.windowScale,
      runtimeWindowScaleMin,
      runtimeWindowScaleMax,
    ),
    nameText: readRuntimeTextStyle(
      parsed.nameText,
      defaultChatStageRuntimeConfig.nameText,
      runtimeNameFontSizeMin,
      runtimeNameFontSizeMax,
    ),
    dialogText: readRuntimeTextStyle(
      parsed.dialogText,
      defaultChatStageRuntimeConfig.dialogText,
      runtimeDialogFontSizeMin,
      runtimeDialogFontSizeMax,
    ),
  };
}

function persistedRuntimeConfigEnvelope(config: ChatStageRuntimeConfig): ChatStageRuntimeConfigStorageEnvelope {
  return {
    config,
    version: chatStageRuntimeConfigVersion,
  };
}

export function readChatStageRuntimeConfig(): ChatStageRuntimeConfig {
  if (typeof window === "undefined") {
    return defaultChatStageRuntimeConfig;
  }
  try {
    const raw = window.localStorage.getItem(runtimeConfigStorageKey);
    if (!raw) {
      return defaultChatStageRuntimeConfig;
    }
    return normalizeChatStageRuntimeConfig(JSON.parse(raw));
  } catch {
    return defaultChatStageRuntimeConfig;
  }
}

export function writeChatStageRuntimeConfig(config: ChatStageRuntimeConfig) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(runtimeConfigStorageKey, JSON.stringify(persistedRuntimeConfigEnvelope(config)));
  } catch {
    // localStorage may be unavailable in hardened webviews.
  }
}

export function runtimeSpriteKey(sprite: ChatStageSprite, index: number) {
  // Key sprite scale by CHARACTER identity (same order as chatStageSpriteCharacterName),
  // never the volatile `id`: the backend sends `id` as "{name}-0" in snapshots but the
  // live `sprite.show` event uses "{name}", so an id-first key gives one character's
  // sprites mismatched sizes as expressions swap or the stage reloads.
  return (sprite.characterName ?? sprite.label ?? sprite.id ?? "").trim() || `slot-${sprite.slot ?? index}`;
}

export function runtimeSpriteLabel(sprite: ChatStageSprite, index: number) {
  return sprite.label || sprite.characterName || sprite.id || `#${index + 1}`;
}

export function runtimeSpriteScale(config: ChatStageRuntimeConfig, sprite: ChatStageSprite, index: number) {
  const key = runtimeSpriteKey(sprite, index);
  return config.spriteScales[key] ?? config.spriteScales[runtimeSpriteDefaultScaleKey] ?? 1;
}

function runtimeTextColor(value: string, fallback: string, themeVariable: string) {
  return value === fallback ? `var(${themeVariable}, ${fallback})` : value;
}

function runtimeTextFontFamily(value: string, themeVariable: string) {
  return value || `var(${themeVariable}, var(--font-chat))`;
}

function runtimeTextFontSize(value: number, fallback: number, themeVariable: string) {
  return value === fallback ? `var(${themeVariable}, ${fallback}px)` : `${value}px`;
}

function runtimeTextFontWeight(
  value: boolean,
  fallback: boolean,
  themeVariable: string,
  activeWeight: string,
  inactiveWeight: string,
  override?: boolean,
) {
  return !override && value === fallback
    ? `var(${themeVariable}, ${fallback ? activeWeight : inactiveWeight})`
    : value
      ? activeWeight
      : inactiveWeight;
}

function runtimeTextBoldIsExplicit(config: ChatStageTextStyleConfig, fallback: ChatStageTextStyleConfig) {
  return config.boldOverride === true || config.bold !== fallback.bold;
}

function runtimeTextAlignIsExplicit(config: ChatStageTextStyleConfig, fallback: ChatStageTextStyleConfig) {
  return config.alignOverride === true || config.align !== fallback.align;
}

function runtimeThemeTextAlign(themeStyle: CSSProperties, fallback: ChatStageTextAlign) {
  const value = themeStyleString(themeStyle, "--chat-dialog-text-theme-align") as ChatStageTextAlign;
  return chatStageTextAlignments.includes(value) ? value : fallback;
}

function hexToRgb(value: string) {
  const match = value.match(/^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i);
  if (!match) {
    return null;
  }
  return {
    b: Number.parseInt(match[3] ?? "0", 16),
    g: Number.parseInt(match[2] ?? "0", 16),
    r: Number.parseInt(match[1] ?? "0", 16),
  };
}

function runtimeRgba(color: string, opacity: number) {
  const rgb = hexToRgb(color);
  const alpha = Number(clampRuntimeNumber(opacity, 1, 0, 1).toFixed(3));
  return rgb ? `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})` : color;
}

function dialogFillMatchesDefault(fill: ChatStageDialogFillConfig) {
  const fallback = defaultChatStageRuntimeConfig.dialogFill;
  return (
    fill.color === fallback.color &&
    fill.color2 === fallback.color2 &&
    fill.gradient === fallback.gradient &&
    fill.gradientDirection === fallback.gradientDirection &&
    fill.gradientMode === fallback.gradientMode &&
    fill.opacity === fallback.opacity
  );
}

function runtimeDialogFillBackground(fill: ChatStageDialogFillConfig) {
  if (dialogFillMatchesDefault(fill)) {
    return undefined;
  }
  const primary = runtimeRgba(fill.color, fill.opacity);
  if (!fill.gradient) {
    return primary;
  }
  if (fill.gradientMode === "dual") {
    return `linear-gradient(180deg, ${primary}, ${runtimeRgba(fill.color2, fill.opacity)})`;
  }
  const angle = fill.gradientDirection === "to-top" ? "0deg" : "180deg";
  const transparent = runtimeRgba(fill.color, 0);
  return `linear-gradient(${angle}, ${primary}, ${transparent})`;
}

function themeStyleString(themeStyle: CSSProperties, name: `--${string}`) {
  const value = (themeStyle as Record<string, unknown>)[name];
  return typeof value === "string" ? value.trim() : "";
}

function runtimeThemeFontSize(themeStyle: CSSProperties, name: `--${string}`, fallback: number) {
  const value = themeStyleString(themeStyle, name);
  const match = value.match(/^(\d+(?:\.\d+)?)px$/);
  return match ? Math.round(clampRuntimeNumber(match[1], fallback, 1, 96)) : fallback;
}

function runtimeThemeBold(themeStyle: CSSProperties, name: `--${string}`, fallback: boolean) {
  const value = themeStyleString(themeStyle, name);
  if (!value) {
    return fallback;
  }
  const weight = Number(value);
  return Number.isFinite(weight) ? weight >= 600 : fallback;
}

export function effectiveChatStageTextStyle(
  config: ChatStageTextStyleConfig,
  fallback: ChatStageTextStyleConfig,
  themeStyle: CSSProperties,
  target: ChatStageTextStyleTarget,
): ChatStageTextStyleConfig {
  const dialog = target === "dialogText";
  const colorVar = dialog ? "--chat-dialog-text-theme-color" : "--chat-name-theme-color";
  const familyVar = dialog ? "--chat-dialog-text-theme-font-family" : "--chat-name-theme-font-family";
  const sizeVar = dialog ? "--chat-dialog-text-theme-font-size" : "--chat-name-theme-font-size";
  const weightVar = dialog ? "--chat-dialog-text-theme-font-weight" : "--chat-name-theme-font-weight";
  const themeColor = sanitizeRuntimeColor(themeStyleString(themeStyle, colorVar), fallback.color);
  const themeFontFamily = themeStyleString(themeStyle, familyVar) || themeStyleString(themeStyle, "--font-chat");
  const explicitBold = runtimeTextBoldIsExplicit(config, fallback);
  const explicitAlign = runtimeTextAlignIsExplicit(config, fallback);
  const next: ChatStageTextStyleConfig = {
    alignOverride: config.alignOverride,
    bold: explicitBold ? config.bold : runtimeThemeBold(themeStyle, weightVar, fallback.bold),
    boldOverride: config.boldOverride,
    color: config.color === fallback.color ? themeColor : config.color,
    fontFamily: config.fontFamily || themeFontFamily,
    fontSize:
      config.fontSize === fallback.fontSize
        ? runtimeThemeFontSize(themeStyle, sizeVar, fallback.fontSize)
        : config.fontSize,
  };
  if (fallback.align) {
    next.align = explicitAlign ? (config.align ?? fallback.align) : runtimeThemeTextAlign(themeStyle, fallback.align);
  }
  if (fallback.direction) {
    next.direction = config.direction ?? fallback.direction;
  }
  return next;
}

export function chatStageRuntimeStyle(
  config: ChatStageRuntimeConfig,
  themeStyle: CSSProperties,
  mainThemeColor = DEFAULT_THEME_COLOR,
): CSSProperties {
  const configAccent = normalizeThemeColor(config.configUseMainThemeColor ? mainThemeColor : config.configThemeColor);
  const dialogFillBackground = runtimeDialogFillBackground(config.dialogFill);
  const dialogScale = clampRuntimeNumber(
    config.dialogScale,
    defaultChatStageRuntimeConfig.dialogScale,
    runtimeDialogScaleMin,
    runtimeDialogScaleMax,
  );
  const windowScale = clampRuntimeNumber(
    config.windowScale,
    defaultChatStageRuntimeConfig.windowScale,
    runtimeWindowScaleMin,
    runtimeWindowScaleMax,
  );
  return {
    ...themeStyle,
    "--chat-config-accent": configAccent,
    "--chat-dialog-runtime-opacity": String(config.dialogOpacity),
    ...(dialogFillBackground ? { "--chat-dialog-runtime-background": dialogFillBackground } : {}),
    "--chat-dialog-runtime-inverse-scale": String(Number((1 / dialogScale).toFixed(4))),
    "--chat-dialog-runtime-scale": String(dialogScale),
    "--chat-dialog-composed-scale": String(Number((dialogScale * windowScale).toFixed(4))),
    "--chat-dialog-runtime-width": "1040px",
    "--chat-dialog-text-runtime-color": runtimeTextColor(
      config.dialogText.color,
      defaultChatStageRuntimeConfig.dialogText.color,
      "--chat-dialog-text-theme-color",
    ),
    "--chat-dialog-text-runtime-font-family": runtimeTextFontFamily(
      config.dialogText.fontFamily,
      "--chat-dialog-text-theme-font-family",
    ),
    "--chat-dialog-text-runtime-font-size": runtimeTextFontSize(
      config.dialogText.fontSize,
      defaultChatStageRuntimeConfig.dialogText.fontSize,
      "--chat-dialog-text-theme-font-size",
    ),
    "--chat-dialog-text-runtime-font-weight": runtimeTextFontWeight(
      config.dialogText.bold,
      defaultChatStageRuntimeConfig.dialogText.bold,
      "--chat-dialog-text-theme-font-weight",
      "700",
      "400",
      runtimeTextBoldIsExplicit(config.dialogText, defaultChatStageRuntimeConfig.dialogText),
    ),
    "--chat-dialog-text-align": runtimeTextAlignIsExplicit(config.dialogText, defaultChatStageRuntimeConfig.dialogText)
      ? (config.dialogText.align ?? defaultChatStageRuntimeConfig.dialogText.align ?? "center")
      : "var(--chat-dialog-text-theme-align, center)",
    "--chat-dialog-text-direction":
      config.dialogText.direction ?? defaultChatStageRuntimeConfig.dialogText.direction ?? "ltr",
    "--chat-dialog-render-direction": "ltr",
    "--chat-name-runtime-color": runtimeTextColor(
      config.nameText.color,
      defaultChatStageRuntimeConfig.nameText.color,
      "--chat-name-theme-color",
    ),
    "--chat-name-runtime-font-family": runtimeTextFontFamily(
      config.nameText.fontFamily,
      "--chat-name-theme-font-family",
    ),
    "--chat-name-runtime-font-size": runtimeTextFontSize(
      config.nameText.fontSize,
      defaultChatStageRuntimeConfig.nameText.fontSize,
      "--chat-name-theme-font-size",
    ),
    "--chat-name-runtime-font-weight": runtimeTextFontWeight(
      config.nameText.bold,
      defaultChatStageRuntimeConfig.nameText.bold,
      "--chat-name-theme-font-weight",
      "800",
      "600",
      runtimeTextBoldIsExplicit(config.nameText, defaultChatStageRuntimeConfig.nameText),
    ),
    "--chat-sprite-runtime-offset-x": `${config.spriteOffsetX}px`,
    "--chat-sprite-runtime-offset-y": `${config.spriteOffsetY}px`,
    "--chat-toolbar-runtime-scale": String(windowScale),
    "--chat-ui-runtime-width": "1120px",
    "--chat-ui-window-scale": String(windowScale),
  } as CSSProperties;
}
