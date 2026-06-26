import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TemplateEditorPage } from "../../../features/template-editor/TemplateEditorPage";
import { buildDefaultTemplateScenario } from "../../../features/template-editor/templateFlow";
import { I18nProvider, translateMessage } from "../../../shared/i18n/I18nProvider";
import { sampleConfig } from "../../../shared/platform/sampleData";
import type { TemplateLaunchSession } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mockListBackgrounds = vi.fn();
const mockListCharacters = vi.fn();
const mockLaunchChat = vi.fn();
const mockGetAppConfig = vi.fn();
const mockSaveSystemConfig = vi.fn();
const mockGenerateTemplate = vi.fn();
const mockGetTemplateSession = vi.fn();
const mockListTemplates = vi.fn();
const mockSaveTemplate = vi.fn();
const mockSaveTemplateSession = vi.fn();

vi.mock("../../../entities/background/repository", () => ({
  backgroundsQueryKey: ["backgrounds"],
  listBackgrounds: () => mockListBackgrounds(),
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: () => mockListCharacters(),
}));

vi.mock("../../../entities/chat/repository", () => ({
  launchChat: (input: unknown) => mockLaunchChat(input),
}));

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mockGetAppConfig(),
  saveSystemConfig: (input: unknown) => mockSaveSystemConfig(input),
}));

vi.mock("../../../entities/template/repository", () => ({
  generateTemplate: (input: unknown) => mockGenerateTemplate(input),
  getTemplateSession: () => mockGetTemplateSession(),
  listTemplates: () => mockListTemplates(),
  saveTemplate: (input: unknown) => mockSaveTemplate(input),
  saveTemplateSession: (input: unknown) => mockSaveTemplateSession(input),
  templatesQueryKey: ["templates"],
}));

const template = {
  content: "Morning scene\n\nSystem rules",
  id: "opening",
  name: "Opening",
  path: "/templates/opening.txt",
  scenario: "Morning scene",
  system: "System rules",
  updatedAt: "now",
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <TemplateEditorPage />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("TemplateEditorPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListTemplates.mockResolvedValue([template]);
    mockGetTemplateSession.mockResolvedValue(null);
    mockGetAppConfig.mockResolvedValue(structuredClone(sampleConfig));
    mockListCharacters.mockResolvedValue([
      { color: "#66ccff", name: "Nanami" },
      { color: "#ff99aa", name: "Mika" },
    ]);
    mockListBackgrounds.mockResolvedValue([{ name: "默认房间" }]);
    mockSaveTemplate.mockImplementation(async (input) => ({ ...template, ...(input as object), id: "opening" }));
    mockGenerateTemplate.mockResolvedValue({
      ...template,
      generationMessage: "generated",
      name: "Generated",
      scenario: "Generated scenario",
      system: "Generated system",
    });
    mockLaunchChat.mockResolvedValue({ dialogText: "launched" });
    mockSaveTemplateSession.mockResolvedValue(undefined);
    mockSaveSystemConfig.mockResolvedValue(sampleConfig.system_config);
  });

  it("saves edited scenario text and generates with selected characters", async () => {
    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("Morning scene"), { target: { value: "Updated scene" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockSaveTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          content: "Updated scene\n\nSystem rules",
          name: "Opening",
          scenario: "Updated scene",
          system: "System rules",
        }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Select all characters" }));
    expect(screen.getByRole("button", { name: "Nanami" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Mika" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() =>
      expect(mockGenerateTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          backgroundName: "透明场景",
          characters: ["Nanami", "Mika"],
          name: "Opening",
        }),
      ),
    );
    expect(await screen.findByDisplayValue("Generated scenario")).toBeInTheDocument();
  });

  it("auto-generates only when character selection changes and puts the default RPG brief in scenario", async () => {
    mockGenerateTemplate.mockImplementationOnce(async (input) => ({
      ...template,
      generationMessage: "generated",
      name: "Generated",
      scenario: (input as { scenario?: string }).scenario ?? "",
      system: "Generated system",
    }));
    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("Morning scene"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Nanami" }));
    const defaultScenario = buildDefaultTemplateScenario(
      ["Nanami"],
      translateMessage("en", "template.defaultScenario"),
    );

    await waitFor(() =>
      expect(mockGenerateTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          characters: ["Nanami"],
          scenario: defaultScenario,
        }),
      ),
    );
    expect(screen.getByDisplayValue(defaultScenario)).toBeInTheDocument();
    const callsAfterCharacterChange = mockGenerateTemplate.mock.calls.length;

    fireEvent.change(screen.getByLabelText("Background"), { target: { value: "默认房间" } });
    fireEvent.click(screen.getByLabelText("LLM translation"));
    await new Promise((resolve) => window.setTimeout(resolve, 260));

    expect(mockGenerateTemplate).toHaveBeenCalledTimes(callsAfterCharacterChange);
  });

  it("launches restored sessions only after quick restart confirmation", async () => {
    mockGetTemplateSession.mockResolvedValue({
      background: "默认房间",
      effectNames: [],
      filenameStub: "Session Draft",
      historyPath: " D:/history/session.json ",
      initSpritePath: " D:/sprites/init.png ",
      maxDialogItems: 8,
      maxSpeechChars: 120,
      roomId: " room-9 ",
      scenario: "Restored scene",
      selectedCharacters: ["Nanami", "Mika"],
      system: "Restored system",
      templateFileDropdown: "opening",
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

    await waitFor(() => expect(screen.getByLabelText("Template name")).toHaveValue("Session Draft"));
    fireEvent.click(screen.getByRole("button", { name: "Quick restart" }));
    expect(mockLaunchChat).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog", { name: "Quick restart" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Quick restart" }));

    await waitFor(() => expect(mockLaunchChat).toHaveBeenCalledTimes(1));
    expect(mockSaveTemplateSession).toHaveBeenCalledWith(
      expect.objectContaining({
        background: "默认房间",
        effectNames: [],
        historyPath: "D:/history/session.json",
        initSpritePath: "D:/sprites/init.png",
        roomId: "room-9",
        selectedCharacters: ["Nanami", "Mika"],
        useCg: true,
        voiceLanguage: "en",
      }),
    );
    expect(mockLaunchChat).toHaveBeenCalledWith(
      expect.objectContaining({
        backgroundName: "默认房间",
        characters: ["Nanami", "Mika"],
        resetHistory: true,
        roomId: "room-9",
        scenario: "Restored scene",
        system: "Restored system",
        templateId: "opening",
        templateName: "Session Draft",
        useCg: true,
      }),
    );
  });
});
