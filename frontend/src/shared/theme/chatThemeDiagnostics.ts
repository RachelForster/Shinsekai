import type { ChatThemeAsset, ChatThemeManifest, VisualBlock } from "./chatTheme";

export type ChatThemeDiagnosticCode = "contrast" | "missing-asset" | "viewport-overflow";

export interface ChatThemeDiagnostic {
  code: ChatThemeDiagnosticCode;
  detail: string;
  section: string;
}

interface RgbaColor {
  a: number;
  b: number;
  g: number;
  r: number;
}

function parseHexPair(value: string) {
  return Number.parseInt(value, 16);
}

function parseCssColor(value?: string): RgbaColor | undefined {
  if (!value) {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  const hex = normalized.match(/^#([0-9a-f]{3,8})$/i)?.[1];
  if (hex) {
    if (hex.length === 3 || hex.length === 4) {
      return {
        r: parseHexPair(hex[0] + hex[0]),
        g: parseHexPair(hex[1] + hex[1]),
        b: parseHexPair(hex[2] + hex[2]),
        a: hex.length === 4 ? parseHexPair(hex[3] + hex[3]) / 255 : 1,
      };
    }
    if (hex.length === 6 || hex.length === 8) {
      return {
        r: parseHexPair(hex.slice(0, 2)),
        g: parseHexPair(hex.slice(2, 4)),
        b: parseHexPair(hex.slice(4, 6)),
        a: hex.length === 8 ? parseHexPair(hex.slice(6, 8)) / 255 : 1,
      };
    }
  }

  const rgb = normalized.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+)%?)?\s*\)$/);
  if (!rgb) {
    return undefined;
  }
  const alpha = rgb[4] === undefined ? 1 : Number(rgb[4]);
  return {
    r: Math.min(255, Number(rgb[1])),
    g: Math.min(255, Number(rgb[2])),
    b: Math.min(255, Number(rgb[3])),
    a: Math.min(1, Math.max(0, alpha)),
  };
}

function composite(color: RgbaColor, background: RgbaColor): RgbaColor {
  return {
    r: color.r * color.a + background.r * (1 - color.a),
    g: color.g * color.a + background.g * (1 - color.a),
    b: color.b * color.a + background.b * (1 - color.a),
    a: 1,
  };
}

function luminance(color: RgbaColor) {
  const channel = (value: number) => {
    const srgb = value / 255;
    return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  };
  return channel(color.r) * 0.2126 + channel(color.g) * 0.7152 + channel(color.b) * 0.0722;
}

function contrastRatio(foreground: RgbaColor, background: RgbaColor) {
  const canvas = { r: 9, g: 12, b: 22, a: 1 };
  const bg = composite(background, canvas);
  const fg = composite(foreground, bg);
  const lighter = Math.max(luminance(fg), luminance(bg));
  const darker = Math.min(luminance(fg), luminance(bg));
  return (lighter + 0.05) / (darker + 0.05);
}

function assetReferences(manifest: ChatThemeManifest) {
  const references = new Set<string>();
  if (manifest.preview) {
    references.add(manifest.preview);
  }
  const visit = (value: unknown, key = "") => {
    if (typeof value === "string" && ["backgroundImage", "frameImage", "sound", "src"].includes(key)) {
      references.add(value);
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item) => visit(item));
      return;
    }
    if (value && typeof value === "object") {
      Object.entries(value).forEach(([childKey, child]) => visit(child, childKey));
    }
  };
  visit(manifest.tokens);
  return [...references].filter(Boolean);
}

export function diagnoseChatTheme(
  manifest: ChatThemeManifest,
  assets?: Pick<ChatThemeAsset, "path">[],
): ChatThemeDiagnostic[] {
  const diagnostics: ChatThemeDiagnostic[] = [];
  const blocks: Array<[string, VisualBlock | undefined]> = [
    ["dialog", manifest.tokens.dialog],
    ["options", manifest.tokens.options],
    ["options.hover", manifest.tokens.options?.hover],
    ["options.active", manifest.tokens.options?.active],
    ["input", manifest.tokens.input],
    ["toolbar", manifest.tokens.toolbar],
    ["send", manifest.tokens.send],
    ["name", manifest.tokens.name],
    ["logs.panel", manifest.tokens.logs?.panel],
    ["logs.viewer", manifest.tokens.logs?.viewer],
    ["logs.code", manifest.tokens.logs?.code],
  ];

  blocks.forEach(([section, block]) => {
    const foreground = parseCssColor(block?.color);
    const background = parseCssColor(block?.background);
    if (!foreground || !background) {
      return;
    }
    const ratio = contrastRatio(foreground, background);
    if (ratio < 4.5) {
      diagnostics.push({ code: "contrast", detail: `${ratio.toFixed(2)}:1`, section });
    }
  });

  if (assets) {
    const availableAssets = new Set(assets.map((asset) => asset.path.replace(/\\/g, "/")));
    assetReferences(manifest).forEach((path) => {
      const normalized = path.replace(/\\/g, "/");
      if (!availableAssets.has(normalized)) {
        diagnostics.push({ code: "missing-asset", detail: normalized, section: "assets" });
      }
    });
  }

  if ((manifest.tokens.options?.widthPx ?? 0) > 680 || (manifest.tokens.dialog?.widthPct ?? 0) > 96) {
    diagnostics.push({
      code: "viewport-overflow",
      detail: "mobile",
      section: (manifest.tokens.options?.widthPx ?? 0) > 680 ? "options" : "dialog",
    });
  }

  return diagnostics;
}
