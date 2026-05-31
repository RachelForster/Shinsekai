import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatLauncherPage } from "../../../features/chat-launcher/ChatLauncherPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mocks = {
  listBackgrounds: vi.fn(),
  listCharacters: vi.fn(),
  listTemplates: vi.fn(),
  getAppConfig: vi.fn(),
  getTemplateSession: vi.fn(),
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
  templatesQueryKey: ["templates"],
  listTemplates: () => mocks.listTemplates(),
  getTemplateSession: () => mocks.getTemplateSession(),
}));
vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mocks.getAppConfig(),
}));

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <I18nProvider language="zh_CN">
          <MemoryRouter>
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
  });

  it("renders the page title", async () => {
    renderPage();
    expect(await screen.findByText("启动聊天")).toBeInTheDocument();
  });
});
