import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../shared/i18n";
import { ToastProvider } from "../shared/ui";
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

vi.mock("../entities/chat/repository", () => ({
  deleteChatTheme: (id: string) => repoMocks.deleteChatTheme(id),
  getActiveChatThemeId: () => repoMocks.getActiveChatThemeId(),
  getChatTheme: () => repoMocks.getChatTheme(),
  getChatThemeManifest: (id: string) => repoMocks.getChatThemeManifest(id),
  listChatThemes: () => repoMocks.listChatThemes(),
  setActiveChatTheme: (id: string) => repoMocks.setActiveChatTheme(id),
  uploadChatTheme: (file: File) => repoMocks.uploadChatTheme(file),
}));

vi.mock("../shared/platform/platform", () => ({
  getPlatform: () => platformMocks.getPlatform(),
}));

import { ChatThemeProvider, useChatTheme } from "../features/chat-stage/theme/ChatThemeProvider";
import { resolveChatTheme, type ChatThemeManifest } from "../shared/theme/chatTheme";

function Probe() {
  const theme = useChatTheme();
  return (
    <div
      data-active={theme.activeId ?? ""}
      data-cps={String(theme.resolved?.typewriter.cps ?? "")}
      data-gap={theme.style["--chat-options-gap"] ?? ""}
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
  });

  it("maps manifest tokens into chat stage CSS variables and font faces", () => {
    const resolved = resolveChatTheme(
      {
        schema: 1,
        id: "classic-dark",
        name: { en: "Classic Dark" },
        tokens: {
          global: { fontFamily: "Mio Sans", themeColor: "#644ae3" },
          fonts: [{ family: "Mio Sans", src: "assets/fonts/mio.woff2", style: "normal", weight: "400" }],
          dialog: {
            background: "rgba(20,20,28,0.86)",
            backgroundImage: "assets/dialog-frame.png",
            borderColor: "rgba(255,255,255,0.32)",
            borderRadius: "8px",
            boxShadow: "0 16px 44px rgba(0,0,0,0.5)",
            color: "#ffffff",
            offsetY: -8,
            padding: 40,
            widthPct: 86,
          },
          input: {
            background: "rgba(34,34,40,0.9)",
            borderColor: "rgba(255,255,255,0.22)",
            color: "#ffffff",
            fieldBackground: "rgba(50,50,50,0.78)",
          },
          name: { color: "#9c8cff" },
          options: {
            background: "rgba(50,50,50,0.68)",
            color: "#ffffff",
            gap: 10,
            hover: { background: "rgba(70,70,70,0.74)" },
          },
          send: { background: "#644ae3", color: "#ffffff" },
          toolbar: { background: "rgba(34,34,40,0.9)", color: "#ffffff" },
          typewriter: { cps: 240, sound: "assets/sfx/type.wav" },
        },
      },
      (rel) => `asset://${rel}`,
    );

    expect(resolved.style["--chat-theme-color"]).toBe("#644ae3");
    expect(resolved.style["--font-chat"]).toBe('"Mio Sans"');
    expect(resolved.style["--chat-dialog-background"]).toBe("rgba(20,20,28,0.86)");
    expect(resolved.style["--chat-dialog-background-image"]).toBe('url("asset://assets/dialog-frame.png")');
    expect(resolved.style["--chat-dialog-padding"]).toBe("40px");
    expect(resolved.style["--chat-dialog-width"]).toBe("min(86vw, 980px)");
    expect(resolved.style["--chat-dialog-offset-y"]).toBe("-8px");
    expect(resolved.style["--chat-option-color"]).toBe("#ffffff");
    expect(resolved.style["--chat-option-hover-background"]).toBe("rgba(70,70,70,0.74)");
    expect(resolved.style["--chat-input-background"]).toBe("rgba(34,34,40,0.9)");
    expect(resolved.style["--chat-input-field-background"]).toBe("rgba(50,50,50,0.78)");
    expect(resolved.style["--chat-toolbar-color"]).toBe("#ffffff");
    expect(resolved.style["--chat-send-background"]).toBe("#644ae3");
    expect(resolved.style["--chat-send-color"]).toBe("#ffffff");
    expect(resolved.style["--chat-name-color"]).toBe("#9c8cff");
    expect(resolved.typewriter.cps).toBe(200);
    expect(resolved.typewriter.soundUrl).toBe("asset://assets/sfx/type.wav");
    expect(resolved.fontFaces).toContain("@font-face");
    expect(resolved.fontFaces).toContain('font-family: "Mio Sans";');
    expect(resolved.fontFaces).toContain('url("asset://assets/fonts/mio.woff2")');
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
            padding: 200,
            widthPct: 10,
          },
          input: {
            background: "rgba(30,30,34,0.9)",
            fieldBackground: "url(javascript:alert(1))",
          },
          options: {
            color: "#ffffff",
            gap: 999,
            hover: { background: "rgba(50,50,50,0.9); position:absolute" },
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
    expect(resolved.style["--chat-dialog-padding"]).toBe("72px");
    expect(resolved.style["--chat-dialog-width"]).toBe("min(30vw, 980px)");
    expect(resolved.style["--chat-input-background"]).toBe("rgba(30,30,34,0.9)");
    expect(resolved.style["--chat-input-field-background"]).toBeUndefined();
    expect(resolved.style["--chat-options-gap"]).toBe("36px");
    expect(resolved.style["--chat-option-hover-background"]).toBeUndefined();
    expect(resolved.typewriter.cps).toBe(1);
    expect(resolved.typewriter.soundUrl).toBeUndefined();
    expect(resolved.fontFaces).toContain('url("asset://assets/fonts/theme.woff2")');
    expect(resolved.fontFaces).not.toContain("../escape.woff2");
  });

  it("applies resolved theme variables and font faces at runtime", async () => {
    const manifest: ChatThemeManifest = {
      schema: 1,
      id: "classic-dark",
      name: { en: "Classic Dark" },
      tokens: {
        global: { themeColor: "#644ae3" },
        fonts: [{ family: "Theme Font", src: "assets/fonts/theme.woff2" }],
        typewriter: { cps: 48 },
      },
    };
    repoMocks.listChatThemes.mockResolvedValue([
      { id: "classic-dark", name: { en: "Classic Dark" }, source: "builtin" },
    ]);
    repoMocks.getActiveChatThemeId.mockResolvedValue("classic-dark");
    repoMocks.getChatThemeManifest.mockResolvedValue(manifest);
    repoMocks.getChatTheme.mockResolvedValue({
      raw: { options_gap: 22 },
      themeColor: "rgba(80,80,90,0.7)",
    });

    renderThemeTree(<Probe />);

    await waitFor(() => expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-active", "classic-dark"));
    expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-cps", "48");
    expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-gap", "22px");
    expect(document.documentElement.style.getPropertyValue("--chat-theme-color")).toBe("#644ae3");
    expect(document.documentElement.style.getPropertyValue("--chat-options-gap")).toBe("22px");
    expect(document.getElementById("shinsekai-chat-theme-fonts")?.textContent).toContain(
      'url("asset://data/chat_ui_themes/classic-dark/assets/fonts/theme.woff2")',
    );
  });

  it("locks the chat stage runtime to the built-in dark theme", async () => {
    const classicManifest: ChatThemeManifest = {
      schema: 1,
      id: "classic-dark",
      name: { en: "Classic Dark" },
      tokens: { global: { themeColor: "#644ae3" } },
    };

    repoMocks.listChatThemes.mockResolvedValue([
      { id: "classic-dark", name: { en: "Classic Dark" }, source: "builtin" },
      { id: "light-paper", name: { en: "Light Paper" }, source: "builtin" },
      { id: "my-theme", name: { en: "My Theme" }, source: "user" },
    ]);
    repoMocks.getActiveChatThemeId.mockResolvedValue("light-paper");
    repoMocks.getChatTheme.mockResolvedValue({});
    repoMocks.getChatThemeManifest.mockResolvedValue(classicManifest);
    repoMocks.setActiveChatTheme.mockResolvedValue(undefined);

    renderThemeTree(<Probe />);

    await waitFor(() => expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-active", "classic-dark"));
    expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-theme-count", "1");
    expect(screen.getByTestId("theme-probe")).toHaveAttribute("data-theme-color", "#644ae3");
    expect(repoMocks.getChatThemeManifest).toHaveBeenCalledWith("classic-dark");
    expect(repoMocks.setActiveChatTheme).toHaveBeenCalledWith("classic-dark");
  });
});
