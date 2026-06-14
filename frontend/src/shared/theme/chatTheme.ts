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
    /** 对话框宽度占比（vw），clamp 30–100。 */
    widthPct?: number;
    /** 垂直偏移（px），clamp -240–240。 */
    offsetY?: number;
  };
  options?: VisualBlock & { gap?: number; hover?: VisualBlock };
  input?: VisualBlock & { fieldBackground?: string };
  toolbar?: VisualBlock;
  send?: VisualBlock;
  name?: VisualBlock;
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
  if (typeof dialog?.widthPct === "number") {
    style["--chat-dialog-width"] = `min(${clampNumber(dialog.widthPct, 86, 30, 100)}vw, 980px)`;
  }
  if (typeof dialog?.offsetY === "number") {
    style["--chat-dialog-offset-y"] = `${clampNumber(dialog.offsetY, 0, -240, 240)}px`;
  }

  const options = tokens.options;
  applyVisualBlock(style, "option", options, assetUrl);
  applyVisualBlock(style, "option-hover", options?.hover, assetUrl);
  if (isSafeCssValue(options?.color)) {
    style["--chat-options-color"] = options.color;
  }
  if (typeof options?.gap === "number") {
    style["--chat-options-gap"] = `${clampNumber(options.gap, 10, 0, 36)}px`;
  }

  const input = tokens.input;
  applyVisualBlock(style, "input", input, assetUrl);
  if (isSafeCssValue(input?.fieldBackground)) {
    style["--chat-input-field-background"] = input.fieldBackground;
  }

  applyVisualBlock(style, "toolbar", tokens.toolbar, assetUrl);
  applyVisualBlock(style, "send", tokens.send, assetUrl);
  applyVisualBlock(style, "name", tokens.name, assetUrl);

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
