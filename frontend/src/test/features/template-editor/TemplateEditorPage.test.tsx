import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TemplateEditorPage } from "../../../features/template-editor/TemplateEditorPage";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
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
});
