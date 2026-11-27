import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TemplateEditorPage } from "../../../features/template-editor/TemplateEditorPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { sampleConfig } from "../../../shared/platform/sampleData";
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
const mockListDialogFormats = vi.fn();
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

vi.mock("../../../entities/effect/repository", () => ({
  effectsQueryKey: ["effects"],
  listEffects: () => mockListEffects(),
}));

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
  dialogFormatsQueryKey: ["templates", "dialog-formats"],
  generateTemplate: (input: unknown) => mockGenerateTemplate(input),
  getTemplateSession: () => mockGetTemplateSession(),
  getUserPromptPresets: () => mockGetUserPromptPresets(),
  listDialogFormats: () => mockListDialogFormats(),
  listTemplates: () => mockListTemplates(),
  saveTemplate: (input: unknown) => mockSaveTemplate(input),
  saveTemplateSession: (input: unknown) => mockSaveTemplateSession(input),
  saveUserPromptPresets: (library: unknown) => mockSaveUserPromptPresets(library),
  templatesQueryKey: ["templates"],
  userPromptPresetsQueryKey: ["templates", "presets"],
}));

vi.mock("../../../shared/desktop/chatWindow", () => ({
  showChatSurface: (...args: unknown[]) => mockShowChatSurface(...args),
}));

const queryClients = new Set<QueryClient>();

function renderEditor(props: Parameters<typeof TemplateEditorPage>[0] = {}) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  queryClients.add(client);
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="en">
          <TemplateEditorPage {...props} />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("TemplateEditorPage outputFormat selector", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockUseChatLaunchGuard.mockReturnValue({
      refreshRuntimeStatus: mockRefreshRuntimeStatus,
      runtimeLaunchDisabled: false,
      updateRuntimeStatusFromSnapshot: mockUpdateRuntimeStatusFromSnapshot,
    });
    mockListDialogFormats.mockResolvedValue([
      { id: "xml_v1", label: "XML / HTML Tags", builtin: true },
      { id: "json_v1", label: "JSON", builtin: true },
      { id: "custom_dsl", label: "Custom Plugin DSL", builtin: false },
    ]);
    mockListTemplates.mockResolvedValue([]);
    mockGetTemplateSession.mockResolvedValue(null);
    mockGetUserPromptPresets.mockResolvedValue({ groups: [], presets: [] });
    mockSaveUserPromptPresets.mockImplementation(async (lib) => lib);
    mockGetAppConfig.mockResolvedValue(structuredClone(sampleConfig));
    mockGetMemoryStatus.mockResolvedValue({ modelCached: true, status: "ready" });
    mockListCharacters.mockResolvedValue([{ color: "#66ccff", name: "Nanami" }]);
    mockListBackgrounds.mockResolvedValue([{ name: "Room" }]);
    mockListEffects.mockResolvedValue([]);
    mockEnsureCharacterBriefs.mockResolvedValue({ characters: [], generatedNames: [] });
    mockGenerateTemplate.mockResolvedValue({
      content: "Generated scenario\n\nGenerated rules",
      generationMessage: "ok",
      id: "",
      name: "New Template",
      outputFormat: "json_v1",
      path: "",
      scenario: "Generated scenario",
      system: "Generated rules",
      updatedAt: "",
    });
    mockSaveTemplateSession.mockImplementation(async (session) => session);
    mockLaunchChat.mockResolvedValue({ dialogText: "launched" });
    mockGetChatSnapshot.mockResolvedValue({
      dialogText: "",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    });
    mockShowChatSurface.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
    for (const client of queryClients) {
      client.clear();
    }
    queryClients.clear();
  });

  it("defaults new templates to xml_v1 and forwards outputFormat when changed in SystemPromptDialog", async () => {
    renderEditor({ createOnly: true });

    expect(await screen.findByText(/Format: XML \/ HTML Tags/)).toBeInTheDocument();

    const editSystemBtn = await screen.findByRole("button", { name: "Edit system prompt" });
    await act(async () => {
      fireEvent.click(editSystemBtn);
    });
    const dialog = await screen.findByRole("dialog", { name: "Edit system prompt & generation rules" });
    const formatCombo = within(dialog).getByRole("combobox", { name: "Output format" });
    expect(formatCombo).toHaveTextContent("XML / HTML Tags");

    fireEvent.click(formatCombo);
    expect(await screen.findByRole("option", { name: "Custom Plugin DSL" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: /JSON \(classic compatible\)/ }));
    expect(formatCombo).toHaveTextContent("JSON (classic compatible)");

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByText(/Format: JSON \(classic compatible\)/)).toBeInTheDocument());
  });

  it("restores legacy templates without outputFormat as json_v1", async () => {
    mockListTemplates.mockResolvedValue([
      {
        content: "Old scenario\n\nOld system",
        id: "legacy",
        name: "Legacy",
        path: "/templates/legacy.txt",
        scenario: "Old scenario",
        system: "Old system",
        updatedAt: "2025-01-01",
      },
    ]);

    renderEditor();

    expect(await screen.findByText(/Format: JSON \(classic compatible\)/)).toBeInTheDocument();
  });

  it("restores saved xml_v1 template with xml_v1 format", async () => {
    mockListTemplates.mockResolvedValue([
      {
        content: "Modern scenario\n\nModern system",
        id: "modern",
        name: "Modern",
        outputFormat: "xml_v1",
        path: "/templates/modern.txt",
        scenario: "Modern scenario",
        system: "Modern system",
        updatedAt: "2026-11-24",
      },
    ]);

    renderEditor();

    expect(await screen.findByText(/Format: XML \/ HTML Tags/)).toBeInTheDocument();
  });

  it("enforces json_v1 for fresh createOnly drafts when listDialogFormats exposes only json_v1", async () => {
    mockListDialogFormats.mockResolvedValue([{ id: "json_v1", label: "JSON", builtin: true }]);

    renderEditor({ createOnly: true });

    expect(await screen.findByText(/Format: JSON \(classic compatible\)/)).toBeInTheDocument();

    const editSystemBtn = await screen.findByRole("button", { name: "Edit system prompt" });
    await act(async () => {
      fireEvent.click(editSystemBtn);
    });
    const dialog = await screen.findByRole("dialog", { name: "Edit system prompt & generation rules" });
    const formatCombo = within(dialog).getByRole("combobox", { name: "Output format" });
    expect(formatCombo).toHaveTextContent("JSON (classic compatible)");

    fireEvent.click(formatCombo);
    expect(await screen.findByRole("option", { name: /JSON \(classic compatible\)/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /XML/ })).not.toBeInTheDocument();
  });

  it("normalizes restored xml_v1 template and launch session to json_v1 when xml_v1 is unavailable", async () => {
    mockListDialogFormats.mockResolvedValue([{ id: "json_v1", label: "JSON", builtin: true }]);
    mockGetTemplateSession.mockResolvedValue({
      background: "Room",
      outputFormat: "xml_v1",
      selectedCharacters: ["Nanami"],
    });
    mockListTemplates.mockResolvedValue([
      {
        content: "Modern scenario\n\nModern system",
        id: "modern",
        name: "Modern",
        outputFormat: "xml_v1",
        path: "/templates/modern.txt",
        scenario: "Modern scenario",
        system: "Modern system",
        updatedAt: "2026-11-24",
      },
    ]);

    renderEditor();

    expect(await screen.findByText(/Format: JSON \(classic compatible\)/)).toBeInTheDocument();

    const editSystemBtn = await screen.findByRole("button", { name: "Edit system prompt" });
    await act(async () => {
      fireEvent.click(editSystemBtn);
    });
    const dialog = await screen.findByRole("dialog", { name: "Edit system prompt & generation rules" });
    const formatCombo = within(dialog).getByRole("combobox", { name: "Output format" });
    expect(formatCombo).toHaveTextContent("JSON (classic compatible)");

    fireEvent.click(formatCombo);
    expect(screen.queryByRole("option", { name: /XML/ })).not.toBeInTheDocument();
  });
});
