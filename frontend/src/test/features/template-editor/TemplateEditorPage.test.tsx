import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Profiler } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TemplateEditorPage } from "../../../features/template-editor/TemplateEditorPage";
import { ChatWorkspacePage } from "../../../features/chat-workspace/ChatWorkspacePage";
import { setMobileAccessPreference } from "../../../features/mobile-access/useMobileAccessPreference";
import { buildDefaultTemplateScenario } from "../../../features/template-editor/templateFlow";
import { I18nProvider, translateMessage } from "../../../shared/i18n/I18nProvider";
import { PlatformRequestError } from "../../../shared/platform/errors";
import { sampleConfig } from "../../../shared/platform/sampleData";
import type { TemplateLaunchSession, UserPromptPresetLibrary } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const mockListBackgrounds = vi.fn();
const mockListCharacters = vi.fn();
const mockEnsureCharacterBriefs = vi.fn();
const mockSaveCharacter = vi.fn();
const mockUploadCharacterSprites = vi.fn();
const mockLaunchChat = vi.fn();
const mockReconfigureConversation = vi.fn();
const mockGetChatSnapshot = vi.fn();
const mockInstallMissingRuntimeDependency = vi.fn();
const mockGetAppConfig = vi.fn();
const mockGetMemoryStatus = vi.fn();
const mockSaveSystemConfig = vi.fn();
const mockGenerateTemplate = vi.fn();
const mockGetTemplateSession = vi.fn();
const mockGetConversationSession = vi.fn();
const mockListEffects = vi.fn();
const mockListTemplates = vi.fn();
const mockRefreshRuntimeStatus = vi.fn();
const mockSaveTemplate = vi.fn();
const mockSaveTemplateSession = vi.fn();
const mockGetUserPromptPresets = vi.fn();
const mockSaveUserPromptPresets = vi.fn();
const mockShowChatSurface = vi.fn();
const mockUpdateRuntimeStatusFromSnapshot = vi.fn();
const mockUseChatLaunchGuard = vi.fn();

vi.mock("../../../entities/background/repository", () => ({
  backgroundsQueryKey: ["backgrounds"],
  listBackgrounds: () => mockListBackgrounds(),
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  ensureCharacterBriefs: (names: string[]) => mockEnsureCharacterBriefs(names),
  listCharacters: () => mockListCharacters(),
  saveCharacter: (character: unknown, originalName?: string) => mockSaveCharacter(character, originalName),
  uploadCharacterSprites: (input: unknown) => mockUploadCharacterSprites(input),
}));

const avatarPickerState = { path: "D:/avatars/self.png" };
vi.mock("../../../shared/ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../shared/ui")>();
  return {
    ...actual,
    PathPickerDialog: ({
      onClose,
      onSelect,
      open,
      title,
    }: {
      onClose: () => void;
      onSelect: (path: string) => void;
      open: boolean;
      title: string;
    }) =>
      open ? (
        <div aria-label={title} role="dialog">
          <button
            onClick={() => {
              onSelect(avatarPickerState.path);
              onClose();
            }}
            type="button"
          >
            Choose mocked avatar
          </button>
        </div>
      ) : null,
  };
});

vi.mock("../../../entities/chat/repository", () => ({
  chatQueryKey: ["chat"],
  conversationsQueryKey: ["chat", "conversations"],
  getConversationSession: (id: string) => mockGetConversationSession(id),
  getChatSnapshot: () => mockGetChatSnapshot(),
  installMissingRuntimeDependency: (input: unknown) => mockInstallMissingRuntimeDependency(input),
  launchChat: (input: unknown) => mockLaunchChat(input),
  reconfigureConversation: (id: string, input: unknown) => mockReconfigureConversation(id, input),
}));

vi.mock("../../../features/chat-startup/useChatLaunchGuard", () => ({
  useChatLaunchGuard: () => mockUseChatLaunchGuard(),
}));

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mockGetAppConfig(),
  getMemoryStatus: (options: unknown) => mockGetMemoryStatus(options),
  saveSystemConfig: (input: unknown) => mockSaveSystemConfig(input),
}));

vi.mock("../../../entities/template/repository", () => ({
  generateTemplate: (input: unknown) => mockGenerateTemplate(input),
  getTemplateSession: () => mockGetTemplateSession(),
  getUserPromptPresets: () => mockGetUserPromptPresets(),
  listTemplates: () => mockListTemplates(),
  saveTemplate: (input: unknown) => mockSaveTemplate(input),
  saveTemplateSession: (input: unknown) => mockSaveTemplateSession(input),
  saveUserPromptPresets: (library: unknown) => mockSaveUserPromptPresets(library),
  templatesQueryKey: ["templates"],
  userPromptPresetsQueryKey: ["templates", "presets"],
}));

vi.mock("../../../entities/effect/repository", () => ({
  effectsQueryKey: ["effects"],
  listEffects: () => mockListEffects(),
}));

vi.mock("../../../shared/desktop/chatWindow", () => ({
  showChatSurface: (...args: unknown[]) => mockShowChatSurface(...args),
}));

vi.mock("../../../features/chat-workspace/ConversationLibrary", () => ({
  ConversationLibrary: () => <h1>Chats</h1>,
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

const queryClients = new Set<QueryClient>();

function renderPage(props: Parameters<typeof TemplateEditorPage>[0] = {}, onCommit = () => {}, workspace = false) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  queryClients.add(client);

  const result = render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <Profiler id="template-editor" onRender={onCommit}>
            {workspace ? (
              <MemoryRouter initialEntries={["/settings/templates?tab=new&mode=normal"]}>
                <ChatWorkspacePage />
              </MemoryRouter>
            ) : (
              <TemplateEditorPage {...props} />
            )}
          </Profiler>
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...result, queryClient: client };
}

async function clickButton(button: HTMLElement) {
  await waitFor(() => expect(button).toBeEnabled());
  await act(async () => {
    fireEvent.click(button);
  });
}

async function openCharactersDialog() {
  await clickButton(screen.getByRole("button", { name: "Edit characters" }));
  return screen.findByRole("dialog", { name: "Select & configure characters" });
}

async function openPresetPromptsDialog() {
  await clickButton(screen.getByRole("button", { name: "Edit preset prompts" }));
  return screen.findByRole("dialog", { name: "Edit preset prompts" });
}

async function openSystemPromptDialog() {
  await clickButton(screen.getByRole("button", { name: "Edit system prompt" }));
  return screen.findByRole("dialog", { name: "Edit system prompt & generation rules" });
}

describe("TemplateEditorPage", () => {
  const savedChat = {
    filenameStub: "My saved chat",
    templateFileDropdown: "opening",
    scenario: "Saved scene",
    system: "Saved rules",
    selectedCharacters: ["Nanami"],
    primaryCharacters: ["Nanami"],
    characterPromptMode: "full",
    historyPath: "D:/history/chosen",
    background: "默认房间",
    mediaSelectionMode: "semantic",
    effectNames: [],
    initSpritePath: "",
    roomId: "",
    voiceLanguage: "en",
  };
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
    mockUseChatLaunchGuard.mockReturnValue({
      refreshRuntimeStatus: mockRefreshRuntimeStatus,
      runtimeLaunchDisabled: false,
      updateRuntimeStatusFromSnapshot: mockUpdateRuntimeStatusFromSnapshot,
    });
    mockListTemplates.mockResolvedValue([template]);
    mockGetTemplateSession.mockResolvedValue(null);
    mockGetUserPromptPresets.mockResolvedValue({ groups: [], presets: [] });
    mockSaveUserPromptPresets.mockImplementation(async (library: UserPromptPresetLibrary) => library);
    mockGetAppConfig.mockResolvedValue(structuredClone(sampleConfig));
    mockGetMemoryStatus.mockResolvedValue({ modelCached: true, status: "ready" });
    mockListCharacters.mockResolvedValue([
      { color: "#66ccff", name: "Nanami" },
      { color: "#ff99aa", name: "Mika" },
    ]);
    mockEnsureCharacterBriefs.mockResolvedValue({ characters: [], generatedNames: [] });
    mockSaveCharacter.mockImplementation(async (character) => character);
    mockUploadCharacterSprites.mockImplementation(async (input: { name: string; paths: string[] }) => ({
      color: "#66ccff",
      emotion_tags: "",
      name: input.name,
      sprites: input.paths.map((path) => ({ path })),
    }));
    mockListBackgrounds.mockResolvedValue([{ name: "默认房间" }]);
    mockListEffects.mockResolvedValue([]);
    mockSaveTemplate.mockImplementation(async (input) => ({ ...template, ...(input as object), id: "opening" }));
    mockGenerateTemplate.mockResolvedValue({
      ...template,
      generationMessage: "generated",
      name: "Generated",
      scenario: "Generated scenario",
      system: "Generated system",
    });
    mockLaunchChat.mockResolvedValue({ dialogText: "launched" });
    mockGetChatSnapshot.mockResolvedValue({
      dialogText: "",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    });
    mockInstallMissingRuntimeDependency.mockResolvedValue({ message: "installed" });
    mockSaveTemplateSession.mockImplementation(async (session) => session);
    mockSaveSystemConfig.mockResolvedValue(sampleConfig.system_config);
    mockShowChatSurface.mockResolvedValue(undefined);
  });

  afterEach(async () => {
    await act(async () => {
      cleanup();
      for (const client of queryClients) client.clear();
      queryClients.clear();
    });
  });

  it("renders summary bars, direct user prompt textarea, and prompt-unrelated right sidebar controls", async () => {
    mockListEffects.mockResolvedValue([{ color: "#4455aa", name: "Rain" }]);
    renderPage();
    await screen.findByDisplayValue("Opening");

    expect(document.querySelectorAll("textarea").length).toBe(1);
    await waitFor(() => expect(screen.getByLabelText("User prompt")).toHaveValue("Morning scene"));
    expect(screen.getByText("No characters selected. Click Edit to choose cast members.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Nanami" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mika" })).not.toBeInTheDocument();
    expect(screen.getByText("No presets")).toBeVisible();
    expect(screen.getByText("Auto-sync")).toBeVisible();

    const sidebar = document.querySelector(".template-options-panel") as HTMLElement;
    expect(within(sidebar).getByText("Stage & runtime settings")).toBeVisible();
    expect(await within(sidebar).findByRole("button", { name: "Rain" })).toBeVisible();
    expect(within(sidebar).getByRole("checkbox", { name: "Use ComfyUI" })).toBeVisible();
    expect(within(sidebar).getByText("Use ComfyUI")).toHaveClass("template-side-field__label");
    expect(within(sidebar).getByText("Allow automatic outfit switching")).toHaveClass("template-side-field__label");
    expect(within(sidebar).queryByRole("checkbox", { name: "Smart sprite matching" })).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("button", { name: /Generate|Regenerate/ })).not.toBeInTheDocument();
  });

  it("defaults initial sprites to visible and saves a disabled switch when launching", async () => {
    mockGetTemplateSession.mockResolvedValue({ ...savedChat, initSpritePath: "D:/sprites/custom.png" });
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Initial sprite")).toHaveValue("D:/sprites/custom.png"));
    const toggle = screen.getByRole("checkbox", { name: "Show initial sprite" });
    expect(toggle).toBeChecked();
    await clickButton(toggle);
    expect(screen.getByLabelText("Initial sprite")).toBeDisabled();
    expect(screen.getByLabelText("Initial sprite")).toHaveValue("D:/sprites/custom.png");
    await clickButton(screen.getByRole("button", { name: "Quick restart" }));
    const dialog = screen.getByRole("dialog", { name: "Quick restart" });
    await clickButton(within(dialog).getByRole("button", { name: "Quick restart" }));
    await waitFor(() =>
      expect(mockLaunchChat).toHaveBeenCalledWith(
        expect.objectContaining({ showInitialSprite: false, initSpritePath: "D:/sprites/custom.png" }),
      ),
    );
    expect(mockSaveTemplateSession).toHaveBeenCalledWith(expect.objectContaining({ showInitialSprite: false }));
  });

  it("restores a disabled initial sprite and preserves its path when enabled again", async () => {
    mockGetTemplateSession.mockResolvedValue({
      ...savedChat,
      initSpritePath: "D:/sprites/custom.png",
      showInitialSprite: false,
    });
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Initial sprite")).toHaveValue("D:/sprites/custom.png"));
    const toggle = screen.getByRole("checkbox", { name: "Show initial sprite" });
    expect(toggle).not.toBeChecked();
    expect(screen.getByLabelText("Initial sprite")).toBeDisabled();
    await clickButton(toggle);
    expect(screen.getByLabelText("Initial sprite")).toBeEnabled();
    expect(screen.getByLabelText("Initial sprite")).toHaveValue("D:/sprites/custom.png");
  });

  it("new chat always creates independent history even with a remembered path", async () => {
    mockGetTemplateSession.mockResolvedValue(savedChat);
    mockGenerateTemplate.mockImplementation(async (input) => ({
      ...template,
      name: input.name,
      scenario: savedChat.scenario,
      system: "Indexed sprite instructions",
      mediaSelectionMode: input.mediaSelectionMode,
    }));
    renderPage({ createOnly: true, conversationTitle: "Evening walk" });
    await waitFor(() => expect(screen.getByLabelText("Template name")).toHaveValue("My saved chat"));
    expect(screen.getByLabelText("Background")).toHaveValue("透明场景");
    expect(screen.getByText("Indexed sprites")).toBeVisible();
    expect(mockGetMemoryStatus).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Quick restart" })).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("D:/history/chosen")).not.toBeInTheDocument();
    await clickButton(screen.getByRole("button", { name: "Create and start" }));
    await waitFor(() =>
      expect(mockLaunchChat).toHaveBeenCalledWith(
        expect.objectContaining({
          backgroundName: "透明场景",
          resetHistory: true,
          historyPath: "",
          conversationTitle: "Evening walk",
          templateName: "My saved chat",
          mediaSelectionMode: "indexed",
          system: "Indexed sprite instructions",
        }),
      ),
    );
    expect(mockGenerateTemplate).toHaveBeenCalledWith(
      expect.objectContaining({ backgroundName: "透明场景", mediaSelectionMode: "indexed" }),
    );
  });

  it("resets remembered background to transparent when creating a new indexed chat", async () => {
    mockGetTemplateSession.mockResolvedValue({ ...savedChat, mediaSelectionMode: "indexed" });
    mockGenerateTemplate.mockImplementation(async (input) => ({
      ...template,
      name: input.name,
      scenario: input.scenario,
      system: "Transparent background instructions",
      mediaSelectionMode: input.mediaSelectionMode,
    }));
    renderPage({ createOnly: true, conversationTitle: "Fresh scene" });
    await waitFor(() => expect(screen.getByLabelText("Template name")).toHaveValue("My saved chat"));
    expect(screen.getByLabelText("Background")).toHaveValue("透明场景");

    await clickButton(screen.getByRole("button", { name: "Create and start" }));
    await waitFor(() =>
      expect(mockLaunchChat).toHaveBeenCalledWith(
        expect.objectContaining({
          backgroundName: "透明场景",
          conversationTitle: "Fresh scene",
          historyPath: "",
          resetHistory: true,
          system: "Transparent background instructions",
        }),
      ),
    );
    expect(mockGenerateTemplate).toHaveBeenCalledWith(
      expect.objectContaining({ backgroundName: "透明场景", name: "My saved chat" }),
    );
  });

  it.each(["success", "failure", "mobile"])(
    "returns to Chats while creation is pending and handles %s after the editor unmounts",
    async (outcome) => {
      let finish!: (snapshot: unknown) => void;
      let fail!: (error: Error) => void;
      mockLaunchChat.mockReturnValueOnce(
        new Promise((resolve, reject) => {
          finish = resolve;
          fail = reject;
        }),
      );
      renderPage({}, undefined, true);
      await screen.findByDisplayValue("Opening");
      await clickButton(screen.getByRole("button", { name: "Create and start" }));

      await waitFor(() => expect(mockLaunchChat).toHaveBeenCalledTimes(1));
      expect(screen.getByRole("heading", { name: "Chats" })).toBeVisible();
      expect(screen.queryByLabelText("Template name")).not.toBeInTheDocument();
      expect(screen.getByRole("dialog")).toBeVisible();
      expect(mockShowChatSurface).not.toHaveBeenCalled();

      await act(async () => {
        if (outcome === "failure") {
          fail(new Error("Launch failed"));
        } else {
          finish({
            dialogText: "launched",
            ...(outcome === "mobile"
              ? {
                  mobileAccess: {
                    enabled: true,
                    host: "192.168.1.20",
                    httpPort: 8789,
                    websocketPort: 8790,
                    qrCodeDataUrl: "data:image/png;base64,dGVzdA==",
                    url: "http://192.168.1.20:8789/",
                    websocketUrl: "ws://192.168.1.20:8790/ws",
                  },
                }
              : {}),
          });
        }
      });
      if (outcome === "failure") {
        expect(within(screen.getByRole("dialog")).getByRole("alert")).toHaveTextContent("Launch failed");
        expect(mockShowChatSurface).not.toHaveBeenCalled();
      } else if (outcome === "mobile") {
        expect(await screen.findByRole("dialog", { name: "Mobile access is ready" })).toBeVisible();
        expect(mockShowChatSurface).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: "Open local chat" }));
        expect(mockShowChatSurface).toHaveBeenCalledWith(
          expect.objectContaining({
            snapshot: expect.objectContaining({ wsUrl: "ws://192.168.1.20:8790/ws" }),
          }),
        );
      } else {
        await waitFor(() => expect(mockShowChatSurface).toHaveBeenCalledTimes(1));
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      }
    },
  );

  it.each(["semantic", "indexed"] as const)(
    "launches the restored form before passive effects flush (%s)",
    async (mode) => {
      mockGetTemplateSession.mockResolvedValue({ ...savedChat, mediaSelectionMode: mode });
      mockGenerateTemplate.mockImplementation(async (input) => ({
        ...template,
        name: input.name,
        scenario: input.scenario,
        system: "Indexed sprite instructions",
        mediaSelectionMode: input.mediaSelectionMode,
      }));
      let clicked = false;
      renderPage({ createOnly: true, conversationTitle: "Evening walk" }, () => {
        if (clicked || screen.queryByLabelText<HTMLInputElement>("Template name")?.value !== "My saved chat") return;
        clicked = true;
        fireEvent.click(screen.getByRole("button", { name: "Create and start" }));
      });
      await waitFor(() =>
        expect(mockLaunchChat).toHaveBeenCalledWith(
          expect.objectContaining({
            templateName: "My saved chat",
            characters: ["Nanami"],
            scenario: "Saved scene",
            historyPath: "",
            resetHistory: true,
            mediaSelectionMode: "indexed",
          }),
        ),
      );
      if (mode === "semantic")
        expect(mockGenerateTemplate).toHaveBeenCalledWith(expect.objectContaining({ name: "My saved chat" }));
    },
  );

  it("generates a timestamp title when a new chat title is cleared", async () => {
    mockGetTemplateSession.mockResolvedValue({ ...savedChat, mediaSelectionMode: "indexed" });
    renderPage({ createOnly: true, conversationTitle: "  " });
    await waitFor(() => expect(screen.getByLabelText("Template name")).toHaveValue("My saved chat"));
    await clickButton(screen.getByRole("button", { name: "Create and start" }));
    await waitFor(() =>
      expect(mockLaunchChat).toHaveBeenCalledWith(
        expect.objectContaining({
          conversationTitle: expect.stringMatching(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/),
          resetHistory: true,
        }),
      ),
    );
  });

  it("keeps smart sprite matching off when a new chat loads a semantic template", async () => {
    mockListTemplates.mockResolvedValue([{ ...template, mediaSelectionMode: "semantic" }]);
    renderPage({ createOnly: true });

    await screen.findByDisplayValue("Opening");

    expect(mockGetMemoryStatus).not.toHaveBeenCalled();
    const systemDialog = await openSystemPromptDialog();
    const toggle = within(systemDialog).getByRole("checkbox", { name: "Smart sprite matching" });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeChecked());
    expect(mockGetMemoryStatus).toHaveBeenCalledWith({ startLoading: true });
  });

  it("restores independent conversation settings after all public templates are deleted", async () => {
    mockListTemplates.mockResolvedValue([]);
    mockGetConversationSession.mockResolvedValue(savedChat);
    mockReconfigureConversation.mockResolvedValue({ status: "idle", historyPath: savedChat.historyPath });
    renderPage({ conversationId: "chosen", onApplied: vi.fn() });
    await screen.findByText("Nanami");
    const button = screen.getByRole("button", { name: "Apply and continue" });
    expect(button).toBeEnabled();
    await clickButton(button);
    await waitFor(() =>
      expect(mockReconfigureConversation).toHaveBeenCalledWith(
        "chosen",
        expect.objectContaining({ scenario: "Saved scene", system: "Saved rules", historyPath: savedChat.historyPath }),
      ),
    );
  });

  it("disables applying settings while the current chat is closing", async () => {
    mockGetConversationSession.mockResolvedValue(savedChat);
    mockUseChatLaunchGuard.mockReturnValue({
      runtimeClosing: true,
      runtimeLaunchDisabled: true,
      refreshRuntimeStatus: mockRefreshRuntimeStatus,
      updateRuntimeStatusFromSnapshot: mockUpdateRuntimeStatusFromSnapshot,
    });
    renderPage({ conversationId: "chosen" });
    await screen.findByText("Nanami");
    const button = screen.getByRole("button", { name: "Apply and continue" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(mockReconfigureConversation).not.toHaveBeenCalled();
  });

  it("conversation settings restore that conversation and continue its fixed history", async () => {
    mockGetConversationSession.mockResolvedValue(savedChat);
    mockReconfigureConversation.mockResolvedValue({ status: "idle", historyPath: savedChat.historyPath });
    mockUseChatLaunchGuard.mockReturnValue({
      refreshRuntimeStatus: mockRefreshRuntimeStatus,
      runtimeLaunchDisabled: true,
      updateRuntimeStatusFromSnapshot: mockUpdateRuntimeStatusFromSnapshot,
    });
    const onApplied = vi.fn();
    renderPage({ conversationId: "chosen", onApplied });
    await screen.findByText("Nanami");
    expect(mockGetConversationSession).toHaveBeenCalledWith("chosen");
    expect(mockGetTemplateSession).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(mockReconfigureConversation).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("User prompt"), { target: { value: "Edited scene" } });

    await clickButton(screen.getByRole("button", { name: "Apply and continue" }));
    await waitFor(() =>
      expect(mockReconfigureConversation).toHaveBeenCalledWith(
        "chosen",
        expect.objectContaining({
          scenario: "Edited scene",
          resetHistory: false,
          historyPath: "D:/history/chosen",
          mediaSelectionMode: "semantic",
        }),
      ),
    );
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce());
    expect(mockLaunchChat).not.toHaveBeenCalled();
    expect(mockSaveTemplateSession).not.toHaveBeenCalled();
    expect(mockShowChatSurface).not.toHaveBeenCalled();
  });

  it("saves edited scenario text and generates with selected characters via dialogs", async () => {
    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("User prompt"), { target: { value: "Updated scene" } });

    await clickButton(screen.getByRole("button", { name: "Save" }));
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

    const charDialog = await openCharactersDialog();
    await clickButton(within(charDialog).getByRole("button", { name: "Select all characters" }));
    await clickButton(within(charDialog).getByRole("button", { name: "Confirm" }));
    expect(screen.getByText("Nanami")).toBeVisible();
    expect(screen.getByText("Mika")).toBeVisible();

    const sysDialog = await openSystemPromptDialog();
    await clickButton(within(sysDialog).getByRole("button", { name: "Regenerate" }));

    await waitFor(() =>
      expect(mockGenerateTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          backgroundName: "透明场景",
          characters: ["Nanami", "Mika"],
          name: "Opening",
        }),
      ),
    );
    expect(await within(sysDialog).findByDisplayValue("Generated system")).toBeInTheDocument();
  });

  it("shows prompt rules in SystemPromptDialog and enables vibe generation after mem0 is ready", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();

    const charDialog = await openCharactersDialog();
    await clickButton(within(charDialog).getByRole("button", { name: "Select all characters" }));
    await clickButton(within(charDialog).getByRole("button", { name: "Confirm" }));

    const sysDialog = await openSystemPromptDialog();
    expect(within(sysDialog).getByText("Prompt generation rules")).toBeVisible();
    const smartSwitch = within(sysDialog).getByRole("checkbox", { name: "Smart sprite matching" });
    fireEvent.click(smartSwitch);

    await waitFor(() => expect(mockGetMemoryStatus).toHaveBeenCalledWith({ startLoading: true }));
    await waitFor(() => expect(smartSwitch).toBeChecked());
    await clickButton(within(sysDialog).getByRole("button", { name: "Regenerate" }));

    await waitFor(() =>
      expect(mockGenerateTemplate).toHaveBeenCalledWith(expect.objectContaining({ mediaSelectionMode: "semantic" })),
    );
  });

  it("downgrades a restored semantic template when mem0 installation is declined", async () => {
    mockListTemplates.mockResolvedValue([{ ...template, mediaSelectionMode: "semantic" }]);
    mockGetMemoryStatus.mockResolvedValue({
      moduleName: "mem0",
      packageName: "mem0ai",
      status: "missing_dependency",
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("Indexed sprites")).toBeVisible());
    const sysDialog = await openSystemPromptDialog();
    expect(within(sysDialog).getByRole("checkbox", { name: "Smart sprite matching" })).not.toBeChecked();
  });

  it.each([4, 5])(
    "keeps NPC role controls available after selecting a player in a %i-character cast",
    async (count) => {
      const cast = Array.from({ length: count }, (_, index) => ({
        character_brief: "Existing brief",
        color: "#66ccff",
        name: `Character ${index + 1}`,
        sprites: [],
      }));
      mockListCharacters.mockResolvedValue(cast);
      renderPage();
      await screen.findByDisplayValue("Opening");

      const charDialog = await openCharactersDialog();
      await clickButton(within(charDialog).getByRole("button", { name: "Select all characters" }));

      const playerSelect = within(charDialog).getByRole("combobox", { name: "Player character" });
      fireEvent.keyDown(playerSelect, { key: "ArrowDown" });
      fireEvent.keyDown(playerSelect, { key: "ArrowDown" });
      fireEvent.keyDown(playerSelect, { key: "Enter" });
      await waitFor(() => expect(playerSelect).toHaveTextContent("Character 1"));
      const aiDialogue = within(charDialog).getByRole("checkbox", { name: "Allow AI to write player dialogue" });
      expect(aiDialogue).toBeChecked();
      fireEvent.click(aiDialogue);
      fireEvent.click(within(charDialog).getByRole("checkbox", { name: "Read player dialogue aloud" }));

      expect(
        within(charDialog).getByText(
          count === 5 ? "4 selected · roles need to be set" : "3 selected · all are primary",
        ),
      ).toBeVisible();
      await clickButton(
        within(charDialog).getByRole("button", {
          name: count === 5 ? "Choose primary characters" : "Change",
        }),
      );
      expect(within(charDialog).queryByRole("button", { name: /Character 1.*Primary/ })).not.toBeInTheDocument();

      // Deselect everything after Character 2 in the primary character picker (first match in grid after role header)
      for (const character of cast.slice(2)) {
        const primaryCards = within(charDialog).getAllByRole("button", { name: new RegExp(`^${character.name}`) });
        const roleCard = primaryCards.find((btn) => btn.className.includes("primary-character-dialog__card"));
        if (roleCard && roleCard.getAttribute("aria-pressed") === "true") {
          fireEvent.click(roleCard);
        }
      }
      await clickButton(within(charDialog).getByRole("button", { name: "Apply roles" }));
      await clickButton(within(charDialog).getByRole("button", { name: "Confirm" }));

      await waitFor(() =>
        expect(mockEnsureCharacterBriefs).toHaveBeenCalledWith(cast.slice(2).map(({ name }) => name)),
      );
      expect(await screen.findByText(`1 primary · ${count - 2} supporting`)).toBeInTheDocument();

      const reopened = await openCharactersDialog();
      expect(within(reopened).getByRole("combobox", { name: "Player character" })).toHaveTextContent("Character 1");
      expect(within(reopened).getByRole("checkbox", { name: "Allow AI to write player dialogue" })).not.toBeChecked();
      expect(within(reopened).getByRole("checkbox", { name: "Read player dialogue aloud" })).toBeChecked();
    },
  );

  it.each([undefined, false])(
    "restores player AI mode %s and forwards changes to generation and launch",
    async (savedMode) => {
      mockGetTemplateSession.mockResolvedValue({
        ...savedChat,
        playerCharacter: "Nanami",
        readPlayerSpeech: false,
        allowPlayerDialogue: savedMode,
      });
      mockListCharacters.mockResolvedValue([{ name: "Nanami", color: "#66ccff", sprites: [] }]);
      renderPage();
      await waitFor(() => expect(screen.getByLabelText("Template name")).toHaveValue("My saved chat"));
      const charDialog = await openCharactersDialog();
      const toggle = within(charDialog).getByRole("checkbox", { name: "Allow AI to write player dialogue" });
      const expectedInitial = savedMode ?? true;
      if (expectedInitial) expect(toggle).toBeChecked();
      else expect(toggle).not.toBeChecked();
      await clickButton(toggle);
      await clickButton(within(charDialog).getByRole("button", { name: "Confirm" }));
      await waitFor(() =>
        expect(mockGenerateTemplate).toHaveBeenCalledWith(
          expect.objectContaining({ playerCharacter: "Nanami", allowPlayerDialogue: !expectedInitial }),
        ),
      );
      await waitFor(() => expect(screen.getByRole("button", { name: "Launch chat" })).toBeEnabled());
      await clickButton(screen.getByRole("button", { name: "Launch chat" }));
      await waitFor(() =>
        expect(mockLaunchChat).toHaveBeenCalledWith(
          expect.objectContaining({
            playerCharacter: "Nanami",
            allowPlayerDialogue: !expectedInitial,
            readPlayerSpeech: false,
          }),
        ),
      );
      expect(mockSaveTemplateSession).toHaveBeenCalledWith(
        expect.objectContaining({ playerCharacter: "Nanami", allowPlayerDialogue: !expectedInitial }),
      );
    },
  );

  it("asks for primary characters above the threshold and generates missing supporting briefs", async () => {
    const largeCast = Array.from({ length: 6 }, (_, index) => ({
      character_brief: index === 4 ? "Existing brief" : "",
      color: "#66ccff",
      name: `Character ${index + 1}`,
    }));
    mockListCharacters.mockResolvedValue(largeCast);
    mockEnsureCharacterBriefs.mockResolvedValue({
      characters: largeCast.slice(2).map((character) => ({
        ...character,
        character_brief: character.character_brief || `Generated brief for ${character.name}`,
      })),
      generatedNames: ["Character 3", "Character 4", "Character 6"],
    });
    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    const charDialog = await openCharactersDialog();
    await clickButton(within(charDialog).getByRole("button", { name: "Select all characters" }));
    await clickButton(within(charDialog).getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("6 selected · roles need to be set")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Choose primary characters" })).not.toBeInTheDocument();

    const sysDialog = await openSystemPromptDialog();
    await clickButton(within(sysDialog).getByRole("button", { name: "Regenerate" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose primary characters" });
    fireEvent.click(within(dialog).getByRole("button", { name: /Character 2/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Apply roles" }));

    await waitFor(() =>
      expect(mockEnsureCharacterBriefs).toHaveBeenCalledWith([
        "Character 3",
        "Character 4",
        "Character 5",
        "Character 6",
      ]),
    );
    expect(await screen.findByText("2 primary · 4 supporting")).toBeInTheDocument();

    const charDialog2 = await openCharactersDialog();
    fireEvent.click(within(charDialog2).getByRole("button", { name: "Character 6" }));
    await clickButton(within(charDialog2).getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("2 primary · 3 supporting")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Choose primary characters" })).not.toBeInTheDocument();
  });

  it("finishes a deferred launch after character roles are applied", async () => {
    const largeCast = Array.from({ length: 5 }, (_, index) => ({
      character_brief: "Existing brief",
      color: "#66ccff",
      name: `Character ${index + 1}`,
    }));
    mockListCharacters.mockResolvedValue(largeCast);
    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    const charDialog = await openCharactersDialog();
    await clickButton(within(charDialog).getByRole("button", { name: "Select all characters" }));
    await clickButton(within(charDialog).getByRole("button", { name: "Confirm" }));

    await clickButton(screen.getByRole("button", { name: "Launch chat" }));

    const dialog = await screen.findByRole("dialog", { name: "Choose primary characters" });
    expect(mockLaunchChat).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Apply roles" }));

    await waitFor(() => expect(mockGenerateTemplate).toHaveBeenCalled());
    await waitFor(() => expect(mockLaunchChat).toHaveBeenCalledTimes(1));
  });

  it("auto-generates when character selection or prompt settings change and puts the default RPG brief in scenario", async () => {
    mockGenerateTemplate.mockImplementation(async (input) => ({
      ...template,
      generationMessage: "generated",
      name: "Generated",
      scenario: (input as { scenario?: string }).scenario ?? "",
      system: "Generated system",
    }));
    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("User prompt"), { target: { value: "" } });

    const charDialog = await openCharactersDialog();
    await clickButton(within(charDialog).getByRole("button", { name: "Nanami" }));
    await clickButton(within(charDialog).getByRole("button", { name: "Confirm" }));

    fireEvent.change(screen.getByLabelText("Template name"), { target: { value: "Renamed before generation" } });
    const defaultScenario = buildDefaultTemplateScenario(
      ["Nanami"],
      translateMessage("en", "template.defaultScenario"),
    );

    await waitFor(() =>
      expect(mockGenerateTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          characters: ["Nanami"],
          scenario: defaultScenario,
          name: "Renamed before generation",
        }),
      ),
    );
    expect(screen.getByLabelText("User prompt")).toHaveValue(defaultScenario);

    // Changing Use ComfyUI on the right sidebar auto-syncs when not manually edited
    const callsBeforeCg = mockGenerateTemplate.mock.calls.length;
    await clickButton(screen.getByRole("checkbox", { name: "Use ComfyUI" }));
    await waitFor(() => expect(mockGenerateTemplate).toHaveBeenCalledTimes(callsBeforeCg + 1));
  });

  it("uses the server-resolved characters for the restored session and launch payload", async () => {
    mockListCharacters.mockResolvedValue([
      { color: "#66ccff", name: "Nanami", sprites: [{ path: "D:/sprites/nanami.png" }] },
    ]);
    mockGetTemplateSession.mockResolvedValue({
      background: "默认房间",
      effectNames: [],
      filenameStub: "Session Draft",
      historyPath: "",
      initSpritePath: "D:/sprites/deleted.png",
      maxDialogItems: 0,
      maxSpeechChars: 0,
      roomId: "",
      scenario: "Restored scene",
      selectedCharacters: ["Deleted", "Nanami"],
      system: "Restored system",
      templateFileDropdown: "opening",
      useCg: false,
      useChoice: true,
      useCot: false,
      useEffect: true,
      useNarration: true,
      useStat: true,
      useTranslation: false,
      voiceLanguage: "ja",
    } satisfies TemplateLaunchSession);
    mockGenerateTemplate.mockResolvedValueOnce({
      ...template,
      generationMessage: "generated",
      name: "Session Draft",
      resolvedCharacters: ["Nanami"],
      scenario: "Restored scene",
      system: "Generated system",
    });
    mockSaveTemplateSession.mockImplementationOnce(async (session) => {
      const { effectNames: _legacyMissingEffectNames, ...legacySavedSession } = session as TemplateLaunchSession;
      return {
        ...legacySavedSession,
        initSpritePath: "D:/sprites/nanami.png",
        selectedCharacters: ["Nanami"],
      } as TemplateLaunchSession;
    });

    await act(async () => {
      renderPage();
    });

    expect(await screen.findByText("Nanami")).toBeInTheDocument();
    const sysDialog = await openSystemPromptDialog();
    await clickButton(within(sysDialog).getByRole("button", { name: "Regenerate" }));

    await waitFor(() =>
      expect(mockGenerateTemplate).toHaveBeenCalledWith(expect.objectContaining({ characters: ["Deleted", "Nanami"] })),
    );
    expect(await within(sysDialog).findByDisplayValue("Generated system")).toBeInTheDocument();
    await clickButton(within(sysDialog).getByRole("button", { name: "Confirm" }));
    expect(mockGenerateTemplate).toHaveBeenCalledTimes(1);

    await clickButton(screen.getByRole("button", { name: "Quick restart" }));
    const dialog = screen.getByRole("dialog", { name: "Quick restart" });
    await clickButton(within(dialog).getByRole("button", { name: "Quick restart" }));

    await waitFor(() =>
      expect(mockSaveTemplateSession).toHaveBeenCalledWith(
        expect.objectContaining({
          initSpritePath: "",
          selectedCharacters: ["Nanami"],
        }),
      ),
    );
    await waitFor(() =>
      expect(mockLaunchChat).toHaveBeenCalledWith(
        expect.objectContaining({
          characters: ["Nanami"],
          initSpritePath: "D:/sprites/nanami.png",
        }),
      ),
    );
  });

  it("preserves the restored draft when generation rejects an all-stale selection", async () => {
    mockGetTemplateSession.mockResolvedValue({
      background: "默认房间",
      effectNames: [],
      filenameStub: "Session Draft",
      historyPath: "",
      initSpritePath: "",
      maxDialogItems: 0,
      maxSpeechChars: 0,
      roomId: "",
      scenario: "Restored scene",
      selectedCharacters: ["Deleted"],
      system: "Restored system",
      templateFileDropdown: "opening",
      useCg: false,
      useChoice: true,
      useCot: false,
      useEffect: true,
      useNarration: true,
      useStat: true,
      useTranslation: false,
      voiceLanguage: "ja",
    } satisfies TemplateLaunchSession);
    mockGenerateTemplate.mockRejectedValueOnce(
      new PlatformRequestError("Select at least one character.", 422, "no_valid_characters"),
    );

    renderPage();

    expect(await screen.findByText(/Deleted/)).toBeInTheDocument();
    const sysDialog = await openSystemPromptDialog();
    expect(await within(sysDialog).findByDisplayValue("Restored system")).toBeInTheDocument();
    await clickButton(within(sysDialog).getByRole("button", { name: "Regenerate" }));

    expect(await screen.findByText("Choose at least one character.")).toBeInTheDocument();
    expect(within(sysDialog).getByDisplayValue("Restored system")).toBeInTheDocument();
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
    mockLaunchChat.mockResolvedValueOnce({
      dialogText: "launched",
      historyPath: "D:/history/confirmed.json",
    });

    const { queryClient } = renderPage();

    await waitFor(() => expect(screen.getByLabelText("Template name")).toHaveValue("Session Draft"));
    await clickButton(screen.getByRole("button", { name: "Quick restart" }));
    expect(mockLaunchChat).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog", { name: "Quick restart" });
    await clickButton(within(dialog).getByRole("button", { name: "Quick restart" }));

    await waitFor(() => expect(mockLaunchChat).toHaveBeenCalledTimes(1));
    expect(mockUpdateRuntimeStatusFromSnapshot).toHaveBeenCalledWith(
      expect.objectContaining({ dialogText: "launched" }),
    );
    expect(mockGetChatSnapshot).not.toHaveBeenCalled();
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
    await waitFor(() => expect(screen.getByDisplayValue("D:/history/confirmed.json")).toBeInTheDocument());
    expect(queryClient.getQueryData<TemplateLaunchSession>(["templates", "session"])?.historyPath).toBe(
      "D:/history/confirmed.json",
    );
    expect(mockSaveTemplateSession).toHaveBeenCalledTimes(1);
  });

  it("does not let restored template settings override the management toolbar's disabled mobile preference", async () => {
    mockGetTemplateSession.mockResolvedValueOnce({
      ...savedChat,
      filenameStub: "Session Draft",
      enableMobileAccess: true,
    });
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Template name")).toHaveValue("Session Draft"));
    expect(screen.queryByLabelText("Connect phone")).not.toBeInTheDocument();
    await clickButton(screen.getByRole("button", { name: "Launch chat" }));
    await waitFor(() =>
      expect(mockLaunchChat).toHaveBeenCalledWith(expect.objectContaining({ enableMobileAccess: false })),
    );
  });

  it("shows a QR code after launching with mobile access enabled", async () => {
    let restoreSession!: (session: null) => void;
    mockGetTemplateSession.mockReturnValueOnce(new Promise<null>((resolve) => (restoreSession = resolve)));
    setMobileAccessPreference(true);
    mockLaunchChat.mockResolvedValueOnce({
      dialogText: "launched",
      mobileAccess: {
        enabled: true,
        host: "192.168.1.20",
        httpPort: 8789,
        qrCodeDataUrl: "data:image/png;base64,dGVzdA==",
        url: "http://192.168.1.20:8789/?shinsekai_bridge_token=test#/chat",
        websocketPort: 8790,
        websocketUrl: "ws://192.168.1.20:8790/ws",
      },
    });
    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    expect(screen.queryByLabelText("Connect phone")).not.toBeInTheDocument();
    const launch = screen.getByRole("button", { name: "Launch chat" });
    expect(launch).toBeDisabled();
    expect(mockLaunchChat).not.toHaveBeenCalled();
    await act(async () => restoreSession(null));
    await clickButton(launch);

    const dialog = await screen.findByRole("dialog", { name: "Mobile access is ready" });
    expect(within(dialog).getByRole("img", { name: "QR code for mobile chat access" })).toHaveAttribute(
      "src",
      "data:image/png;base64,dGVzdA==",
    );
    expect(dialog).toHaveTextContent("8789");
    expect(dialog).toHaveTextContent("8790");
    expect(mockSaveTemplateSession).toHaveBeenCalledWith(expect.objectContaining({ enableMobileAccess: true }));
    expect(mockLaunchChat).toHaveBeenCalledWith(expect.objectContaining({ enableMobileAccess: true }));
    expect(mockShowChatSurface).not.toHaveBeenCalled();

    expect(within(dialog).getByRole("button", { name: "Copy link" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Open local chat" })).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Open local chat" }));
    await waitFor(() =>
      expect(mockShowChatSurface).toHaveBeenCalledWith(
        expect.objectContaining({
          snapshot: expect.objectContaining({ wsUrl: "ws://192.168.1.20:8790/ws" }),
        }),
      ),
    );
  });

  it("refreshes runtime status after a launch failure", async () => {
    mockLaunchChat.mockRejectedValueOnce(new Error("runtime closing"));

    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    await clickButton(screen.getByRole("button", { name: "Launch chat" }));

    expect(await screen.findByRole("dialog", { name: "Preparing chat" })).toHaveTextContent("runtime closing");
    expect(mockRefreshRuntimeStatus).toHaveBeenCalledTimes(1);
  });

  it("disables launch actions while an existing chat process is still running", async () => {
    mockUseChatLaunchGuard.mockReturnValue({
      refreshRuntimeStatus: mockRefreshRuntimeStatus,
      runtimeLaunchDisabled: true,
      updateRuntimeStatusFromSnapshot: mockUpdateRuntimeStatusFromSnapshot,
    });

    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Launch chat" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Quick restart" })).toBeDisabled();
    expect(mockGetChatSnapshot).not.toHaveBeenCalled();
  });

  it("renders empty and query error states", async () => {
    mockListTemplates.mockResolvedValueOnce([]);
    const { unmount } = renderPage();

    expect(await screen.findByText("No templates")).toBeInTheDocument();
    expect(screen.getByText("Generate a template first.")).toBeInTheDocument();
    unmount();

    mockListTemplates.mockRejectedValueOnce(new Error("templates failed"));
    renderPage();

    expect(await screen.findByText("Operation failed")).toBeInTheDocument();
    const callsBeforeRetry = mockListTemplates.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(mockListTemplates).toHaveBeenCalledTimes(callsBeforeRetry + 1));
  });

  it("persists selected effects, dialog number settings, and handles runtime dependency installs", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockListEffects.mockResolvedValue([
      {
        audio_tags: "特效 1：雨声\n特效 2: 雷声",
        image_list: [],
        image_tags: "",
        image_audio_list: [],
        color: "#4455aa",
        name: "Rain",
      },
    ]);
    mockLaunchChat.mockResolvedValueOnce({
      dialogText: "Missing mem0",
      runtimeDependencyError: {
        moduleName: "mem0",
        packageName: "mem0ai",
      },
    });

    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rain" }));

    fireEvent.click(screen.getByRole("radio", { name: "English" }));
    await waitFor(() =>
      expect(mockSaveSystemConfig).toHaveBeenCalledWith(expect.objectContaining({ voice_language: "en" })),
    );

    const sysDialog = await openSystemPromptDialog();
    fireEvent.change(within(sysDialog).getByLabelText("Max speech chars"), { target: { value: "80" } });
    fireEvent.change(within(sysDialog).getByLabelText("Max dialog items"), { target: { value: "6" } });
    await clickButton(within(sysDialog).getByRole("button", { name: "Confirm" }));

    fireEvent.change(screen.getByLabelText("Initial sprite"), { target: { value: "D:/sprites/init.png" } });
    fireEvent.change(screen.getByLabelText("History file"), { target: { value: "D:/history/log.json" } });
    await clickButton(screen.getByRole("button", { name: "Launch chat" }));

    await waitFor(() => expect(mockLaunchChat).toHaveBeenCalledTimes(1));
    expect(mockSaveTemplateSession).toHaveBeenCalledWith(
      expect.objectContaining({
        effectNames: ["Rain"],
        historyPath: "D:/history/log.json",
        initSpritePath: "D:/sprites/init.png",
        maxDialogItems: 6,
        maxSpeechChars: 80,
      }),
    );
    expect(mockLaunchChat).toHaveBeenCalledWith(
      expect.objectContaining({
        effectNames: ["Rain"],
        historyPath: "D:/history/log.json",
        initSpritePath: "D:/sprites/init.png",
      }),
    );
    expect(mockInstallMissingRuntimeDependency).toHaveBeenCalledWith({ moduleName: "mem0" });
    expect(mockShowChatSurface).not.toHaveBeenCalled();
  });

  it("preserves authored prompt sections when restoring and selecting effects", async () => {
    mockListTemplates.mockResolvedValue([
      {
        ...template,
        system:
          'System rules\n\nOutput field contract:\n- character_name (string): 内置\n- camera (string): 插件字段\n\n立绘说明:\n角色\n\n已选特效提示：\n旧音频和图片\n\n音效触发时机与模式：\n- loop:旧关键词\n循环示例：开始时 {"effect": "loop:雨声"}\n\n音效触发时机与模式：\n- stop:旧关键词\n\n可用音效：\n旧音效\n\n音效触发时机与模式：\n- before:旧关键词\n\n可调用工具\n- search',
      },
    ]);
    mockListEffects.mockResolvedValue([
      {
        audio_tags: "特效 1：雨声\n特效 2: 雷声",
        image_list: [],
        image_tags: "",
        image_audio_list: [],
        color: "#4455aa",
        name: "Rain",
      },
    ]);

    renderPage();

    expect(await screen.findByDisplayValue("Opening")).toBeInTheDocument();
    const authoredSystem = (await mockListTemplates.mock.results[0].value)[0].system;

    fireEvent.click(screen.getByRole("button", { name: "Rain" }));
    fireEvent.click(screen.getByRole("button", { name: "Rain" }));

    const sysDialog = await openSystemPromptDialog();
    const systemTemplate = within(sysDialog).getByDisplayValue(/System rules/) as HTMLTextAreaElement;
    expect(systemTemplate).toHaveValue(authoredSystem);
  });

  it("restores and launches memory isolation mode, auto outfit switch, and initial outfits", async () => {
    mockListCharacters.mockResolvedValue([
      {
        color: "#66ccff",
        default_sprite_group: "默认",
        name: "Nanami",
        sprite_groups: ["默认", "校服", "私服"],
        sprites: [
          { group: "校服", path: "D:/sprites/school.png" },
          { group: "私服", path: "D:/sprites/casual.png" },
        ],
      },
    ]);
    mockGetTemplateSession.mockResolvedValue({
      ...savedChat,
      autoOutfitSwitch: false,
      initialOutfits: { Nanami: "私服" },
      mediaSelectionMode: "indexed",
      memoryMode: "inherit_readonly",
    });

    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Template name")).toHaveValue("My saved chat"));

    expect(screen.getByRole("checkbox", { name: "Allow automatic outfit switching" })).not.toBeChecked();
    await clickButton(screen.getByRole("button", { name: "Launch chat" }));

    await waitFor(() =>
      expect(mockLaunchChat).toHaveBeenCalledWith(
        expect.objectContaining({
          autoOutfitSwitch: false,
          initialOutfits: { Nanami: "私服" },
          memoryMode: "inherit_readonly",
        }),
      ),
    );
    expect(mockSaveTemplateSession).toHaveBeenCalledWith(
      expect.objectContaining({
        autoOutfitSwitch: false,
        initialOutfits: { Nanami: "私服" },
        memoryMode: "inherit_readonly",
      }),
    );
  });

  it("discards character selection changes when cancelling CharacterConfigDialog", async () => {
    renderPage();
    await screen.findByDisplayValue("Opening");

    const charDialog = await openCharactersDialog();
    await clickButton(within(charDialog).getByRole("button", { name: "Nanami" }));
    expect(within(charDialog).getByRole("button", { name: "Nanami" })).toHaveAttribute("aria-pressed", "true");
    await clickButton(within(charDialog).getByRole("button", { name: "Cancel" }));

    expect(screen.getByText("No characters selected. Click Edit to choose cast members.")).toBeVisible();
    expect(screen.queryByText("Nanami")).not.toBeInTheDocument();
  });

  it("creates grouped presets, manages groups, appends non-destructively, removes with ×, and reorders via drag-and-drop", async () => {
    let storedLibrary: UserPromptPresetLibrary = {
      groups: ["Style"],
      presets: [
        { id: "p-tone", name: "Light Novel", group: "Style", color: "#5b8def", content: "Use light novel pacing." },
        { id: "p-rule", name: "No Autoplay", group: "", color: "#e879a8", content: "Never speak for player." },
      ],
    };
    mockGetUserPromptPresets.mockImplementation(async () => structuredClone(storedLibrary));
    mockSaveUserPromptPresets.mockImplementation(async (next: UserPromptPresetLibrary) => {
      storedLibrary = structuredClone(next);
      return structuredClone(storedLibrary);
    });

    renderPage({ createOnly: true });
    await screen.findByDisplayValue("Opening");

    // 1. Open Preset Prompts dialog, create a new preset under a brand-new group
    const presetDialog = await openPresetPromptsDialog();
    expect(within(presetDialog).queryByLabelText("Base user prompt")).not.toBeInTheDocument();
    await clickButton(within(presetDialog).getByRole("button", { name: "New preset" }));
    fireEvent.change(within(presetDialog).getByLabelText("Preset name"), { target: { value: "Slow Burn" } });
    fireEvent.click(within(presetDialog).getByRole("combobox", { name: "Group" }));
    fireEvent.click(screen.getByRole("option", { name: "+ New group…" }));
    fireEvent.change(within(presetDialog).getByLabelText("Enter new group name"), { target: { value: "Pacing" } });
    fireEvent.change(within(presetDialog).getByLabelText("Preset text to append"), {
      target: { value: "Advance the plot gently." },
    });
    await clickButton(within(presetDialog).getByRole("button", { name: "Save preset" }));

    await waitFor(() => expect(mockSaveUserPromptPresets).toHaveBeenCalled());
    // Newly created preset is auto-selected and new group tab appears
    expect(within(presetDialog).getByRole("tab", { name: /Pacing/ })).toBeVisible();
    expect(within(presetDialog).getByRole("button", { name: "Slow Burn" })).toHaveAttribute("aria-pressed", "true");

    // 2. Also select "Light Novel" and "No Autoplay"
    await clickButton(within(presetDialog).getByRole("button", { name: "Light Novel" }));
    await clickButton(within(presetDialog).getByRole("button", { name: "No Autoplay" }));

    // Main-page base User prompt textarea remains untouched
    const baseTextarea = screen.getByLabelText("User prompt") as HTMLTextAreaElement;
    expect(baseTextarea).toHaveValue("Morning scene");

    // Remove "No Autoplay" using × button in the append order strip
    await clickButton(within(presetDialog).getByRole("button", { name: "Remove preset No Autoplay" }));
    expect(within(presetDialog).getByRole("button", { name: "No Autoplay" })).toHaveAttribute("aria-pressed", "false");

    // Drag-and-drop "Light Novel" onto "Slow Burn" to swap order -> ["p-tone", createdId]
    const orderList = within(presetDialog).getByRole("list", { name: /Append order/ });
    const orderItems = within(orderList).getAllByRole("listitem");
    expect(orderItems).toHaveLength(2);
    const createdId = orderItems[0].getAttribute("data-preset-id")!;
    expect(orderItems[1].getAttribute("data-preset-id")).toBe("p-tone");

    fireEvent.dragStart(orderItems[1], { dataTransfer: { effectAllowed: "move", setData: vi.fn() } });
    fireEvent.dragOver(orderItems[0], { dataTransfer: { dropEffect: "move" } });
    fireEvent.drop(orderItems[0], { dataTransfer: { getData: () => "p-tone" } });
    fireEvent.dragEnd(orderItems[1]);

    const reorderedItems = within(orderList).getAllByRole("listitem");
    expect(reorderedItems.map((el) => el.getAttribute("data-preset-id"))).toEqual(["p-tone", createdId]);

    // Rename group "Pacing" -> "Tempo", then delete group "Style" (moves Light Novel to Ungrouped)
    await clickButton(within(presetDialog).getByRole("button", { name: "Manage groups" }));
    const groupList = presetDialog.querySelector(".template-preset-group-list") as HTMLElement;
    const pacingRow = within(groupList)
      .getByText(/Pacing \(1\)/)
      .closest("li")!;
    await clickButton(within(pacingRow).getByRole("button", { name: "Rename" }));
    fireEvent.change(within(groupList).getByLabelText("Pacing"), { target: { value: "Tempo" } });
    await clickButton(within(groupList).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(within(presetDialog).getByRole("tab", { name: /Tempo/ })).toBeVisible());

    const styleRow = within(groupList)
      .getByText(/Style \(1\)/)
      .closest("li")!;
    await clickButton(within(styleRow).getByRole("button", { name: "Delete group" }));
    await waitFor(() => expect(storedLibrary.presets.find((p) => p.id === "p-tone")?.group).toBe(""));
    await clickButton(within(presetDialog).getByRole("button", { name: "Done managing groups" }));

    // Check composed preview before confirming
    await clickButton(within(presetDialog).getByRole("button", { name: /Preview composed prompt/ }));
    expect(
      within(presetDialog).getByText("Morning scene\n\nUse light novel pacing.\n\nAdvance the plot gently.", {
        normalizer: (s) => s,
      }),
    ).toBeVisible();

    await clickButton(within(presetDialog).getByRole("button", { name: "Confirm" }));

    // Outer Preset Prompts bar displays selected preset chips and User Prompt card hints append count
    const presetPromptsBar = document.querySelector('[data-section="preset-prompts"]') as HTMLElement;
    const userPromptCard = document.querySelector('[data-section="user-prompt"]') as HTMLElement;
    expect(within(presetPromptsBar).getByText("2 selected")).toBeVisible();
    expect(within(presetPromptsBar).getByText("Light Novel")).toBeVisible();
    expect(within(presetPromptsBar).getByText("Slow Burn")).toBeVisible();
    expect(within(presetPromptsBar).queryByText(/Use light novel pacing/)).not.toBeInTheDocument();
    expect(within(userPromptCard).getByText("+2 presets appended")).toBeVisible();
    expect(baseTextarea).toHaveValue("Morning scene");

    // Opening and cancelling discards unconfirmed preset edits
    const reopened = await openPresetPromptsDialog();
    await clickButton(within(reopened).getByRole("button", { name: "Clear presets" }));
    await clickButton(within(reopened).getByRole("button", { name: "Cancel" }));
    expect(within(presetPromptsBar).getByText("Light Novel")).toBeVisible();

    // Launching forwards composed scenario and preset metadata
    await clickButton(screen.getByRole("button", { name: "Create and start" }));
    await waitFor(() =>
      expect(mockLaunchChat).toHaveBeenCalledWith(
        expect.objectContaining({
          scenario: "Morning scene\n\nUse light novel pacing.\n\nAdvance the plot gently.",
          editorSession: expect.objectContaining({
            baseScenario: "Morning scene",
            selectedPresetIds: ["p-tone", createdId],
          }),
        }),
      ),
    );
  });

  it("retains deleted preset snapshot when editing an existing conversation", async () => {
    mockGetUserPromptPresets.mockResolvedValue({ groups: [], presets: [] });
    mockGetConversationSession.mockResolvedValue({
      ...savedChat,
      baseScenario: "Saved base",
      scenario: "Saved base\n\nDeleted preset text",
      selectedPresetIds: ["p-deleted"],
      appliedPresets: [{ id: "p-deleted", name: "Old Preset", content: "Deleted preset text" }],
    });
    mockReconfigureConversation.mockResolvedValue({ status: "idle", historyPath: savedChat.historyPath });

    renderPage({ conversationId: "chosen", onApplied: vi.fn() });

    const presetPromptsBar = document.querySelector('[data-section="preset-prompts"]') as HTMLElement;
    expect(await within(presetPromptsBar).findByText("Old Preset")).toBeVisible();
    expect(within(presetPromptsBar).getByText("Deleted")).toBeVisible();

    await clickButton(screen.getByRole("button", { name: "Apply and continue" }));
    await waitFor(() =>
      expect(mockReconfigureConversation).toHaveBeenCalledWith(
        "chosen",
        expect.objectContaining({
          scenario: "Saved base\n\nDeleted preset text",
        }),
      ),
    );
  });

  it("protects manually edited system prompt from auto-sync until Regenerate is clicked", async () => {
    mockGenerateTemplate.mockResolvedValue({
      ...template,
      generationMessage: "generated",
      name: "Generated",
      scenario: "Morning scene",
      system: "Regenerated system text",
    });
    renderPage();
    await screen.findByDisplayValue("Opening");

    // Select a character first so auto-sync is eligible
    const charDialog = await openCharactersDialog();
    await clickButton(within(charDialog).getByRole("button", { name: "Nanami" }));
    await clickButton(within(charDialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(mockGenerateTemplate).toHaveBeenCalledTimes(1));

    // Edit system prompt manually inside SystemPromptDialog
    const sysDialog = await openSystemPromptDialog();
    const sysArea = within(sysDialog).getByLabelText("System template");
    fireEvent.change(sysArea, { target: { value: "My handcrafted system prompt" } });
    expect(within(sysDialog).getByText("Manually edited")).toBeVisible();
    await clickButton(within(sysDialog).getByRole("button", { name: "Confirm" }));

    const systemBar = document.querySelector('[data-section="system-prompt"]') as HTMLElement;
    expect(within(systemBar).getByText("Manually edited")).toBeVisible();

    // Changing Use ComfyUI on the right sidebar must NOT overwrite manual system prompt
    const callsBefore = mockGenerateTemplate.mock.calls.length;
    await clickButton(screen.getByRole("checkbox", { name: "Use ComfyUI" }));
    await new Promise((resolve) => window.setTimeout(resolve, 240));
    expect(mockGenerateTemplate).toHaveBeenCalledTimes(callsBefore);
    expect(within(systemBar).getByText("Manually edited · config changed")).toBeVisible();

    // Opening dialog still shows handcrafted text; clicking Regenerate rebuilds and resets Auto-sync
    const sysDialog2 = await openSystemPromptDialog();
    expect(within(sysDialog2).getByDisplayValue("My handcrafted system prompt")).toBeVisible();
    await clickButton(within(sysDialog2).getByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(within(sysDialog2).getByDisplayValue("Regenerated system text")).toBeVisible());
    expect(within(sysDialog2).getByText("Auto-sync")).toBeVisible();
    await clickButton(within(sysDialog2).getByRole("button", { name: "Confirm" }));

    expect(within(systemBar).getByText("Auto-sync")).toBeVisible();
  });

  it("does not auto-pop role picker above 4 characters and preserves compact/full roles when adding a 6th character", async () => {
    const largeCast = Array.from({ length: 6 }, (_, index) => ({
      character_brief: "Existing brief",
      color: "#66ccff",
      name: `Character ${index + 1}`,
    }));
    mockListCharacters.mockResolvedValue(largeCast);
    renderPage();
    await screen.findByDisplayValue("Opening");

    // Select 5 characters in CharacterConfigDialog -> inline role picker does NOT auto-open
    const charDialog = await openCharactersDialog();
    for (const character of largeCast.slice(0, 5)) {
      await clickButton(within(charDialog).getByRole("button", { name: character.name }));
    }
    expect(within(charDialog).getByText("5 selected · roles need to be set")).toBeVisible();
    expect(charDialog.querySelector(".primary-character-dialog__grid")).not.toBeInTheDocument();

    // Open inline role picker manually, toggle Character 2 off -> leaves 3 primary, stays open until Apply roles / Confirm
    await clickButton(within(charDialog).getByRole("button", { name: "Choose primary characters" }));
    expect(charDialog.querySelector(".primary-character-dialog__grid")).toBeInTheDocument();
    const char2RoleCard = within(charDialog)
      .getAllByRole("button", { name: /^Character 2/ })
      .find((btn) => btn.className.includes("primary-character-dialog__card"))!;
    fireEvent.click(char2RoleCard);
    expect(charDialog.querySelector(".primary-character-dialog__grid")).toBeInTheDocument();
    await clickButton(within(charDialog).getByRole("button", { name: "Apply roles" }));
    await clickButton(within(charDialog).getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("3 primary · 2 supporting")).toBeVisible();

    // Reopen and add a 6th character -> preserves compact mode without auto-opening role picker
    const charDialog2 = await openCharactersDialog();
    await clickButton(within(charDialog2).getByRole("button", { name: "Character 6" }));
    expect(within(charDialog2).getByText("3 primary · 3 supporting")).toBeVisible();
    expect(charDialog2.querySelector(".primary-character-dialog__grid")).not.toBeInTheDocument();

    // Confirm generates missing supporting brief for newly added Character 6 and launches directly
    await clickButton(within(charDialog2).getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(mockEnsureCharacterBriefs).toHaveBeenCalledWith(expect.arrayContaining(["Character 6"])),
    );
    expect(await screen.findByText("3 primary · 3 supporting")).toBeVisible();

    await clickButton(screen.getByRole("button", { name: "Launch chat" }));
    expect(screen.queryByRole("dialog", { name: "Choose primary characters" })).not.toBeInTheDocument();
    await waitFor(() => expect(mockLaunchChat).toHaveBeenCalledTimes(1));

    // Switch to "Use all as primary" on 5 characters, then add 6th -> stays full mode
    const charDialog3 = await openCharactersDialog();
    await clickButton(within(charDialog3).getByRole("button", { name: "Character 6" }));
    await clickButton(within(charDialog3).getByRole("button", { name: "Use all as primary" }));
    await clickButton(within(charDialog3).getByRole("button", { name: "Character 6" }));
    expect(within(charDialog3).getByText("6 selected · all are primary")).toBeVisible();
    expect(charDialog3.querySelector(".primary-character-dialog__grid")).not.toBeInTheDocument();
    await clickButton(within(charDialog3).getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("6 selected · all are primary")).toBeVisible();
  });

  it("allows selecting built-in self persona, uploading a player avatar, and switching player avatar sprites", async () => {
    let catalog: Array<{
      color: string;
      emotion_tags: string;
      is_builtin?: boolean;
      name: string;
      portrait_sprite_index?: number;
      sprite_prefix: string;
      sprites: Array<{ path: string }>;
    }> = [
      {
        color: "#8ea8ff",
        emotion_tags: "",
        is_builtin: true,
        name: "自设",
        sprite_prefix: "__self__",
        sprites: [],
      },
      {
        color: "#66ccff",
        emotion_tags: "立绘 1：微笑\n立绘 2：惊讶\n",
        name: "Nanami",
        portrait_sprite_index: 0,
        sprite_prefix: "nanami",
        sprites: [{ path: "D:/sprites/n1.png" }, { path: "D:/sprites/n2.png" }],
      },
    ];
    mockListCharacters.mockImplementation(async () => structuredClone(catalog));
    mockSaveCharacter.mockImplementation(async (next: (typeof catalog)[number]) => {
      catalog = catalog.map((item) => (item.name === next.name ? { ...item, ...next } : item));
      return structuredClone(catalog.find((item) => item.name === next.name) ?? next);
    });
    mockUploadCharacterSprites.mockImplementation(async ({ name, paths }: { name: string; paths: string[] }) => {
      catalog = catalog.map((item) =>
        item.name === name ? { ...item, sprites: [...item.sprites, ...paths.map((path) => ({ path }))] } : item,
      );
      return structuredClone(catalog.find((item) => item.name === name)!);
    });

    renderPage();
    await screen.findByDisplayValue("Opening");

    const charDialog = await openCharactersDialog();
    // Self persona is directly selectable in Player character even before selecting any NPCs
    const playerSelect = within(charDialog).getByRole("combobox", { name: "Player character" });
    fireEvent.click(playerSelect);
    fireEvent.click(screen.getByRole("option", { name: "自设" }));
    expect(within(charDialog).getByRole("button", { name: "自设" })).toHaveAttribute("aria-pressed", "true");
    expect(within(charDialog).getByRole("button", { name: "Adjust player portrait" })).toBeDisabled();

    // Upload an avatar image for self persona
    await clickButton(within(charDialog).getByRole("button", { name: "Upload avatar" }));
    const uploadDialog = await screen.findByRole("dialog", { name: "Upload avatar" });
    await clickButton(within(uploadDialog).getByRole("button", { name: "Choose mocked avatar" }));

    await waitFor(() =>
      expect(mockUploadCharacterSprites).toHaveBeenCalledWith(
        expect.objectContaining({ name: "自设", paths: ["D:/avatars/self.png"] }),
      ),
    );
    await waitFor(() =>
      expect(within(charDialog).getByRole("button", { name: "Adjust player portrait" })).toBeEnabled(),
    );

    // Select Nanami and switch player to Nanami -> shows Player avatar combobox for multiple sprites
    await clickButton(within(charDialog).getByRole("button", { name: "Nanami" }));
    fireEvent.click(within(charDialog).getByRole("combobox", { name: "Player character" }));
    fireEvent.click(screen.getByRole("option", { name: "Nanami" }));

    const avatarSelect = within(charDialog).getByRole("combobox", { name: "Player avatar" });
    fireEvent.click(avatarSelect);
    fireEvent.click(screen.getByRole("option", { name: /n2\.png/ }));
    await waitFor(() =>
      expect(mockSaveCharacter).toHaveBeenCalledWith(
        expect.objectContaining({ name: "Nanami", portrait_sprite_index: 1 }),
        "Nanami",
      ),
    );
  });

  it("preserves saved preset snapshot when global preset with the same ID was edited, unless refreshed in dialog", async () => {
    mockGetUserPromptPresets.mockResolvedValue({
      groups: ["Style"],
      presets: [{ id: "p-tone", name: "Light Novel v2", group: "Style", content: "Global v2 text" }],
    });
    mockGetConversationSession.mockResolvedValue({
      ...savedChat,
      baseScenario: "Saved base",
      scenario: "Saved base\n\nSaved v1 text",
      selectedPresetIds: ["p-tone"],
      appliedPresets: [{ id: "p-tone", name: "Light Novel v1", group: "Style", content: "Saved v1 text" }],
    });
    mockReconfigureConversation.mockResolvedValue({ status: "idle", historyPath: savedChat.historyPath });

    renderPage({ conversationId: "chosen", onApplied: vi.fn() });

    const presetPromptsBar = document.querySelector('[data-section="preset-prompts"]') as HTMLElement;
    expect(await within(presetPromptsBar).findByText("Light Novel v1")).toBeVisible();
    expect(within(presetPromptsBar).queryByText("Deleted")).not.toBeInTheDocument();

    await clickButton(screen.getByRole("button", { name: "Apply and continue" }));
    await waitFor(() =>
      expect(mockReconfigureConversation).toHaveBeenCalledWith(
        "chosen",
        expect.objectContaining({
          scenario: "Saved base\n\nSaved v1 text",
          editorSession: expect.objectContaining({
            appliedPresets: [{ id: "p-tone", name: "Light Novel v1", group: "Style", content: "Saved v1 text" }],
          }),
        }),
      ),
    );

    mockReconfigureConversation.mockClear();
    const dialog = await openPresetPromptsDialog();
    await clickButton(within(dialog).getByRole("button", { name: "Light Novel v2" }));
    await clickButton(within(dialog).getByRole("button", { name: "Light Novel v2" }));
    await clickButton(within(dialog).getByRole("button", { name: "Confirm" }));

    expect(within(presetPromptsBar).getByText("Light Novel v2")).toBeVisible();
    await clickButton(screen.getByRole("button", { name: "Apply and continue" }));
    await waitFor(() =>
      expect(mockReconfigureConversation).toHaveBeenCalledWith(
        "chosen",
        expect.objectContaining({
          scenario: "Saved base\n\nGlobal v2 text",
          editorSession: expect.objectContaining({
            appliedPresets: [{ id: "p-tone", name: "Light Novel v2", group: "Style", content: "Global v2 text" }],
          }),
        }),
      ),
    );
  });

  it("disables preset library editing while presets query is pending or failed so existing presets cannot be overwritten", async () => {
    mockGetUserPromptPresets.mockRejectedValue(new Error("Preset store offline"));

    renderPage({ createOnly: true });
    expect(await screen.findByText("Preset store offline")).toBeVisible();

    const dialog = await openPresetPromptsDialog();
    expect(
      within(dialog).getByText(
        "Failed to load preset library. Editing is disabled to prevent overwriting saved presets.",
      ),
    ).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "New preset" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Manage groups" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(mockSaveUserPromptPresets).not.toHaveBeenCalled();
  });
});
