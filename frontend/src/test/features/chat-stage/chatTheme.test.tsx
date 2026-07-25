import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../../../shared/i18n";
import { ToastProvider } from "../../../shared/ui";
const repoMocks = vi.hoisted(() => ({
  deleteChatTheme: vi.fn(),
  getActiveChatThemeId: vi.fn(),
  getChatTheme: vi.fn(),
  getChatThemeManifest: vi.fn(),
  listChatThemes: vi.fn(),
  setActiveChatTheme: vi.fn(),
  uploadChatTheme: vi.fn(),
}));

const platformMocks = vi.hoisted(() => ({
  getPlatform: vi.fn(),
}));

vi.mock("../../../entities/chat/repository", () => ({
  deleteChatTheme: (id: string) => repoMocks.deleteChatTheme(id),
  getActiveChatThemeId: () => repoMocks.getActiveChatThemeId(),
  getChatTheme: () => repoMocks.getChatTheme(),
  getChatThemeManifest: (id: string) => repoMocks.getChatThemeManifest(id),
  listChatThemes: () => repoMocks.listChatThemes(),
  setActiveChatTheme: (id: string) => repoMocks.setActiveChatTheme(id),
  uploadChatTheme: (file: File) => repoMocks.uploadChatTheme(file),
}));

vi.mock("../../../shared/platform/platform", () => ({
  getPlatform: () => platformMocks.getPlatform(),
}));

import { ChatThemeProvider, useChatTheme } from "../../../features/chat-stage/theme/ChatThemeProvider";
import { ChatThemePicker } from "../../../features/chat-stage/theme/ChatThemePicker";
import {
  chatStageRuntimeConfigVersion,
  defaultChatStageRuntimeConfig,
} from "../../../features/chat-stage/runtimeConfig";
import { resolveChatTheme, type ChatThemeManifest } from "../../../shared/theme/chatTheme";

function Probe() {
  const theme = useChatTheme();
  return (
    <div
      data-active={theme.activeId ?? ""}
      data-cps={String(theme.resolved?.typewriter.cps ?? "")}
      data-gap={theme.style["--chat-options-gap"] ?? ""}
      data-logs-code={theme.style["--logs-code-background"] ?? ""}
      data-theme-count={String(theme.themes.length)}
      data-testid="theme-probe"
      data-theme-color={theme.style["--chat-theme-color"] ?? ""}
    />
  );
}

function renderThemeTree(children: React.ReactNode) {
  return render(
    <ToastProvider>
      <I18nProvider language="en">
        <ChatThemeProvider>{children}</ChatThemeProvider>
      </I18nProvider>
    </ToastProvider>,
  );
}

describe("chat theme runtime", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
    document.documentElement.removeAttribute("style");
    document.getElementById("shinsekai-chat-theme-fonts")?.remove();
    platformMocks.getPlatform.mockReturnValue({
      files: {
        fileUrl: (path: string) => `asset://${path}`,
      },
    });
  });

  afterEach(() => {
    document.documentElement.removeAttribute("style");
    document.getElementById("shinsekai-chat-theme-fonts")?.remove();
    window.localStorage.removeItem("shinsekai-chat-stage-runtime-config");
  });

  it("maps manifest tokens into chat stage CSS variables and font faces", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "token-rich-theme",
        name: { en: "Token Rich Theme" },
        tokens: {
          global: { fontFamily: "Mio Sans", themeColor: "#644ae3" },
          fonts: [{ family: "Mio Sans", src: "assets/fonts/mio.woff2", style: "normal", weight: "400" }],
          dialog: {
            background: "rgba(20,20,28,0.86)",
            backgroundImage: "assets/dialog-frame.png",
            borderColor: "rgba(255,255,255,0.32)",
            borderRadius: "8px",
            boxShadow: "0 16px 44px rgba(0,0,0,0.5)",
            chrome: "none",
            color: "#ffffff",
            frameImage: "assets/dialog-border.svg",
            frameSlice: 28,
            heightPx: 166,
            nameInputGapVh: 20,
            offsetY: -8,
            padding: 40,
            textAlign: "center",
            textShadow: "0 2px 4px rgba(0,0,0,0.7)",
            textSizePx: 34,
            textWeight: 800,
            widthPct: 86,
          },
          input: {
            background: "rgba(34,34,40,0.9)",
            borderColor: "rgba(255,255,255,0.22)",
            color: "#ffffff",
            fieldBackground: "rgba(50,50,50,0.78)",
            fieldBorderRadius: "12px",
            maxWidthPx: 720,
            sendPlacement: "inside",
          },
          name: {
            background: "rgba(28,22,48,0.92)",
            backgroundImage: "assets/name-plate.png",
            borderColor: "rgba(156,140,255,0.6)",
            borderRadius: "6px",
            boxShadow: "0 12px 28px rgba(0,0,0,0.36)",
            color: "#9c8cff",
            frameImage: "assets/name-border.svg",
            frameSlice: 16,
            align: "center",
            decoration: "line-dots",
            fontFamily: "Trebuchet MS, Georgia, serif",
            overlapPx: 14,
            textShadow: "0 2px 4px rgba(0,0,0,0.7)",
            hideWhenStartOption: true,
            textSizePx: 30,
            textWeight: 800,
          },
          options: {
            background: "rgba(50,50,50,0.68)",
            color: "#ffffff",
            gap: 10,
            active: { background: "#f3cf57", color: "#1d2630" },
            icon: "chat",
            maxWidthVw: 40,
            minHeightPx: 68,
            minHeightVh: 5.2,
            minWidthVw: 26,
            nameClearanceVh: 5.6,
            placement: "right",
            textShadow: "0 2px 4px rgba(0,0,0,0.7)",
            textSizeVh: 1.6,
            textSizePx: 30,
            textWeight: 800,
            widthPx: 620,
            widthMode: "content",
            hover: { background: "rgba(70,70,70,0.74)" },
          },
          send: { background: "#644ae3", color: "#ffffff" },
          toolbar: {
            background: "rgba(34,34,40,0.9)",
            color: "#ffffff",
            placement: "dialog-top",
            reveal: "hover",
          },
          logs: {
            badge: { background: "rgba(255,255,255,0.06)", color: "#c8c2df" },
            code: {
              background: "rgba(8,9,14,0.9)",
              backgroundImage: "assets/log-code.png",
              color: "#f3f0ff",
              fontFamily: "JetBrains Mono, ui-monospace, monospace",
            },
            event: { background: "rgba(100,74,227,0.16)", color: "#cfc7ff" },
            fileItem: {
              background: "rgba(255,255,255,0.03)",
              active: { background: "rgba(100,74,227,0.18)" },
              hover: { background: "rgba(255,255,255,0.07)" },
            },
            levels: {
              error: { background: "rgba(255,95,109,0.14)", color: "#ff9ca7" },
              debug: { borderColor: "rgba(91,173,255,0.34)" },
            },
            line: {
              borderColor: "rgba(255,255,255,0.08)",
              expanded: { background: "rgba(100,74,227,0.15)" },
              hover: { background: "rgba(100,74,227,0.1)" },
            },
            panel: { background: "rgba(20,20,28,0.78)", backgroundImage: "assets/log-panel.png", borderRadius: "8px" },
          },
          typewriter: { cps: 240, sound: "assets/sfx/type.wav" },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-theme-color"]).toBe("#644ae3");
    expect(resolved.style["--font-chat"]).toBe('"Mio Sans"');
    expect(resolved.style["--chat-dialog-background"]).toBe("rgba(20,20,28,0.86)");
    expect(resolved.style["--chat-dialog-background-image"]).toBe('url("asset://assets/dialog-frame.png")');
    expect(resolved.style["--chat-dialog-background-slice"]).toBe("28");
    expect(resolved.style["--chat-dialog-background-width"]).toBe("28px");
    expect(resolved.style["--chat-dialog-background-outset"]).toBe("0px");
    expect(resolved.style["--chat-dialog-backdrop-filter"]).toBe("none");
    expect(resolved.style["--chat-dialog-actions-border"]).toBe("0 solid transparent");
    expect(resolved.style["--chat-dialog-border"]).toBe("0 solid transparent");
    expect(resolved.style["--chat-dialog-body-height"]).toBe("100%");
    expect(resolved.style["--chat-dialog-body-min-height"]).toBe("0px");
    expect(resolved.style["--chat-dialog-body-overflow"]).toBe("auto");
    expect(resolved.style["--chat-dialog-body-scrollbar-gutter"]).toBe("auto");
    expect(resolved.style["--chat-dialog-frame"]).toBe(
      'url("asset://assets/dialog-border.svg") 28 fill / 28px stretch',
    );
    expect(resolved.style["--chat-dialog-frame-image"]).toBe('url("asset://assets/dialog-border.svg")');
    expect(resolved.style["--chat-dialog-frame-slice"]).toBe("28");
    expect(resolved.style["--chat-dialog-frame-width"]).toBe("28px");
    expect(resolved.style["--chat-dialog-frame-outset"]).toBe("0px");
    expect(resolved.style["--chat-dialog-height"]).toBe("166px");
    expect(resolved.style["--chat-dialog-padding"]).toBe("40px");
    expect(resolved.style["--chat-dialog-toolbar-gap"]).toBe("10px");
    expect(resolved.style["--chat-dialog-toolbar-reserved-height"]).toBeUndefined();
    expect(resolved.style["--chat-dialog-name-input-gap"]).toBe("clamp(84px, 20svh, 180px)");
    expect(resolved.style["--chat-dialog-stack-bottom"]).toContain("--chat-dialog-name-input-gap");
    expect(resolved.style["--chat-dialog-toolbar-placement"]).toBe("dialog-top");
    expect(resolved.style["--chat-dialog-toolbar-reveal"]).toBe("hover");
    expect(resolved.style["--chat-dialog-toolbar-layer-bottom"]).toContain("--chat-dialog-height");
    expect(resolved.style["--chat-dialog-toolbar-layer-width"]).toContain("--chat-ui-runtime-width");
    expect(resolved.style["--chat-options-name-clearance"]).toBe("5.6svh");
    expect(resolved.style["--chat-dialog-width"]).toBe("min(86vw, 980px)");
    expect(resolved.style["--chat-dialog-offset-y"]).toBe("-8px");
    expect(resolved.style["--chat-dialog-text-theme-align"]).toBe("center");
    expect(resolved.style["--chat-dialog-text-shadow"]).toBe("0 2px 4px rgba(0,0,0,0.7)");
    expect(resolved.style["--chat-dialog-text-theme-font-size"]).toBe("34px");
    expect(resolved.style["--chat-dialog-text-theme-font-weight"]).toBe("800");
    expect(resolved.style["--chat-option-color"]).toBe("#ffffff");
    expect(resolved.style["--chat-option-active-background"]).toBe("#f3cf57");
    expect(resolved.style["--chat-option-active-color"]).toBe("#1d2630");
    expect(resolved.style["--chat-option-hover-background"]).toBe("rgba(70,70,70,0.74)");
    expect(resolved.style["--chat-option-font-size"]).toBe("clamp(18px, 1.6svh, 32px)");
    expect(resolved.style["--chat-option-font-weight"]).toBe("800");
    expect(resolved.style["--chat-option-icon-opacity"]).toBe("1");
    expect(resolved.style["--chat-option-icon-size"]).toBe("clamp(28px, 3.78svh, 38px)");
    expect(resolved.style["--chat-option-justify-content"]).toBe("flex-start");
    expect(resolved.style["--chat-option-padding"]).toBe("8px 18px 8px 60px");
    expect(resolved.style["--chat-option-min-height"]).toBe("clamp(36px, 5.2svh, 96px)");
    expect(resolved.style["--chat-option-text-shadow"]).toBe("0 2px 4px rgba(0,0,0,0.7)");
    expect(resolved.style["--chat-options-left"]).toBe("calc(100% - var(--stage-safe-x))");
    expect(resolved.style["--chat-options-bottom"]).toBe(
      "calc(var(--stage-control-stack-height) + var(--chat-dialog-name-input-gap) + var(--chat-options-name-clearance))",
    );
    expect(resolved.style["--chat-options-top"]).toBe("auto");
    expect(resolved.style["--chat-options-transform"]).toBe("translateX(-100%)");
    expect(resolved.style["--chat-options-max-width"]).toBe("min(40vw, 760px, calc(100vw - 32px))");
    expect(resolved.style["--chat-options-min-width"]).toBe("clamp(320px, 26vw, 720px)");
    expect(resolved.style["--chat-options-mobile-left"]).toBe("var(--chat-options-left)");
    expect(resolved.style["--chat-options-mobile-width"]).toBe("var(--chat-options-width)");
    expect(resolved.style["--chat-options-width"]).toBe("max-content");
    expect(resolved.style["--chat-input-background"]).toBe("rgba(34,34,40,0.9)");
    expect(resolved.style["--chat-input-field-background"]).toBe("rgba(50,50,50,0.78)");
    expect(resolved.style["--chat-input-field-border-radius"]).toBe("12px");
    expect(resolved.style["--chat-input-grid-template-columns"]).toBe("minmax(0, 1fr) 38px 38px");
    expect(resolved.style["--chat-input-max-width"]).toBe("720px");
    expect(resolved.style["--chat-send-label-display"]).toBe("none");
    expect(resolved.style["--chat-send-position"]).toBe("absolute");
    expect(resolved.style["--chat-toolbar-color"]).toBe("#ffffff");
    expect(resolved.style["--chat-send-background"]).toBe("#644ae3");
    expect(resolved.style["--chat-send-color"]).toBe("#ffffff");
    expect(resolved.style["--chat-name-background"]).toBe("rgba(28,22,48,0.92)");
    expect(resolved.style["--chat-name-background-image"]).toBe('url("asset://assets/name-plate.png")');
    expect(resolved.style["--chat-name-background-slice"]).toBe("16");
    expect(resolved.style["--chat-name-background-width"]).toBe("16px");
    expect(resolved.style["--chat-name-background-outset"]).toBe("0px");
    expect(resolved.style["--chat-name-frame"]).toBe('url("asset://assets/name-border.svg") 16 fill / 16px stretch');
    expect(resolved.style["--chat-name-frame-image"]).toBe('url("asset://assets/name-border.svg")');
    expect(resolved.style["--chat-name-frame-slice"]).toBe("16");
    expect(resolved.style["--chat-name-frame-width"]).toBe("16px");
    expect(resolved.style["--chat-name-frame-outset"]).toBe("0px");
    expect(resolved.style["--chat-name-border-color"]).toBe("rgba(156,140,255,0.6)");
    expect(resolved.style["--chat-name-border-radius"]).toBe("6px");
    expect(resolved.style["--chat-name-box-shadow"]).toBe("0 12px 28px rgba(0,0,0,0.36)");
    expect(resolved.style["--chat-name-color"]).toBe("#9c8cff");
    expect(resolved.style["--chat-name-theme-font-family"]).toBe("Trebuchet MS, Georgia, serif");
    expect(resolved.style["--chat-name-after-background"]).toContain("radial-gradient");
    expect(resolved.style["--chat-name-after-content"]).toBe('""');
    expect(resolved.style["--chat-name-after-display"]).toBe("block");
    expect(resolved.style["--chat-name-after-height"]).toBe("0.72em");
    expect(resolved.style["--chat-name-after-width"]).toBe("3.2em");
    expect(resolved.style["--chat-name-before-background"]).toContain("linear-gradient");
    expect(resolved.style["--chat-name-before-content"]).toBe('""');
    expect(resolved.style["--chat-name-before-display"]).toBe("block");
    expect(resolved.style["--chat-name-before-height"]).toBe("0.72em");
    expect(resolved.style["--chat-name-before-position"]).toBe("static");
    expect(resolved.style["--chat-name-before-width"]).toBe("3.2em");
    expect(resolved.style["--chat-name-border"]).toBe("0 solid transparent");
    expect(resolved.style["--chat-name-border-bottom"]).toBe("0 solid transparent");
    expect(resolved.style["--chat-name-hide-when-start-option"]).toBe("true");
    expect(resolved.style["--chat-name-overlap"]).toBe("14px");
    expect(resolved.style["--chat-name-sheen"]).toBe("none");
    expect(resolved.style["--chat-name-text-shadow"]).toBe("0 2px 4px rgba(0,0,0,0.7)");
    expect(resolved.style["--chat-name-theme-font-size"]).toBe("30px");
    expect(resolved.style["--chat-name-theme-font-weight"]).toBe("800");
    expect(resolved.style["--chat-name-left"]).toBe("50%");
    expect(resolved.style["--chat-name-transform"]).toBe("translateX(-50%)");
    expect(resolved.style["--logs-panel-background"]).toBe("rgba(20,20,28,0.78)");
    expect(resolved.style["--logs-panel-background-image"]).toBe('url("asset://assets/log-panel.png")');
    expect(resolved.style["--logs-panel-border-radius"]).toBe("8px");
    expect(resolved.style["--logs-code-background"]).toBe("rgba(8,9,14,0.9)");
    expect(resolved.style["--logs-code-background-image"]).toBe('url("asset://assets/log-code.png")');
    expect(resolved.style["--logs-code-font-family"]).toBe("JetBrains Mono, ui-monospace, monospace");
    expect(resolved.style["--logs-line-hover-background"]).toBe("rgba(100,74,227,0.1)");
    expect(resolved.style["--logs-line-expanded-background"]).toBe("rgba(100,74,227,0.15)");
    expect(resolved.style["--logs-file-active-background"]).toBe("rgba(100,74,227,0.18)");
    expect(resolved.style["--logs-level-error-color"]).toBe("#ff9ca7");
    expect(resolved.style["--logs-level-debug-border-color"]).toBe("rgba(91,173,255,0.34)");
    expect(resolved.typewriter.cps).toBe(200);
    expect(resolved.typewriter.soundUrl).toBe("asset://assets/sfx/type.wav");
    expect(resolved.fontFaces).toContain("@font-face");
    expect(resolved.fontFaces).toContain('font-family: "Mio Sans";');
    expect(resolved.fontFaces).toContain('url("asset://assets/fonts/mio.woff2")');
  });

  it("uses frame geometry for a nine-slice background without requiring a frame image", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "nine-slice-background",
        name: { en: "Nine-slice Background" },
        tokens: {
          dialog: {
            backgroundImage: "assets/dialog.png",
            frameSlice: 24,
            frameWidthPx: 18,
            frameOutsetPx: 2,
          },
          input: { backgroundImage: "assets/input.png" },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-dialog-background-image"]).toBe('url("asset://assets/dialog.png")');
    expect(resolved.style["--chat-dialog-background-slice"]).toBe("24");
    expect(resolved.style["--chat-dialog-background-width"]).toBe("18px");
    expect(resolved.style["--chat-dialog-background-outset"]).toBe("2px");
    expect(resolved.style["--chat-dialog-frame-image"]).toBeUndefined();
    expect(resolved.style["--chat-input-background-slice"]).toBe("32");
    expect(resolved.style["--chat-input-background-width"]).toBe("32px");
    expect(resolved.style["--chat-input-background-outset"]).toBe("0px");
  });

  it("maps the arrow-fade name decoration without adding a frame", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "arrow-fade-theme",
        name: { en: "Arrow Fade" },
        tokens: {
          name: {
            background: "linear-gradient(90deg, #174688, transparent)",
            decoration: "arrow-fade",
          },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-name-after-display"]).toBe("block");
    expect(resolved.style["--chat-name-after-width"]).toBe("2.8em");
    expect(resolved.style["--chat-name-before-position"]).toBe("static");
    expect(resolved.style["--chat-name-before-width"]).toBe("0.72em");
    expect(resolved.style["--chat-name-border"]).toBe("0 solid transparent");
    expect(resolved.style["--chat-name-clip-path"]).toBe("polygon(0 50%, 18px 0, 100% 0, 100% 100%, 18px 100%)");
    expect(resolved.style["--chat-name-sheen"]).toBe("none");
    expect(resolved.style["--chat-name-frame-image"]).toBeUndefined();
  });

  it("maps reusable frame geometry without leaking chat frames into logs", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "svg-frames",
        name: { en: "SVG Frames" },
        tokens: {
          dialog: {
            frameImage: "assets/dialog.svg",
            frameOutsetPx: 6,
            frameSlice: 40,
            frameWidthPx: 12,
          },
          logs: {
            panel: {
              frameImage: "assets/logs.svg",
              frameOutsetPx: 4,
              frameSlice: 24,
              frameWidthPx: 8,
            },
            toolbar: {
              frameWidthPx: 0,
            },
          },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-dialog-frame-image"]).toBe('url("asset://assets/dialog.svg")');
    expect(resolved.style["--chat-dialog-frame-slice"]).toBe("40");
    expect(resolved.style["--chat-dialog-frame-width"]).toBe("12px");
    expect(resolved.style["--chat-dialog-frame-outset"]).toBe("6px");
    expect(resolved.style["--logs-panel-frame-image"]).toBe('url("asset://assets/logs.svg")');
    expect(resolved.style["--logs-panel-frame-slice"]).toBe("24");
    expect(resolved.style["--logs-panel-frame-width"]).toBe("8px");
    expect(resolved.style["--logs-panel-frame-outset"]).toBe("4px");
    expect(resolved.style["--logs-toolbar-frame-image"]).toBeUndefined();
    expect(resolved.style["--logs-toolbar-frame-width"]).toBe("0px");
    expect(resolved.style["--logs-viewer-frame-image"]).toBeUndefined();
  });

  it("does not apply optional theme layout fields when a theme omits them", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "plain-subtitle",
        name: { en: "Plain Subtitle" },
        tokens: {
          dialog: { chrome: "none", heightPx: 156 },
          input: { fieldBackground: "rgba(50,50,50,0.78)" },
          options: { minHeightPx: 52, placement: "right" },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-dialog-stack-bottom"]).toBeUndefined();
    expect(resolved.style["--chat-dialog-name-input-gap"]).toBeUndefined();
    expect(resolved.style["--chat-dialog-toolbar-placement"]).toBeUndefined();
    expect(resolved.style["--chat-dialog-toolbar-input-clearance"]).toBeUndefined();
    expect(resolved.style["--chat-input-grid-template-columns"]).toBeUndefined();
    expect(resolved.style["--chat-input-field-display"]).toBeUndefined();
    expect(resolved.style["--chat-input-field-position"]).toBeUndefined();
    expect(resolved.style["--chat-input-layout"]).toBeUndefined();
    expect(resolved.style["--chat-input-max-width"]).toBeUndefined();
    expect(resolved.style["--chat-send-position"]).toBeUndefined();
    expect(resolved.style["--chat-send-border-radius"]).toBeUndefined();
    expect(resolved.style["--chat-option-min-height"]).toBe("52px");
    expect(resolved.style["--chat-options-bottom"]).toContain("--chat-dialog-toolbar-reserved-height");
  });

  it("maps opt-in input-top toolbar placement without affecting omitted themes", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "input-toolbar",
        name: { en: "Input Toolbar" },
        tokens: {
          dialog: { chrome: "none", heightPx: 166, nameInputGapVh: 20 },
          toolbar: { placement: "input-top", reveal: "hover" },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-dialog-toolbar-placement"]).toBe("input");
    expect(resolved.style["--chat-dialog-toolbar-input-clearance"]).toBe("12px");
    expect(resolved.style["--chat-dialog-toolbar-layer-width"]).toContain("--chat-ui-runtime-width");
    expect(resolved.style["--chat-dialog-stack-bottom"]).toContain("clamp(34px, 4.2svh, 46px)");
  });

  it("maps opt-in pill input layout and aligns input-top toolbar to the pill width", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "pill-input",
        name: { en: "Pill Input" },
        tokens: {
          input: { layout: "pill", maxWidthPx: 640 },
          toolbar: { placement: "input-top", reveal: "hover" },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-input-layout"]).toBe("pill");
    expect(resolved.style["--chat-input-max-width"]).toBe("640px");
    expect(resolved.style["--stage-input-height"]).toBe(
      "calc(var(--chat-input-button-size) + clamp(14px, 1.8svh, 18px))",
    );
    expect(resolved.style["--chat-input-padding"]).toBe("clamp(7px, 0.9svh, 9px) clamp(9px, 1.2svh, 12px)");
    expect(resolved.style["--chat-input-grid-template-columns"]).toBe(
      "var(--chat-input-button-size) minmax(0, 1fr) auto",
    );
    expect(resolved.style["--chat-input-panel-display"]).toBe("grid");
    expect(resolved.style["--chat-input-send-display"]).toBe("none");
    expect(resolved.style["--chat-input-voice-stack-display"]).toBe("none");
    expect(resolved.style["--chat-input-border-color"]).toBe("transparent");
    expect(resolved.style["--chat-input-border-radius"]).toBe("calc(var(--stage-input-height) / 2)");
    expect(resolved.style["--chat-input-field-background"]).toBe("transparent");
    expect(resolved.style["--chat-input-field-border-radius"]).toBe("0px");
    expect(resolved.style["--chat-send-background"]).toBe("transparent");
    expect(resolved.style["--chat-send-border-color"]).toBe("transparent");
    expect(resolved.style["--chat-send-border-radius"]).toBe("50%");
    expect(resolved.style["--chat-send-box-shadow"]).toBe("none");
    expect(resolved.style["--chat-send-color"]).toBe("var(--chat-input-color, #fff)");
    expect(resolved.style["--chat-dialog-toolbar-input-clearance"]).toBe("4px");
    expect(resolved.style["--chat-dialog-toolbar-layer-width"]).toContain("--chat-input-max-width");
  });

  it("uses the legacy CSS baseline when a theme explicitly requests external send placement", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "external-send",
        name: { en: "External Send" },
        tokens: {
          input: { layout: "default", sendPlacement: "outside" },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-input-layout"]).toBeUndefined();
    expect(resolved.style["--chat-input-field-display"]).toBeUndefined();
    expect(resolved.style["--chat-input-grid-template-columns"]).toBeUndefined();
    expect(resolved.style["--chat-send-position"]).toBeUndefined();
  });

  it("maps the compact inside-send layout only when a theme explicitly requests it", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "inside-send",
        name: { en: "Inside Send" },
        tokens: {
          input: { layout: "default", sendPlacement: "inside" },
          send: { borderColor: "#123456" },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-input-field-display"]).toBe("block");
    expect(resolved.style["--chat-input-field-position"]).toBe("relative");
    expect(resolved.style["--chat-input-grid-template-columns"]).toBe("minmax(0, 1fr) 38px 38px");
    expect(resolved.style["--chat-input-textarea-padding-right"]).toBe("56px");
    expect(resolved.style["--chat-send-label-display"]).toBe("none");
    expect(resolved.style["--chat-send-position"]).toBe("absolute");
    expect(resolved.style["--chat-send-border-color"]).toBe("#123456");
    expect(resolved.style["--chat-send-right"]).toBe("11px");
    expect(resolved.style["--chat-send-top"]).toBe("50%");
    expect(resolved.style["--chat-send-transform"]).toBe("translateY(-50%)");
    expect(resolved.style["--chat-send-width"]).toBe("36px");
  });

  it("lets explicit visual tokens override pill layout defaults", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "custom-pill",
        name: { en: "Custom Pill" },
        tokens: {
          input: {
            borderColor: "#102030",
            borderRadius: "18px",
            boxShadow: "0 0 9px #123456",
            fieldBackground: "rgba(7,8,9,0.7)",
            fieldBorderRadius: "11px",
            layout: "pill",
          },
          send: {
            background: "#123456",
            borderColor: "#abcdef",
            borderRadius: "14px",
            boxShadow: "0 0 7px #abcdef",
            color: "#fedcba",
          },
          toolbar: { borderRadius: "17px" },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-input-border-radius"]).toBe("18px");
    expect(resolved.style["--chat-input-border-color"]).toBe("#102030");
    expect(resolved.style["--chat-input-field-background"]).toBe("rgba(7,8,9,0.7)");
    expect(resolved.style["--chat-input-field-border-radius"]).toBe("11px");
    expect(resolved.style["--chat-input-box-shadow"]).toBe("0 0 9px #123456");
    expect(resolved.style["--chat-send-background"]).toBe("#123456");
    expect(resolved.style["--chat-send-border-color"]).toBe("#abcdef");
    expect(resolved.style["--chat-send-border-radius"]).toBe("14px");
    expect(resolved.style["--chat-send-box-shadow"]).toBe("0 0 7px #abcdef");
    expect(resolved.style["--chat-send-color"]).toBe("#fedcba");
    expect(resolved.style["--chat-toolbar-border-radius"]).toBe("17px");
  });

  it("filters unsafe theme values while keeping safe tokens and numeric clamps", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "unsafe-theme",
        name: { en: "Unsafe Theme" },
        tokens: {
          global: {
            fontFamily: 'Bad"; color:red',
            themeColor: "#22aa88",
          },
          fonts: [
            { family: "Theme Sans", src: "../escape.woff2", style: "italic", weight: "400" },
            { family: "Theme Sans", src: "assets/fonts/theme.woff2", style: "italic", weight: "400" },
          ],
          dialog: {
            background: "rgba(12,12,18,0.9)",
            backgroundImage: "https://example.com/dialog.png",
            boxShadow: "0 0 12px rgba(0,0,0,0.4)",
            heightPx: 999,
            padding: 200,
            widthPct: 10,
          },
          input: {
            background: "rgba(30,30,34,0.9)",
            fieldBackground: "url(javascript:alert(1))",
            fieldBorderRadius: "12px; position:absolute",
          },
          options: {
            color: "#ffffff",
            gap: 999,
            hover: { background: "rgba(50,50,50,0.9); position:absolute" },
          },
          name: {
            background: "rgba(25,25,30,0.9)",
            backgroundImage: "../name.png",
            color: "#ffffff",
          },
          logs: {
            code: {
              background: "rgba(8,9,14,0.9)",
              backgroundImage: "/tmp/log-code.png",
              fontFamily: 'Bad"; color:red',
            },
            panel: {
              backgroundImage: "https://example.com/log-panel.png",
            },
            line: {
              hover: { background: "rgba(50,50,50,0.9); position:absolute" },
            },
          },
          typewriter: {
            cps: 0,
            sound: "/tmp/type.wav",
          },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-theme-color"]).toBe("#22aa88");
    expect(resolved.style["--font-chat"]).toBeUndefined();
    expect(resolved.style["--chat-dialog-background"]).toBe("rgba(12,12,18,0.9)");
    expect(resolved.style["--chat-dialog-background-image"]).toBeUndefined();
    expect(resolved.style["--chat-dialog-height"]).toBe("260px");
    expect(resolved.style["--chat-dialog-padding"]).toBe("72px");
    expect(resolved.style["--chat-dialog-width"]).toBe("min(30vw, 980px)");
    expect(resolved.style["--chat-input-background"]).toBe("rgba(30,30,34,0.9)");
    expect(resolved.style["--chat-input-field-background"]).toBeUndefined();
    expect(resolved.style["--chat-options-gap"]).toBe("36px");
    expect(resolved.style["--chat-option-hover-background"]).toBeUndefined();
    expect(resolved.style["--chat-name-background"]).toBe("rgba(25,25,30,0.9)");
    expect(resolved.style["--chat-name-background-image"]).toBeUndefined();
    expect(resolved.style["--logs-code-background"]).toBe("rgba(8,9,14,0.9)");
    expect(resolved.style["--logs-code-background-image"]).toBeUndefined();
    expect(resolved.style["--logs-panel-background-image"]).toBeUndefined();
    expect(resolved.style["--logs-code-font-family"]).toBeUndefined();
    expect(resolved.style["--logs-line-hover-background"]).toBeUndefined();
    expect(resolved.typewriter.cps).toBe(1);
    expect(resolved.typewriter.soundUrl).toBeUndefined();
    expect(resolved.fontFaces).toContain('url("asset://assets/fonts/theme.woff2")');
    expect(resolved.fontFaces).not.toContain("../escape.woff2");
  });

  it("applies resolved theme variables and font faces at runtime", async () => {
    const manifest: ChatThemeManifest = {
      schema: 1,
      id: "windborne-adventure",
      name: { en: "Windborne Adventure" },
      tokens: {
        global: { themeColor: "#f3cf57" },
        fonts: [{ family: "Theme Font", src: "assets/fonts/theme.woff2" }],
        logs: { code: { background: "rgba(10,19,25,0.88)" } },
        typewriter: { cps: 48 },
      },
    };
    repoMocks.listChatThemes.mockResolvedValue([
      { id: "windborne-adventure", name: { en: "Windborne Adventure" }, source: "builtin" },
    ]);
    repoMocks.getActiveChatThemeId.mockResolvedValue("windborne-adventure");
    repoMocks.getChatThemeManifest.mockResolvedValue(manifest);
    repoMocks.getChatTheme.mockResolvedValue({
      raw: { options_gap: 22 },
      themeColor: "rgba(80,80,90,0.7)",
    });

    renderThemeTree(<Probe />);

    await waitFor(() =>
      expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-active", "windborne-adventure"),
    );
    expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-cps", "48");
    expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-gap", "22px");
    expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-logs-code", "rgba(10,19,25,0.88)");
    await waitFor(() => expect(document.documentElement.style.getPropertyValue("--chat-theme-color")).toBe("#f3cf57"));
    expect(document.documentElement.style.getPropertyValue("--logs-code-background")).toBe("rgba(10,19,25,0.88)");
    expect(document.documentElement.style.getPropertyValue("--chat-options-gap")).toBe("22px");
    expect(document.getElementById("shinsekai-chat-theme-fonts")?.textContent).toContain(
      'url("asset://data/chat_ui_themes/windborne-adventure/assets/fonts/theme.woff2")',
    );
  });

  it("supports upload, switch, and delete flows through the theme picker", async () => {
    const onActiveThemeChange = vi.fn();
    const onThemesChange = vi.fn();
    const windborneManifest: ChatThemeManifest = {
      schema: 1,
      id: "windborne-adventure",
      name: { en: "Windborne Adventure" },
      tokens: { global: { themeColor: "#f3cf57" } },
    };
    const uploadedManifest: ChatThemeManifest = {
      schema: 1,
      id: "my-theme",
      name: { en: "My Theme" },
      tokens: {
        global: { themeColor: "#22aa88" },
        logs: { code: { background: "rgba(5,30,25,0.9)" } },
      },
    };

    repoMocks.listChatThemes
      .mockResolvedValueOnce([{ id: "windborne-adventure", name: { en: "Windborne Adventure" }, source: "builtin" }])
      .mockResolvedValueOnce([
        { id: "windborne-adventure", name: { en: "Windborne Adventure" }, source: "builtin" },
        { id: "my-theme", name: { en: "My Theme" }, source: "user" },
      ])
      .mockResolvedValueOnce([{ id: "windborne-adventure", name: { en: "Windborne Adventure" }, source: "builtin" }]);
    repoMocks.getActiveChatThemeId.mockResolvedValue("windborne-adventure");
    repoMocks.getChatTheme.mockResolvedValue({});
    repoMocks.getChatThemeManifest.mockImplementation(async (id: string) =>
      id === "my-theme" ? uploadedManifest : windborneManifest,
    );
    repoMocks.uploadChatTheme.mockResolvedValue({
      id: "my-theme",
      name: { en: "My Theme" },
      source: "user",
      version: "1.0.0",
    });
    repoMocks.setActiveChatTheme.mockResolvedValue(undefined);
    repoMocks.deleteChatTheme.mockResolvedValue(undefined);
    window.localStorage.setItem(
      "shinsekai-chat-stage-runtime-config",
      JSON.stringify({
        config: {
          ...defaultChatStageRuntimeConfig,
          dialogFill: {
            ...defaultChatStageRuntimeConfig.dialogFill,
            color: "#112233",
          },
          dialogOpacity: 0.6,
          dialogText: {
            ...defaultChatStageRuntimeConfig.dialogText,
            color: "#ddeeff",
          },
          nameText: {
            ...defaultChatStageRuntimeConfig.nameText,
            color: "#ffeeaa",
          },
        },
        version: chatStageRuntimeConfigVersion,
      }),
    );

    renderThemeTree(<ChatThemePicker onActiveThemeChange={onActiveThemeChange} onThemesChange={onThemesChange} />);

    fireEvent.click(await screen.findByRole("button", { name: "Manage themes" }));
    expect(await screen.findByRole("dialog", { name: "Chat themes" })).toHaveClass("chat-theme-picker__dialog");

    const uploadInput = document.querySelector(".chat-theme-picker__file-input") as HTMLInputElement;
    const file = new File(["theme"], "my-theme.zip", { type: "application/zip" });
    fireEvent.change(uploadInput, { target: { files: [file] } });

    await waitFor(() => expect(repoMocks.uploadChatTheme).toHaveBeenCalled());
    await waitFor(() => expect(repoMocks.setActiveChatTheme).toHaveBeenCalledWith("my-theme"));
    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("shinsekai-chat-stage-runtime-config") || "{}");
      expect(stored).toMatchObject({
        config: {
          configThemeColor: "#22aa88",
          configUseMainThemeColor: false,
          dialogFill: defaultChatStageRuntimeConfig.dialogFill,
          dialogOpacity: 0.6,
          dialogText: defaultChatStageRuntimeConfig.dialogText,
          nameText: defaultChatStageRuntimeConfig.nameText,
        },
        version: chatStageRuntimeConfigVersion,
      });
    });
    expect(onThemesChange).toHaveBeenCalledTimes(1);
    expect(onActiveThemeChange).toHaveBeenCalledWith("my-theme");
    await waitFor(() =>
      expect(document.documentElement.style.getPropertyValue("--logs-code-background")).toBe("rgba(5,30,25,0.9)"),
    );
    expect(await screen.findByText("Theme uploaded")).toBeInTheDocument();
    expect(await screen.findByText("Theme applied")).toBeInTheDocument();

    const dialog = screen.getByRole("dialog", { name: "Chat themes" });
    const myThemeCard = within(dialog).getByText("My Theme").closest(".chat-theme-picker__card");
    expect(myThemeCard).not.toBeNull();
    fireEvent.click(within(myThemeCard as HTMLElement).getByRole("button", { name: "Delete" }));

    const confirm = await screen.findByRole("dialog", { name: "Delete theme" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(repoMocks.deleteChatTheme).toHaveBeenCalledWith("my-theme"));
    expect(onThemesChange).toHaveBeenCalledTimes(2);
    expect(onActiveThemeChange).toHaveBeenLastCalledWith(null);
    expect(await screen.findByText("Theme deleted")).toBeInTheDocument();
  });
});
