// chat_ui 主题 mod 系统 —— 令牌 + 资源主题契约（无可执行代码）。
//
// 这是设计文档《chat_ui_react_migration_and_theme_system.md》"参考接口输出 · A"的占位实现。
// 当前为 M0 骨架：类型契约完整、resolveChatTheme 仅做最小映射，校验/字体注入/沙箱在 M5 补全。
//
// 设计规范（统一 token 契约）：每个 token 映射到 chat-stage.css 已有的 --chat-* CSS 变量；
// 主题只能在此契约内改外观，禁止破坏布局的声明（width/height/position/font-size 等）。

import type { ChatStageStyle } from "./chatChromeTheme";

export type { ChatStageStyle } from "./chatChromeTheme";

/** 当前 manifest schema 版本。后端校验与前端解析都以此为准。 */
export const CHAT_THEME_SCHEMA = 1 as const;

/** 默认内置 chat_ui 主题。 */
export const DEFAULT_CHAT_THEME_ID = "windborne-adventure";

/** 一组可视化声明（颜色 / 背景图 / 边框 / 圆角 / 阴影 / 内边距），对应一块 UI 的 --chat-<block>-* 变量。 */
export interface VisualBlock {
  background?: string;
  /** 背景图，主题目录内相对路径（沙箱）。 */
  backgroundImage?: string;
  borderColor?: string;
  borderRadius?: string;
  color?: string;
  /** 像素值；解析时 clamp。 */
  padding?: number;
  boxShadow?: string;
  /** ADV 边框贴图（9-slice），主题目录内相对路径（沙箱）。仅 dialog / name 块消费。 */
  frameImage?: string;
  /** 边框切片像素（border-image slice/width），clamp 1–200，默认 32。 */
  frameSlice?: number;
}

/** 自定义字体声明，运行时注入为 @font-face。src 为主题目录内相对路径。 */
export interface ChatThemeFontFace {
  family: string;
  src: string;
  weight?: string;
  style?: string;
}

/** 主题可填写的全部 token —— 即"统一设计规范"。 */
export interface ChatThemeTokens {
  global?: { themeColor?: string; fontFamily?: string };
  fonts?: ChatThemeFontFace[];
  dialog?: VisualBlock & {
    /** 对话区 chrome；none = 字幕模式，无背景框、无边框、无滚动限制。 */
    chrome?: "panel" | "none";
    /** 对话框宽度占比（vw），clamp 30–100。 */
    widthPct?: number;
    /** 固定对话区高度（px），clamp 96–260。 */
    heightPx?: number;
    /** 名牌装饰中心线到输入框顶部的目标距离（svh）；不填写则使用基础布局。 */
    nameInputGapVh?: number;
    /** 垂直偏移（px），clamp -240–240。 */
    offsetY?: number;
    /** 正文对齐方式。 */
    textAlign?: "left" | "center";
    textShadow?: string;
    textSizePx?: number;
    textWeight?: number;
  };
  options?: VisualBlock & {
    active?: VisualBlock;
    gap?: number;
    hover?: VisualBlock;
    icon?: "none" | "chat";
    maxWidthVw?: number;
    minHeightVh?: number;
    minWidthVw?: number;
    placement?: "center" | "right";
    minHeightPx?: number;
    nameClearanceVh?: number;
    textShadow?: string;
    textSizeVh?: number;
    textSizePx?: number;
    textWeight?: number;
    widthPx?: number;
    widthMode?: "fixed" | "content";
  };
  input?: VisualBlock & {
    fieldBackground?: string;
    fieldBorderRadius?: string;
    layout?: "default" | "pill";
    maxWidthPx?: number;
    sendPlacement?: "outside" | "inside";
  };
  toolbar?: VisualBlock & { placement?: "dialog-top" | "input" | "input-top"; reveal?: "always" | "hover" };
  send?: VisualBlock;
  name?: VisualBlock & {
    align?: "left" | "center";
    decoration?: "accent" | "line-dots";
    fontFamily?: string;
    hideWhenStartOption?: boolean;
    textShadow?: string;
    textSizePx?: number;
    textWeight?: number;
  };
  logs?: LogsThemeTokens;
  /** 打字机：每秒字数 + 可选打字音效（主题目录内相对路径）。 */
  typewriter?: { cps?: number; sound?: string };
}

type LogsLevelThemeTokens = Partial<Record<"debug" | "default" | "error" | "info" | "warn", VisualBlock>>;

export interface LogsThemeTokens {
  badge?: VisualBlock;
  code?: VisualBlock & { fontFamily?: string };
  detail?: VisualBlock;
  event?: VisualBlock;
  fileItem?: VisualBlock & { active?: VisualBlock; hover?: VisualBlock };
  levels?: LogsLevelThemeTokens;
  line?: VisualBlock & { expanded?: VisualBlock; hover?: VisualBlock };
  number?: VisualBlock;
  page?: VisualBlock;
  panel?: VisualBlock;
  sidebar?: VisualBlock;
  source?: VisualBlock;
  toolbar?: VisualBlock;
  viewer?: VisualBlock;
}

/** 完整主题清单（theme.json）。 */
export interface ChatThemeManifest {
  schema: typeof CHAT_THEME_SCHEMA;
  id: string;
  /** i18n 名称：{ zh_CN, en, ja, ... } */
  name: Record<string, string>;
  author?: string;
  version?: string;
  description?: Record<string, string>;
  /** 缩略图，主题目录内相对路径。 */
  preview?: string;
  tokens: ChatThemeTokens;
}

/** 主题列表项（不含完整 tokens），用于主题选择器。 */
export interface ChatThemeSummary {
  id: string;
  name: Record<string, string>;
  author?: string;
  version?: string;
  /** 已解析为可直接 <img src> 的 URL（通常 /api/media?path=...）。 */
  previewUrl?: string;
  source: "builtin" | "user";
}

/** resolveChatTheme 的产物：可直接喂给 style / <style> / 打字机的中间结构。 */
export interface ResolvedChatTheme {
  /** 写入 chat stage 根元素 style 的 --chat-* 变量集合。 */
  style: ChatStageStyle;
  /** 注入 <style> 的 @font-face 文本（无字体时为空串）。 */
  fontFaces: string;
  /** 前端打字机参数。 */
  typewriter: { cps: number; soundUrl?: string };
}

/** 打字机默认速率（字/秒），与原生 TypingLabel 体感对齐。 */
export const DEFAULT_TYPEWRITER_CPS = 40;

const forbiddenCssDeclaration =
  /\b(width|height|min-width|max-width|min-height|max-height|position|left|right|top|bottom|font-size)\s*:/i;

function isSafeCssValue(value: unknown): value is string {
  if (typeof value !== "string") {
    return false;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return false;
  }
  if (/[{};]/.test(trimmed)) {
    return false;
  }
  if (/url\s*\(/i.test(trimmed)) {
    return false;
  }
  return !forbiddenCssDeclaration.test(trimmed);
}

function normalizeThemeAssetRef(value: unknown) {
  if (typeof value !== "string") {
    return "";
  }
  const normalized = value.trim().replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(normalized)) {
    return "";
  }
  if (normalized.startsWith("/") || normalized.startsWith("\\")) {
    return "";
  }
  const parts = normalized.split("/");
  if (parts.some((part) => part === "..")) {
    return "";
  }
  return parts.filter(Boolean).join("/");
}

function clampNumber(value: unknown, fallback: number, min: number, max: number) {
  const next = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(next)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, next));
}

function setStyleVar(style: ChatStageStyle, name: `--${string}`, value: unknown) {
  if (!isSafeCssValue(value)) {
    return;
  }
  style[name] = value.trim();
}

function setPxVar(
  style: ChatStageStyle,
  name: `--${string}`,
  value: unknown,
  fallback: number,
  min: number,
  max: number,
) {
  if (typeof value !== "number") {
    return;
  }
  style[name] = `${clampNumber(value, fallback, min, max)}px`;
}

function setVhVar(
  style: ChatStageStyle,
  name: `--${string}`,
  value: unknown,
  min: number,
  max: number,
) {
  if (typeof value !== "number") {
    return;
  }
  style[name] = `${Number(clampNumber(value, min, min, max).toFixed(2))}svh`;
}

function setVhClampVar(
  style: ChatStageStyle,
  name: `--${string}`,
  value: unknown,
  min: number,
  max: number,
  minPx: number,
  maxPx: number,
) {
  if (typeof value !== "number") {
    return;
  }
  const vh = Number(clampNumber(value, min, min, max).toFixed(2));
  style[name] = `clamp(${minPx}px, ${vh}svh, ${maxPx}px)`;
}

function setVwClampVar(
  style: ChatStageStyle,
  name: `--${string}`,
  value: unknown,
  min: number,
  max: number,
  minPx: number,
  maxPx: number,
) {
  if (typeof value !== "number") {
    return;
  }
  const vw = Number(clampNumber(value, min, min, max).toFixed(2));
  style[name] = `clamp(${minPx}px, ${vw}vw, ${maxPx}px)`;
}

function setIntegerVar(
  style: ChatStageStyle,
  name: `--${string}`,
  value: unknown,
  fallback: number,
  min: number,
  max: number,
) {
  if (typeof value !== "number") {
    return;
  }
  style[name] = String(Math.round(clampNumber(value, fallback, min, max)));
}

function applyVisualBlock(
  style: ChatStageStyle,
  prefix: string,
  block?: VisualBlock | null,
  assetUrl?: (rel: string) => string,
) {
  if (!block) {
    return;
  }
  setStyleVar(style, `--chat-${prefix}-background`, block.background);
  if (assetUrl && block.backgroundImage) {
    const backgroundImage = resolveThemeAssetUrl(block.backgroundImage, assetUrl);
    if (backgroundImage) {
      style[`--chat-${prefix}-background-image`] = `url("${backgroundImage}")`;
    }
  }
  if (assetUrl && block.frameImage) {
    const frameImage = resolveThemeAssetUrl(block.frameImage, assetUrl);
    if (frameImage) {
      const slice = clampNumber(block.frameSlice, 32, 1, 200);
      style[`--chat-${prefix}-frame`] = `url("${frameImage}") ${slice} fill / ${slice}px round`;
    }
  }
  setStyleVar(style, `--chat-${prefix}-border-color`, block.borderColor);
  setStyleVar(style, `--chat-${prefix}-border-radius`, block.borderRadius);
  setStyleVar(style, `--chat-${prefix}-color`, block.color);
  setStyleVar(style, `--chat-${prefix}-box-shadow`, block.boxShadow);
  if (typeof block.padding === "number") {
    style[`--chat-${prefix}-padding`] = `${clampNumber(block.padding, 40, 8, 72)}px`;
  }
}

function applyLogsVisualBlock(
  style: ChatStageStyle,
  prefix: string,
  block?: VisualBlock | null,
  assetUrl?: (rel: string) => string,
) {
  if (!block) {
    return;
  }
  setStyleVar(style, `--logs-${prefix}-background`, block.background);
  if (assetUrl && block.backgroundImage) {
    const backgroundImage = resolveThemeAssetUrl(block.backgroundImage, assetUrl);
    if (backgroundImage) {
      style[`--logs-${prefix}-background-image`] = `url("${backgroundImage}")`;
    }
  }
  setStyleVar(style, `--logs-${prefix}-border-color`, block.borderColor);
  setStyleVar(style, `--logs-${prefix}-border-radius`, block.borderRadius);
  setStyleVar(style, `--logs-${prefix}-color`, block.color);
  setStyleVar(style, `--logs-${prefix}-box-shadow`, block.boxShadow);
  if (typeof block.padding === "number") {
    style[`--logs-${prefix}-padding`] = `${clampNumber(block.padding, 40, 8, 72)}px`;
  }
}

function mergeVisualBlock<T extends VisualBlock>(base?: T | null, override?: T | null): T | undefined {
  if (!base && !override) {
    return undefined;
  }
  return { ...(base ?? {}), ...(override ?? {}) } as T;
}

function resolveLogsThemeTokens(tokens: ChatThemeTokens): LogsThemeTokens {
  const logs = tokens.logs ?? {};
  const accentBlock: VisualBlock = {
    background: tokens.options?.background,
    borderColor: tokens.options?.borderColor,
    color: tokens.name?.color ?? tokens.global?.themeColor,
  };
  const codeFallback: LogsThemeTokens["code"] = {
    background: tokens.input?.fieldBackground ?? tokens.input?.background ?? tokens.dialog?.background,
    color: tokens.input?.color ?? tokens.dialog?.color,
  };
  return {
    page: mergeVisualBlock({ color: tokens.dialog?.color }, logs.page),
    panel: mergeVisualBlock(tokens.toolbar ?? tokens.dialog, logs.panel),
    toolbar: mergeVisualBlock(tokens.toolbar, logs.toolbar),
    sidebar: mergeVisualBlock(tokens.toolbar ?? tokens.input, logs.sidebar),
    source: mergeVisualBlock(accentBlock, logs.source),
    viewer: mergeVisualBlock(tokens.dialog, logs.viewer),
    code: mergeVisualBlock(codeFallback, logs.code),
    line: logs.line,
    number: logs.number,
    detail: mergeVisualBlock(tokens.input, logs.detail),
    badge: mergeVisualBlock({ color: tokens.options?.color ?? tokens.dialog?.color }, logs.badge),
    event: mergeVisualBlock(accentBlock, logs.event),
    fileItem: logs.fileItem,
    levels: logs.levels,
  };
}

function quotedFontFamily(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  if (!isSafeCssValue(trimmed)) {
    return "";
  }
  if (trimmed.includes(",")) {
    return trimmed;
  }
  if (/["']/.test(trimmed) || /^[a-z0-9_-]+$/i.test(trimmed)) {
    return trimmed;
  }
  return `"${trimmed.replace(/"/g, '\\"')}"`;
}

function resolveThemeAssetUrl(rel: unknown, assetUrl: (rel: string) => string) {
  const normalized = normalizeThemeAssetRef(rel);
  return normalized ? assetUrl(normalized) : "";
}

/**
 * manifest + 资源 URL 解析器 → CSS 变量 / 字体 / 打字机参数。
 *
 * M0 占位：仅做最小、安全的映射（颜色与数值 token），不抛错；
 * 完整 token 覆盖、@font-face 注入、url() 沙箱与校验在 M5（主题系统）补全。
 *
 * @param manifest 主题清单
 * @param assetUrl 把主题目录内相对路径解析为可访问 URL 的函数（如 rel => `${apiBase}/api/media?path=...`）
 */
export function resolveChatTheme(manifest: ChatThemeManifest, assetUrl: (rel: string) => string): ResolvedChatTheme {
  const tokens = manifest.tokens ?? {};
  const style: ChatStageStyle = {};

  if (isSafeCssValue(tokens.global?.themeColor)) {
    style["--chat-theme-color"] = tokens.global.themeColor;
  }
  if (typeof tokens.global?.fontFamily === "string") {
    const fontFamily = quotedFontFamily(tokens.global.fontFamily);
    if (fontFamily) {
      style["--font-chat"] = fontFamily;
    }
  }

  const dialog = tokens.dialog;
  applyVisualBlock(style, "dialog", dialog, assetUrl);
  if (typeof dialog?.heightPx === "number" || dialog?.chrome === "none") {
    style["--chat-dialog-height"] = `${clampNumber(dialog?.heightPx, 156, 96, 260)}px`;
    style["--chat-dialog-body-height"] = "100%";
    style["--chat-dialog-body-min-height"] = "0px";
  }
  if (dialog?.chrome === "none") {
    style["--chat-dialog-backdrop-filter"] = "none";
    style["--chat-dialog-actions-border"] = "0 solid transparent";
    style["--chat-dialog-body-max-height"] = "none";
    style["--chat-dialog-body-overflow"] = "visible";
    style["--chat-dialog-body-scrollbar-gutter"] = "auto";
    style["--chat-dialog-border"] = "0 solid transparent";
    style["--chat-dialog-min-height"] = "0px";
    style["--chat-dialog-toolbar-gap"] = "10px";
    style["--chat-dialog-toolbar-padding-bottom"] = "0px";
    style["--chat-sheen"] = "none";
  }
  if (typeof dialog?.nameInputGapVh === "number") {
    setVhVar(style, "--chat-dialog-name-input-gap", dialog.nameInputGapVh, 12, 32);
    style["--chat-dialog-stack-bottom"] =
      "calc(var(--stage-control-stack-height) + var(--chat-dialog-name-input-gap) - var(--chat-dialog-height) - var(--chat-name-line-offset) - var(--chat-dialog-offset-y))";
  }
  if (typeof dialog?.widthPct === "number") {
    style["--chat-dialog-width"] = `min(${clampNumber(dialog.widthPct, 86, 30, 100)}vw, 980px)`;
  }
  if (typeof dialog?.offsetY === "number") {
    style["--chat-dialog-offset-y"] = `${clampNumber(dialog.offsetY, 0, -240, 240)}px`;
  }
  if (dialog?.textAlign === "center") {
    style["--chat-dialog-text-align"] = "center";
  }
  if (isSafeCssValue(dialog?.color)) {
    style["--chat-dialog-text-theme-color"] = dialog.color.trim();
  }
  if (typeof tokens.global?.fontFamily === "string") {
    const fontFamily = quotedFontFamily(tokens.global.fontFamily);
    if (fontFamily) {
      style["--chat-dialog-text-theme-font-family"] = fontFamily;
      style["--chat-name-theme-font-family"] = fontFamily;
    }
  }
  setPxVar(style, "--chat-dialog-text-theme-font-size", dialog?.textSizePx, 17, 12, 64);
  setIntegerVar(style, "--chat-dialog-text-theme-font-weight", dialog?.textWeight, 400, 300, 900);
  setStyleVar(style, "--chat-dialog-text-shadow", dialog?.textShadow);

  const options = tokens.options;
  applyVisualBlock(style, "option", options, assetUrl);
  applyVisualBlock(style, "option-active", options?.active, assetUrl);
  applyVisualBlock(style, "option-hover", options?.hover, assetUrl);
  if (isSafeCssValue(options?.color)) {
    style["--chat-options-color"] = options.color;
  }
  if (typeof options?.gap === "number") {
    style["--chat-options-gap"] = `${clampNumber(options.gap, 10, 0, 36)}px`;
  }
  if (options?.placement === "right") {
    style["--chat-options-left"] = "calc(100% - var(--stage-safe-x))";
    style["--chat-options-bottom"] =
      typeof dialog?.nameInputGapVh === "number"
        ? "calc(var(--stage-control-stack-height) + var(--chat-dialog-name-input-gap) + var(--chat-options-name-clearance))"
        : "calc(var(--stage-control-stack-height) + var(--chat-dialog-toolbar-reserved-height) + var(--chat-dialog-height) + var(--chat-options-name-clearance) - var(--chat-dialog-offset-y))";
    style["--chat-options-top"] = "auto";
    style["--chat-options-transform"] = "translateX(-100%)";
  }
  setPxVar(style, "--chat-options-width", options?.widthPx, 460, 260, 720);
  if (options?.widthMode === "content") {
    style["--chat-options-width"] = "max-content";
    setVwClampVar(style, "--chat-options-min-width", options.minWidthVw, 12, 42, 320, 720);
    if (typeof options.maxWidthVw === "number") {
      const vw = Number(clampNumber(options.maxWidthVw, 42, 20, 60).toFixed(2));
      style["--chat-options-max-width"] = `min(${vw}vw, 760px, calc(100vw - 32px))`;
    }
    style["--chat-options-mobile-left"] = "var(--chat-options-left)";
    style["--chat-options-mobile-max-width"] = "calc(100vw - 24px)";
    style["--chat-options-mobile-min-width"] = "min(var(--chat-options-min-width), calc(100vw - 24px))";
    style["--chat-options-mobile-right"] = "auto";
    style["--chat-options-mobile-transform"] = "var(--chat-options-transform)";
    style["--chat-options-mobile-width"] = "var(--chat-options-width)";
  }
  setPxVar(style, "--chat-option-min-height", options?.minHeightPx, 46, 36, 96);
  setVhClampVar(style, "--chat-option-min-height", options?.minHeightVh, 3, 8, 36, 96);
  setVhVar(style, "--chat-options-name-clearance", options?.nameClearanceVh, 2, 12);
  setPxVar(style, "--chat-option-font-size", options?.textSizePx, 16, 12, 64);
  setVhClampVar(style, "--chat-option-font-size", options?.textSizeVh, 1, 4, 18, 32);
  setIntegerVar(style, "--chat-option-font-weight", options?.textWeight, 600, 300, 900);
  setStyleVar(style, "--chat-option-text-shadow", options?.textShadow);
  if (options?.icon === "chat") {
    style["--chat-option-icon-opacity"] = "1";
    style["--chat-option-icon-size"] = "clamp(28px, 3.78svh, 38px)";
    style["--chat-option-justify-content"] = "flex-start";
    style["--chat-option-padding"] = "8px 18px 8px 60px";
    style["--chat-option-text-align"] = "left";
  }

  const input = tokens.input;
  applyVisualBlock(style, "input", input, assetUrl);
  if (isSafeCssValue(input?.fieldBackground)) {
    style["--chat-input-field-background"] = input.fieldBackground;
  }
  if (isSafeCssValue(input?.fieldBorderRadius)) {
    style["--chat-input-field-border-radius"] = input.fieldBorderRadius;
  }
  if (typeof input?.maxWidthPx === "number") {
    style["--chat-input-max-width"] = `${clampNumber(input.maxWidthPx, 640, 320, 900)}px`;
  }
  if (input?.layout === "pill") {
    style["--chat-input-layout"] = "pill";
    style["--chat-input-max-width"] = `${clampNumber(input.maxWidthPx, 640, 320, 900)}px`;
    style["--stage-input-height"] = "calc(var(--chat-input-button-size) + clamp(10px, 1.44svh, 14px))";
    style["--chat-input-border"] = "0 solid transparent";
    style["--chat-input-border-radius"] = "999px";
    style["--chat-input-field-background"] = "transparent";
    style["--chat-input-field-border-radius"] = "0px";
    style["--chat-input-field-display"] = "contents";
    style["--chat-input-field-position"] = "static";
    style["--chat-input-gap"] = "clamp(8px, 1.2vw, 14px)";
    style["--chat-input-grid-template-columns"] = "var(--chat-input-button-size) minmax(0, 1fr) auto";
    style["--chat-input-padding"] = "clamp(5px, 0.72svh, 7px) clamp(7px, 0.9svh, 10px)";
    style["--chat-input-panel-display"] = "grid";
    style["--chat-input-pill-control-display"] = "inline-flex";
    style["--chat-input-send-display"] = "none";
    style["--chat-input-textarea-font-size"] = "clamp(17px, 2svh, 22px)";
    style["--chat-input-textarea-max-height"] = "48px";
    style["--chat-input-textarea-min-height"] = "42px";
    style["--chat-input-textarea-padding-right"] = "0px";
    style["--chat-input-voice-stack-display"] = "none";
  }
  if (input?.sendPlacement === "inside" && input?.layout !== "pill") {
    style["--chat-input-grid-template-columns"] = "minmax(0, 1fr) 38px";
    style["--chat-input-field-display"] = "block";
    style["--chat-input-field-position"] = "relative";
    style["--chat-input-textarea-padding-right"] = "56px";
    style["--chat-send-active-transform"] = "translateY(-50%)";
    style["--chat-send-border"] = "0 solid transparent";
    style["--chat-send-box-shadow"] = "none";
    style["--chat-send-height"] = "36px";
    style["--chat-send-hover-sheen"] = "none";
    style["--chat-send-hover-transform"] = "translateY(-50%)";
    style["--chat-send-icon-size"] = "18px";
    style["--chat-send-label-display"] = "none";
    style["--chat-send-min-height"] = "36px";
    style["--chat-send-min-width"] = "36px";
    style["--chat-send-padding"] = "0";
    style["--chat-send-position"] = "absolute";
    style["--chat-send-right"] = "11px";
    style["--chat-send-sheen"] = "none";
    style["--chat-send-top"] = "50%";
    style["--chat-send-transform"] = "translateY(-50%)";
    style["--chat-send-width"] = "36px";
  }

  const toolbar = tokens.toolbar;
  applyVisualBlock(style, "toolbar", toolbar, assetUrl);
  if (toolbar?.placement === "dialog-top") {
    style["--chat-dialog-toolbar-placement"] = "dialog-top";
    style["--chat-dialog-toolbar-layer-bottom"] =
      "calc(var(--chat-dialog-stack-bottom) + var(--chat-dialog-height) + 4px)";
    style["--chat-dialog-toolbar-layer-max-width"] = "calc(100vw - 32px)";
    style["--chat-dialog-toolbar-layer-padding"] = "26px 0 0";
    style["--chat-dialog-toolbar-layer-width"] = "min(var(--chat-ui-runtime-width), calc(100vw - 32px))";
    style["--chat-dialog-toolbar-reveal"] = toolbar.reveal === "hover" ? "hover" : "always";
    style["--chat-dialog-toolbar-hidden-y"] = "16px";
  } else if (toolbar?.placement === "input" || toolbar?.placement === "input-top") {
    style["--chat-dialog-toolbar-input-clearance"] = "36px";
    style["--chat-dialog-toolbar-placement"] = "input";
    style["--chat-dialog-toolbar-reveal"] = toolbar.reveal === "hover" ? "hover" : "always";
    if (toolbar.placement === "input-top") {
      style["--chat-dialog-toolbar-input-clearance"] = "12px";
      style["--chat-dialog-toolbar-layer-padding"] = "20px 0 0";
      style["--chat-dialog-toolbar-layer-width"] = "min(var(--chat-ui-runtime-width), calc(100vw - 32px))";
      style["--chat-dialog-toolbar-layer-max-width"] = "calc(100vw - 32px)";
      style["--chat-dialog-toolbar-hidden-y"] = "16px";
      if (input?.layout === "pill") {
        style["--chat-dialog-toolbar-input-clearance"] = "4px";
        style["--chat-dialog-toolbar-layer-width"] = "min(var(--chat-input-max-width), calc(100vw - 32px))";
      }
      if (typeof dialog?.nameInputGapVh === "number") {
        style["--chat-dialog-stack-bottom"] =
          "calc(var(--stage-control-stack-height) + var(--chat-dialog-name-input-gap) + clamp(34px, 4.2svh, 46px) - var(--chat-dialog-height) - var(--chat-name-line-offset) - var(--chat-dialog-offset-y))";
      }
    }
  }
  applyVisualBlock(style, "send", tokens.send, assetUrl);
  applyVisualBlock(style, "name", tokens.name, assetUrl);
  if (isSafeCssValue(tokens.name?.color)) {
    style["--chat-name-theme-color"] = tokens.name.color.trim();
  }
  if (typeof tokens.name?.fontFamily === "string") {
    const fontFamily = quotedFontFamily(tokens.name.fontFamily);
    if (fontFamily) {
      style["--chat-name-theme-font-family"] = fontFamily;
    }
  }
  setPxVar(style, "--chat-name-theme-font-size", tokens.name?.textSizePx, 15, 12, 56);
  setIntegerVar(style, "--chat-name-theme-font-weight", tokens.name?.textWeight, 800, 300, 900);
  setStyleVar(style, "--chat-name-text-shadow", tokens.name?.textShadow);
  if (tokens.name?.align === "center") {
    style["--chat-name-justify-content"] = "center";
    style["--chat-name-left"] = "50%";
    style["--chat-name-text-align"] = "center";
    style["--chat-name-transform"] = "translateX(-50%)";
  }
  if (tokens.name?.decoration === "line-dots") {
    style["--chat-name-after-background"] =
      "radial-gradient(circle, currentColor 0 42%, transparent 45%) left 50% / 0.5em 0.5em no-repeat, linear-gradient(currentColor 0 0) right 50% / calc(100% - 0.66em) 2px no-repeat";
    style["--chat-name-after-content"] = '""';
    style["--chat-name-after-display"] = "block";
    style["--chat-name-after-height"] = "0.72em";
    style["--chat-name-after-margin"] = "0 0 0 0.46em";
    style["--chat-name-after-width"] = "3.2em";
    style["--chat-name-before-background"] =
      "linear-gradient(currentColor 0 0) left 50% / calc(100% - 0.66em) 2px no-repeat, radial-gradient(circle, currentColor 0 42%, transparent 45%) right 50% / 0.5em 0.5em no-repeat";
    style["--chat-name-before-content"] = '""';
    style["--chat-name-before-display"] = "block";
    style["--chat-name-before-height"] = "0.72em";
    style["--chat-name-before-margin"] = "0 0.46em 0 0";
    style["--chat-name-before-position"] = "static";
    style["--chat-name-before-width"] = "3.2em";
    style["--chat-name-border"] = "0 solid transparent";
    style["--chat-name-border-bottom"] = "0 solid transparent";
    style["--chat-name-decoration-color"] = "var(--chat-name-runtime-color, var(--chat-name-color))";
    style["--chat-name-sheen"] = "none";
  }
  if (tokens.name?.hideWhenStartOption === true) {
    style["--chat-name-hide-when-start-option"] = "true";
  }

  const logs = resolveLogsThemeTokens(tokens);
  applyLogsVisualBlock(style, "page", logs?.page, assetUrl);
  applyLogsVisualBlock(style, "panel", logs?.panel, assetUrl);
  applyLogsVisualBlock(style, "toolbar", logs?.toolbar, assetUrl);
  applyLogsVisualBlock(style, "sidebar", logs?.sidebar, assetUrl);
  applyLogsVisualBlock(style, "source", logs?.source, assetUrl);
  applyLogsVisualBlock(style, "viewer", logs?.viewer, assetUrl);
  applyLogsVisualBlock(style, "code", logs?.code, assetUrl);
  applyLogsVisualBlock(style, "line", logs?.line, assetUrl);
  applyLogsVisualBlock(style, "line-hover", logs?.line?.hover, assetUrl);
  applyLogsVisualBlock(style, "line-expanded", logs?.line?.expanded, assetUrl);
  applyLogsVisualBlock(style, "number", logs?.number, assetUrl);
  applyLogsVisualBlock(style, "detail", logs?.detail, assetUrl);
  applyLogsVisualBlock(style, "badge", logs?.badge, assetUrl);
  applyLogsVisualBlock(style, "event", logs?.event, assetUrl);
  applyLogsVisualBlock(style, "file", logs?.fileItem, assetUrl);
  applyLogsVisualBlock(style, "file-hover", logs?.fileItem?.hover, assetUrl);
  applyLogsVisualBlock(style, "file-active", logs?.fileItem?.active, assetUrl);
  if (typeof logs?.code?.fontFamily === "string") {
    const fontFamily = quotedFontFamily(logs.code.fontFamily);
    if (fontFamily) {
      style["--logs-code-font-family"] = fontFamily;
    }
  }
  for (const level of ["debug", "default", "error", "info", "warn"] as const) {
    applyLogsVisualBlock(style, `level-${level}`, logs?.levels?.[level], assetUrl);
  }

  const fontFaces = (tokens.fonts ?? [])
    .map((font) => {
      const family = typeof font.family === "string" ? quotedFontFamily(font.family) : "";
      const src = resolveThemeAssetUrl(font.src, assetUrl);
      if (!family || !src) {
        return "";
      }
      const declarations = [`font-family: ${family};`, `src: url("${src}");`, `font-display: swap;`];
      if (isSafeCssValue(font.weight)) {
        declarations.push(`font-weight: ${font.weight.trim()};`);
      }
      if (isSafeCssValue(font.style)) {
        declarations.push(`font-style: ${font.style.trim()};`);
      }
      return `@font-face { ${declarations.join(" ")} }`;
    })
    .filter(Boolean)
    .join("\n");

  const typewriter = {
    cps: clampNumber(tokens.typewriter?.cps, DEFAULT_TYPEWRITER_CPS, 1, 200),
    soundUrl: resolveThemeAssetUrl(tokens.typewriter?.sound, assetUrl) || undefined,
  };

  return { style, fontFaces, typewriter };
}

/** 选择 manifest 名称的本地化文本，缺失时回退 id。 */
export function chatThemeDisplayName(
  theme: Pick<ChatThemeManifest, "id" | "name"> | ChatThemeSummary,
  language: string,
): string {
  return theme.name?.[language] ?? theme.name?.zh_CN ?? theme.name?.en ?? theme.id;
}
