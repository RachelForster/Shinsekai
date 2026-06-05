import type { CSSProperties } from "react";

export interface ChatThemePayload {
  raw: unknown;
  themeColor: string;
}

export type ChatStageStyle = CSSProperties & Record<`--${string}`, string>;

interface ThemeBlock {
  extra_qss?: unknown;
  hover_extra_qss?: unknown;
}

const forbiddenDecl =
  /^(width|height|min-width|max-width|min-height|max-height|min-size|max-size|position|left|right|top|bottom|font-size)\s*:/i;

const visualVarMap: Record<string, string> = {
  background: "background",
  "background-color": "background",
  border: "border",
  "border-color": "border-color",
  "border-radius": "border-radius",
  "box-shadow": "box-shadow",
  color: "color",
  opacity: "opacity",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function clampNumber(value: unknown, fallback: number, min: number, max: number) {
  const next = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(next)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, next));
}

function normalizeCssColor(value: string) {
  const match = value.trim().match(/^rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*([0-9.]+)\s*\)$/i);
  if (!match) {
    return value.trim();
  }
  const alpha = Number(match[4]);
  const cssAlpha = alpha > 1 ? Math.min(1, Math.max(0, alpha / 255)) : alpha;
  return `rgba(${match[1]}, ${match[2]}, ${match[3]}, ${Number(cssAlpha.toFixed(3))})`;
}

function readExtra(raw: Record<string, unknown>, key: string, field: keyof ThemeBlock = "extra_qss") {
  const block = raw[key];
  if (!block || typeof block !== "object" || Array.isArray(block)) {
    return "";
  }
  const value = (block as ThemeBlock)[field];
  return typeof value === "string" ? value : "";
}

function isAllowedValue(property: string, value: string) {
  if (!value.trim()) {
    return false;
  }
  if (property === "background" && /url\s*\(/i.test(value)) {
    return false;
  }
  return !/[{}]/.test(value);
}

function applyVisualDeclarations(style: ChatStageStyle, prefix: string, fragment: string) {
  for (const raw of fragment.split(";")) {
    const declaration = raw.trim();
    if (!declaration || forbiddenDecl.test(declaration)) {
      continue;
    }
    const separator = declaration.indexOf(":");
    if (separator <= 0) {
      continue;
    }
    const property = declaration.slice(0, separator).trim().toLowerCase();
    const value = declaration.slice(separator + 1).trim();
    const target = visualVarMap[property];
    if (!target || !isAllowedValue(property, value)) {
      continue;
    }
    const normalized = property.includes("color") ? normalizeCssColor(value) : value;
    style[`--chat-${prefix}-${target}`] = normalized;
  }
}

export function parseChatChromeTheme(payload?: ChatThemePayload | null): ChatStageStyle {
  const raw = asRecord(payload?.raw);
  const style: ChatStageStyle = {
    "--chat-dialog-offset-y": `${clampNumber(raw.dialog_offset_y, 0, -240, 240)}px`,
    "--chat-dialog-padding": `${clampNumber(raw.dialog_padding, 40, 8, 72)}px`,
    "--chat-dialog-width": `min(${clampNumber(raw.dialog_width_pct, 86, 30, 100)}vw, 980px)`,
    "--chat-options-gap": `${clampNumber(raw.options_gap, 10, 0, 36)}px`,
  };

  if (payload?.themeColor) {
    style["--chat-theme-color"] = normalizeCssColor(payload.themeColor);
  }

  applyVisualDeclarations(style, "dialog", readExtra(raw, "dialog_label"));
  applyVisualDeclarations(style, "input", readExtra(raw, "input_bar"));
  applyVisualDeclarations(style, "toolbar", readExtra(raw, "busy_bar_label"));
  applyVisualDeclarations(style, "option", readExtra(raw, "option_row"));
  applyVisualDeclarations(style, "option-hover", readExtra(raw, "option_row", "hover_extra_qss"));
  applyVisualDeclarations(style, "options", readExtra(raw, "options_container"));
  applyVisualDeclarations(style, "send", readExtra(raw, "send_button"));

  return style;
}
