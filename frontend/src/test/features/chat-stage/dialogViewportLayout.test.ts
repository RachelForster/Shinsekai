import { describe, expect, it } from "vitest";

import {
  resolveVnDialogViewportStyle,
  shouldApplyVnDialogAdaptation,
  VN_SCALE_MAX,
  VN_STAGE_MAX_ASPECT,
} from "../../../features/chat-stage/dialogViewportLayout";
import { chatStageRuntimeStyle, defaultChatStageRuntimeConfig } from "../../../features/chat-stage/runtimeConfig";
import { builtinChatThemeManifests } from "../../../shared/theme/builtinChatThemes";
import { resolveChatTheme } from "../../../shared/theme/chatTheme";

describe("dialogViewportLayout", () => {
  it("stays inactive for standard windowed and narrow mobile viewports", () => {
    expect(shouldApplyVnDialogAdaptation(null)).toBe(false);
    expect(shouldApplyVnDialogAdaptation({ expanded: false, height: 768, width: 1024 })).toBe(false);
    expect(shouldApplyVnDialogAdaptation({ expanded: false, height: 820, width: 1280 })).toBe(false);
    expect(shouldApplyVnDialogAdaptation({ expanded: true, height: 600, width: 800 })).toBe(false);
    expect(shouldApplyVnDialogAdaptation({ expanded: true, height: 1200, width: 860 })).toBe(false);

    expect(
      resolveVnDialogViewportStyle({
        config: defaultChatStageRuntimeConfig,
        defaultConfig: defaultChatStageRuntimeConfig,
        dialogComposedScale: 1,
        themeStyle: {},
        viewport: { expanded: false, height: 820, width: 1280 },
      }),
    ).toEqual({});
  });

  it("scales dialog box proportions cleanly for 1080p, 2K, 4K, ultrawide, and 150% DPI laptop fullscreen", () => {
    const maximized1080p = resolveVnDialogViewportStyle({
      config: defaultChatStageRuntimeConfig,
      defaultConfig: defaultChatStageRuntimeConfig,
      dialogComposedScale: 1,
      themeStyle: {},
      viewport: { expanded: true, height: 1040, width: 1920 },
    });
    expect(maximized1080p["--chat-dialog-runtime-width"]).toBe("1651px");
    expect(maximized1080p["--chat-dialog-min-height"]).toBe("208px");
    expect(maximized1080p["--chat-dialog-body-max-height"]).toBe("312px");
    expect(maximized1080p["--chat-dialog-text-runtime-font-size"]).toBe("23px");
    expect(maximized1080p["--chat-option-font-size"]).toBe("22px");
    expect(maximized1080p["--chat-option-min-height"]).toBe("61px");
    expect(maximized1080p["--chat-options-gap"]).toBe("13px");

    const fullscreen1080p = resolveVnDialogViewportStyle({
      config: defaultChatStageRuntimeConfig,
      defaultConfig: defaultChatStageRuntimeConfig,
      dialogComposedScale: 1,
      themeStyle: {},
      viewport: { expanded: true, height: 1080, width: 1920 },
    });
    expect(fullscreen1080p["--chat-dialog-runtime-width"]).toBe("1651px");
    expect(fullscreen1080p["--chat-dialog-min-height"]).toBe("216px");
    expect(fullscreen1080p["--chat-dialog-body-max-height"]).toBe("324px");
    expect(fullscreen1080p["--chat-dialog-text-runtime-font-size"]).toBe("24px");
    expect(fullscreen1080p["--chat-option-font-size"]).toBe("22px");
    expect(fullscreen1080p["--chat-option-min-height"]).toBe("63px");
    expect(fullscreen1080p["--chat-option-padding"]).toBe("16px 29px");
    expect(fullscreen1080p["--chat-options-gap"]).toBe("13px");

    const qhd2k = resolveVnDialogViewportStyle({
      config: defaultChatStageRuntimeConfig,
      defaultConfig: defaultChatStageRuntimeConfig,
      dialogComposedScale: 1,
      themeStyle: {},
      viewport: { expanded: true, height: 1440, width: 2560 },
    });
    expect(qhd2k["--chat-dialog-runtime-width"]).toBe("2202px");
    expect(qhd2k["--chat-dialog-min-height"]).toBe("288px");
    expect(qhd2k["--chat-dialog-body-max-height"]).toBe("432px");
    expect(qhd2k["--chat-dialog-text-runtime-font-size"]).toBe("32px");
    expect(qhd2k["--chat-option-font-size"]).toBe("30px");
    expect(qhd2k["--chat-option-min-height"]).toBe("84px");
    expect(qhd2k["--chat-options-gap"]).toBe("18px");

    const uhd4k = resolveVnDialogViewportStyle({
      config: defaultChatStageRuntimeConfig,
      defaultConfig: defaultChatStageRuntimeConfig,
      dialogComposedScale: 1,
      themeStyle: {},
      viewport: { expanded: true, height: 2160, width: 3840 },
    });
    expect(uhd4k["--chat-dialog-runtime-width"]).toBe("3302px");
    expect(uhd4k["--chat-dialog-min-height"]).toBe("320px");
    expect(uhd4k["--chat-dialog-body-max-height"]).toBe("460px");
    expect(uhd4k["--chat-dialog-text-runtime-font-size"]).toBe(`${Math.round(18 * VN_SCALE_MAX)}px`);
    expect(uhd4k["--chat-name-runtime-font-size"]).toBe(`${Math.round(16 * VN_SCALE_MAX)}px`);
    expect(uhd4k["--chat-option-font-size"]).toBe("31px");
    expect(uhd4k["--chat-option-min-height"]).toBe("89px");
    expect(uhd4k["--chat-options-gap"]).toBe("19px");

    const ultrawide = resolveVnDialogViewportStyle({
      config: defaultChatStageRuntimeConfig,
      defaultConfig: defaultChatStageRuntimeConfig,
      dialogComposedScale: 1,
      themeStyle: {},
      viewport: { expanded: true, height: 1440, width: 3440 },
    });
    const expectedUltrawide = `${Math.round((1440 * VN_STAGE_MAX_ASPECT * 86) / 100)}px`;
    expect(ultrawide["--chat-dialog-runtime-width"]).toBe(expectedUltrawide);

    const laptop150Dpi = resolveVnDialogViewportStyle({
      config: defaultChatStageRuntimeConfig,
      defaultConfig: defaultChatStageRuntimeConfig,
      dialogComposedScale: 1,
      themeStyle: {},
      viewport: { expanded: true, height: 720, width: 1280 },
    });
    expect(laptop150Dpi["--chat-dialog-runtime-width"]).toBe("1101px");
    expect(laptop150Dpi["--chat-dialog-min-height"]).toBe("156px");
    expect(laptop150Dpi["--chat-dialog-body-max-height"]).toBe("260px");
    expect(laptop150Dpi["--chat-option-font-size"]).toBe("17px");
    expect(laptop150Dpi["--chat-option-min-height"]).toBe("48px");
    expect(laptop150Dpi["--chat-options-gap"]).toBe("10px");
  });

  it("adapts built-in visual-novel themes cleanly beyond the 980px theme cap", () => {
    const cases = [
      { id: "sakura-dream", expectedWidth: 1651, baseHeight: 178, expectedOptionFont: 24, expectedOptionMinHeight: 71 },
      {
        id: "spiritron-command",
        expectedWidth: 1805,
        baseHeight: 180,
        expectedOptionFont: 24,
        expectedOptionMinHeight: 68,
      },
      {
        id: "raging-loop-simple",
        expectedWidth: 1920,
        baseHeight: 226,
        expectedOptionFont: 24,
        expectedOptionMinHeight: 60,
      },
      {
        id: "windborne-adventure",
        expectedWidth: 1382,
        baseHeight: 166,
        expectedOptionFont: 24,
        expectedOptionMinHeight: 60,
      },
      {
        id: "neon-night-city",
        expectedWidth: 1613,
        baseHeight: 184,
        expectedOptionFont: 24,
        expectedOptionMinHeight: 66,
      },
    ] as const;

    for (const item of cases) {
      const resolved = resolveChatTheme(builtinChatThemeManifests[item.id], (rel) => rel);
      const style = chatStageRuntimeStyle(defaultChatStageRuntimeConfig, resolved.style, "#d4788e", {
        expanded: true,
        height: 1080,
        width: 1920,
      }) as unknown as Record<string, string>;

      expect(style["--chat-dialog-width"]).toBe(`${item.expectedWidth}px`);
      expect(style["--chat-dialog-runtime-width"]).toBe(`${item.expectedWidth}px`);
      expect(style["--chat-option-font-size"]).toBe(`${item.expectedOptionFont}px`);
      expect(style["--chat-option-min-height"]).toBe(`${item.expectedOptionMinHeight}px`);

      const scaledHeight = Number.parseInt(style["--chat-dialog-height"], 10);
      expect(scaledHeight).toBeGreaterThan(item.baseHeight);
      expect(scaledHeight).toBeLessThanOrEqual(Math.round(1080 * 0.34));

      const gapPx = Number.parseInt(style["--chat-dialog-name-input-gap"], 10);
      expect(gapPx).toBeGreaterThan(scaledHeight);
    }

    const windborneTheme = resolveChatTheme(builtinChatThemeManifests["windborne-adventure"], (rel) => rel);
    const windborneStyle = chatStageRuntimeStyle(defaultChatStageRuntimeConfig, windborneTheme.style, "#f3cf57", {
      expanded: true,
      height: 1080,
      width: 1920,
    }) as unknown as Record<string, string>;
    expect(windborneStyle["--chat-option-icon-size"]).toBe("41px");
    expect(windborneStyle["--chat-option-padding"]).toBe("11px 24px 11px 71px");

    const ragingTheme = resolveChatTheme(builtinChatThemeManifests["raging-loop-simple"], (rel) => rel);
    const ultrawideFullBleed = chatStageRuntimeStyle(defaultChatStageRuntimeConfig, ragingTheme.style, "#62c3ff", {
      expanded: true,
      height: 1440,
      width: 3440,
    }) as unknown as Record<string, string>;
    expect(ultrawideFullBleed["--chat-dialog-width"]).toBe("3440px");
  });

  it("respects explicit user overrides for dialogWidthPct, font sizes, and composed scales", () => {
    const customized = chatStageRuntimeStyle(
      {
        ...defaultChatStageRuntimeConfig,
        dialogText: { ...defaultChatStageRuntimeConfig.dialogText, fontSize: 28 },
        dialogWidthPct: 60,
        nameText: { ...defaultChatStageRuntimeConfig.nameText, fontSize: 24 },
      },
      {},
      "#d4788e",
      { expanded: true, height: 1080, width: 1920 },
    ) as unknown as Record<string, string>;

    expect(customized["--chat-dialog-width"]).toBe("60vw");
    expect(customized["--chat-dialog-runtime-width"]).toBe("60vw");
    expect(customized["--chat-dialog-text-runtime-font-size"]).toBe("28px");
    expect(customized["--chat-name-runtime-font-size"]).toBe("24px");
    expect(customized["--chat-dialog-min-height"]).toBe("216px");

    const scaled = chatStageRuntimeStyle(
      {
        ...defaultChatStageRuntimeConfig,
        dialogScale: 1.2,
        windowScale: 1.2,
      },
      {},
      "#d4788e",
      { expanded: true, height: 1080, width: 1920 },
    ) as unknown as Record<string, string>;

    const maxLayoutForScale = Math.floor((1920 - 40) / 1.44);
    expect(scaled["--chat-dialog-composed-scale"]).toBe("1.44");
    expect(scaled["--chat-dialog-runtime-width"]).toBe(`${maxLayoutForScale}px`);
    expect(Number.parseInt(scaled["--chat-dialog-runtime-width"], 10) * 1.44).toBeLessThanOrEqual(1880);
  });
});
