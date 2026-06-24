import { describe, expect, it } from "vitest";

import { DEFAULT_THEME_COLOR, normalizeThemeColor } from "../../../shared/theme/appTheme";

describe("normalizeThemeColor", () => {
  it("keeps full hex colors", () => {
    expect(normalizeThemeColor("#D4788E")).toBe("#d4788e");
  });

  it("expands short hex colors", () => {
    expect(normalizeThemeColor("#abc")).toBe("#aabbcc");
  });

  it("converts rgb colors to hex", () => {
    expect(normalizeThemeColor("rgba(50,50,50,200)")).toBe("#323232");
  });

  it("falls back for invalid colors", () => {
    expect(normalizeThemeColor("not-a-color")).toBe(DEFAULT_THEME_COLOR);
  });
});
