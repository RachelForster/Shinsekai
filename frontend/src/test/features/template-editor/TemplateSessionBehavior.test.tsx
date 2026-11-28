import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TemplateEditorPage } from "../../../features/template-editor/TemplateEditorPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({
  ensureCharacterBriefs: vi.fn(),
  generateTemplate: vi.fn(),
  getAppConfig: vi.fn(),
  getChatSnapshot: vi.fn(),
  getConversationSession: vi.fn(),
  getMemoryStatus: vi.fn(),
  getTemplateSession: vi.fn(),
  getUserPromptPresets: vi.fn(),
  launchChat: vi.fn(),
  listBackgrounds: vi.fn(),
  listCharacters: vi.fn(),
  listEffects: vi.fn(),
  listPluginSessionBehaviors: vi.fn(),
  listTemplates: vi.fn(),
  saveSystemConfig: vi.fn(),
  saveTemplateSession: vi.fn(),
  showChatSurface: vi.fn(),
  updateRuntimeStatusFromSnapshot: vi.fn(),
}));

vi.mock("../../../entities/background/repository", () => ({
  backgroundsQueryKey: ["backgrounds"],
  listBackgrounds: () => mocks.listBackgrounds(),
}));

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  ensureCharacterBriefs: () => mocks.ensureCharacterBriefs(),
  listCharacters: () => mocks.listCharacters(),
  saveCharacter: vi.fn(),
  uploadCharacterSprites: vi.fn(),
}));

vi.mock("../../../entities/chat/repository", () => ({
  chatQueryKey: ["chat"],
  conversationsQueryKey: ["chat", "conversations"],
  getChatSnapshot: () => mocks.getChatSnapshot(),
  getConversationSession: () => mocks.getConversationSession(),
  installMissingRuntimeDependency: vi.fn(),
  launchChat: (input: unknown) => mocks.launchChat(input),
  reconfigureConversation: vi.fn(),
}));

vi.mock("../../../features/chat-startup/useChatLaunchGuard", () => ({
  useChatLaunchGuard: () => ({
    refreshRuntimeStatus: vi.fn(),
    runtimeLaunchDisabled: false,
    updateRuntimeStatusFromSnapshot: mocks.updateRuntimeStatusFromSnapshot,
  }),
}));

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mocks.getAppConfig(),
  getMemoryStatus: () => mocks.getMemoryStatus(),
  saveSystemConfig: () => mocks.saveSystemConfig(),
}));

vi.mock("../../../entities/template/repository", () => ({
  dialogFormatsQueryKey: ["templates", "dialog-formats"],
  generateTemplate: (input: unknown) => mocks.generateTemplate(input),
  getTemplateSession: () => mocks.getTemplateSession(),
  getUserPromptPresets: () => mocks.getUserPromptPresets(),
  listDialogFormats: () => Promise.resolve([{ builtin: true, id: "xml_v1", label: "XML / HTML Tags" }]),
  listTemplates: () => mocks.listTemplates(),
  saveTemplate: vi.fn(),
  saveTemplateSession: (session: unknown) => mocks.saveTemplateSession(session),
  saveUserPromptPresets: vi.fn(),
  templatesQueryKey: ["templates"],
  userPromptPresetsQueryKey: ["templates", "presets"],
}));

vi.mock("../../../entities/effect/repository", () => ({
  effectsQueryKey: ["effects"],
  listEffects: () => mocks.listEffects(),
}));

vi.mock("../../../entities/plugin/repository", () => ({
  listPluginSessionBehaviors: () => mocks.listPluginSessionBehaviors(),
  pluginSessionBehaviorsQueryKey: ["plugins", "session-behaviors"],
}));

vi.mock("../../../shared/desktop/chatWindow", () => ({
  showChatSurface: (...args: unknown[]) => mocks.showChatSurface(...args),
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

function renderEditor(props: Parameters<typeof TemplateEditorPage>[0] = {}) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  queryClients.add(client);
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <TemplateEditorPage {...props} />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("TemplateEditorPage SessionBehavior selection", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.ensureCharacterBriefs.mockResolvedValue({ characters: [], generatedNames: [] });
    mocks.getUserPromptPresets.mockResolvedValue({ groups: [], presets: [] });
    mocks.saveSystemConfig.mockResolvedValue(structuredClone(sampleConfig.system_config));
    mocks.listTemplates.mockResolvedValue([template]);
    mocks.getTemplateSession.mockResolvedValue(null);
    mocks.getAppConfig.mockResolvedValue(structuredClone(sampleConfig));
    mocks.getMemoryStatus.mockResolvedValue({ modelCached: true, status: "ready" });
    mocks.listCharacters.mockResolvedValue([{ color: "#66ccff", name: "Nanami" }]);
    mocks.listBackgrounds.mockResolvedValue([{ name: "透明场景" }]);
    mocks.listEffects.mockResolvedValue([]);
    mocks.listPluginSessionBehaviors.mockResolvedValue([]);
    mocks.generateTemplate.mockResolvedValue({ ...template, system: "Generated system" });
    mocks.saveTemplateSession.mockImplementation(async (session) => session);
    mocks.launchChat.mockResolvedValue({ dialogText: "launched" });
    mocks.getChatSnapshot.mockResolvedValue({
      dialogText: "",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    });
    mocks.showChatSurface.mockResolvedValue(undefined);
  });

  afterEach(async () => {
    await act(async () => {
      cleanup();
      for (const client of queryClients) client.clear();
      queryClients.clear();
    });
  });

  it("hides the session behavior selector when no behaviors are registered", async () => {
    renderEditor();
    await screen.findByDisplayValue("Opening");
    await waitFor(() => expect(mocks.listPluginSessionBehaviors).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("combobox", { name: "Plugin gameplay mode" })).not.toBeInTheDocument();
  });

  it("selects a plugin session behavior and forwards behaviorId and defaultConfig on launch", async () => {
    mocks.listPluginSessionBehaviors.mockResolvedValue([
      {
        behaviorId: "werewolf",
        defaultConfig: { playerCount: 6 },
        description: "Social deduction host",
        name: "Werewolf Game",
        pluginId: "demo.werewolf",
      },
    ]);

    renderEditor({ conversationTitle: "Night 1", createOnly: true });
    const combobox = await screen.findByRole("combobox", { name: "Plugin gameplay mode" });
    expect(combobox).toHaveTextContent("Default chat mode");

    fireEvent.click(combobox);
    fireEvent.click(await screen.findByRole("option", { name: "Werewolf Game" }));
    expect(combobox).toHaveTextContent("Werewolf Game");
    expect(screen.getByText("Social deduction host")).toBeVisible();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Create and start" }));
    });

    await waitFor(() =>
      expect(mocks.launchChat).toHaveBeenCalledWith(
        expect.objectContaining({
          behaviorConfig: { playerCount: 6 },
          behaviorId: "werewolf",
          editorSession: expect.objectContaining({
            behaviorConfig: { playerCount: 6 },
            behaviorId: "werewolf",
          }),
        }),
      ),
    );
  });

  it("restores saved behaviorId and behaviorConfig on quick restart", async () => {
    mocks.listPluginSessionBehaviors.mockResolvedValue([
      {
        behaviorId: "werewolf",
        defaultConfig: { playerCount: 6 },
        description: "Social deduction host",
        name: "Werewolf Game",
        pluginId: "demo.werewolf",
      },
    ]);
    mocks.getTemplateSession.mockResolvedValue({
      background: "透明场景",
      behaviorConfig: { playerCount: 8 },
      behaviorId: "werewolf",
      effectNames: [],
      filenameStub: "My game",
      historyPath: "D:/history/werewolf",
      initSpritePath: "",
      mediaSelectionMode: "indexed",
      roomId: "",
      scenario: "Morning scene",
      selectedCharacters: ["Nanami"],
      system: "System rules",
      templateFileDropdown: "opening",
      voiceLanguage: "en",
    });

    renderEditor();
    const combobox = await screen.findByRole("combobox", { name: "Plugin gameplay mode" });
    await waitFor(() => expect(combobox).toHaveTextContent("Werewolf Game"));

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Quick restart" }));
    });
    const dialog = screen.getByRole("dialog", { name: "Quick restart" });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Quick restart" }));
    });

    await waitFor(() =>
      expect(mocks.saveTemplateSession).toHaveBeenCalledWith(
        expect.objectContaining({
          behaviorConfig: { playerCount: 8 },
          behaviorId: "werewolf",
        }),
      ),
    );
    expect(mocks.launchChat).toHaveBeenCalledWith(
      expect.objectContaining({
        behaviorConfig: { playerCount: 8 },
        behaviorId: "werewolf",
      }),
    );
  });
});
