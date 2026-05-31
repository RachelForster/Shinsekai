export const DEFAULT_THEME_COLOR = "#d4788e";

const HEX_COLOR_RE = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;
const RGB_COLOR_RE = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*[\d.]+)?\s*\)$/i;

function toTwoDigitHex(value: number) {
  return Math.max(0, Math.min(255, value)).toString(16).padStart(2, "0");
}

export function normalizeThemeColor(color: string | null | undefined) {
  const value = String(color ?? "").trim();
  if (!value) {
    return DEFAULT_THEME_COLOR;
  }

  const hexMatch = value.match(HEX_COLOR_RE);
  if (hexMatch) {
    const hex = hexMatch[1];
    if (hex.length === 3) {
      return `#${hex[0]}${hex[0]}${hex[1]}${hex[1]}${hex[2]}${hex[2]}`.toLowerCase();
    }
    return `#${hex}`.toLowerCase();
  }

  const rgbMatch = value.match(RGB_COLOR_RE);
  if (rgbMatch) {
    const channels = rgbMatch.slice(1, 4).map((channel) => Number.parseInt(channel, 10));
    if (channels.every((channel) => Number.isFinite(channel) && channel >= 0 && channel <= 255)) {
      return `#${channels.map(toTwoDigitHex).join("")}`;
    }
  }

  return DEFAULT_THEME_COLOR;
}

export function applyThemeColor(color: string | null | undefined) {
  document.documentElement.style.setProperty("--theme-accent", normalizeThemeColor(color));
}
