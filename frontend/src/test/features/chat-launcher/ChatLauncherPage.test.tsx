import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatLauncherPage } from "../../../features/chat-launcher/ChatLauncherPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import type { TemplateLaunchSession } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mocks = {
  getAppConfig: vi.fn(),
  getTemplateSession: vi.fn(),
  launchChat: vi.fn(),
  listBackgrounds: vi.fn(),
  listCharacters: vi.fn(),
  listTemplates: vi.fn(),
  saveTemplateSession: vi.fn(),
};

vi.mock("../../../entities/background/repository", () => ({
  backgroundsQueryKey: ["backgrounds"],
  listBackgrounds: () => mocks.listBackgrounds(),
}));
vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: () => mocks.listCharacters(),
}));
vi.mock("../../../entities/template/repository", () => ({
  getTemplateSession: () => mocks.getTemplateSession(),
  listTemplates: () => mocks.listTemplates(),
  saveTemplateSession: (session: TemplateLaunchSession) => mocks.saveTemplateSession(session),
  templatesQueryKey: ["templates"],
}));
vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mocks.getAppConfig(),
}));
vi.mock("../../../entities/chat/repository", () => ({
  launchChat: (payload: unknown) => mocks.launchChat(payload),
}));

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <I18nProvider language="en">
          <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
            <ChatLauncherPage />
          </MemoryRouter>
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ChatLauncherPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listBackgrounds.mockResolvedValue([]);
    mocks.listCharacters.mockResolvedValue([]);
    mocks.listTemplates.mockResolvedValue([]);
    mocks.getAppConfig.mockResolvedValue({
      system_config: { voice_language: "ja" },
    });
    mocks.getTemplateSession.mockResolvedValue(null);
    mocks.saveTemplateSession.mockImplementation(async (session: TemplateLaunchSession) => session);
    mocks.launchChat.mockResolvedValue({
      dialogText: "Ready",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    });
  });

  it("renders the page title", async () => {
    renderPage();
    expect(await screen.findByText("Launch chat")).toBeInTheDocument();
  });

  it("restores saved launch session values before starting chat", async () => {
    mocks.listTemplates.mockResolvedValue([
      {
        content: "template content",
        id: "tpl-session",
        name: "Session Template",
        path: "D:/templates/session.yaml",
        scenario: "festival night",
        system: "stay in character",
        updatedAt: "2026-01-01",
      },
    ]);
    mocks.listBackgrounds.mockResolvedValue([
      {
        bg_tags: "",
        bgm_list: [],
        bgm_tags: "",
        name: "school",
        sprite_prefix: "school",
        sprites: [],
      },
    ]);
    mocks.listCharacters.mockResolvedValue([{ name: "Mio" }, { name: "Aki" }]);
    mocks.getTemplateSession.mockResolvedValue({
      background: "school",
      effectNames: [],
      filenameStub: "Session Template",
      historyPath: " D:/history/session.json ",
      initSpritePath: " D:/sprites/init.png ",
      maxDialogItems: 12,
      maxSpeechChars: 160,
      roomId: "room-7",
      scenario: "old scenario",
      selectedCharacters: ["Mio", "Aki"],
      system: "old system",
      templateFileDropdown: "tpl-session",
      useCg: true,
      useChoice: false,
      useCot: true,
      useEffect: false,
      useNarration: true,
      useStat: false,
      useTranslation: true,
      voiceLanguage: "en",
    } satisfies TemplateLaunchSession);

    renderPage();

    expect(await screen.findByText("Session Template")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByDisplayValue(/session\.json/).length).toBeGreaterThan(0));
    expect(screen.getByDisplayValue(/D:\/sprites\/init\.png/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Launch" }));

    await waitFor(() => expect(mocks.launchChat).toHaveBeenCalledTimes(1));
    expect(mocks.saveTemplateSession).toHaveBeenCalledWith(
      expect.objectContaining({
        background: "school",
      effectNames: [],
        historyPath: "D:/history/session.json",
        initSpritePath: "D:/sprites/init.png",
        roomId: "room-7",
        selectedCharacters: ["Mio", "Aki"],
        templateFileDropdown: "tpl-session",
        useCg: true,
        voiceLanguage: "en",
      }),
    );
    expect(mocks.launchChat).toHaveBeenCalledWith(
      expect.objectContaining({
        backgroundName: "school",
        characters: ["Mio", "Aki"],
        historyPath: "D:/history/session.json",
        initSpritePath: "D:/sprites/init.png",
        resetHistory: false,
        roomId: "room-7",
        scenario: "festival night",
        system: "stay in character",
        templateId: "tpl-session",
        templateName: "Session Template",
        useCg: true,
      }),
    );
  });

  it("requires quick restart confirmation before launching with resetHistory", async () => {
    mocks.listTemplates.mockResolvedValue([
      {
        content: "template content",
        id: "tpl-1",
        name: "Default Template",
        path: "D:/templates/default.yaml",
        scenario: "",
        system: "",
        updatedAt: "2026-01-01",
      },
    ]);
    mocks.listBackgrounds.mockResolvedValue([]);
    mocks.listCharacters.mockResolvedValue([{ name: "Mio" }]);

    renderPage();

    expect(await screen.findByText("Default Template")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Quick restart" }));
    expect(mocks.launchChat).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog", { name: "Quick restart" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Quick restart" }));

    await waitFor(() => expect(mocks.launchChat).toHaveBeenCalledTimes(1));
    expect(mocks.launchChat).toHaveBeenCalledWith(expect.objectContaining({ resetHistory: true }));
  });
});
