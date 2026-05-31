import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToolsPage } from "../../../features/tools/ToolsPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mockListCharacters = vi.fn();

vi.mock("../../../entities/character/repository", () => ({
  charactersQueryKey: ["characters"],
  listCharacters: () => mockListCharacters(),
}));

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <I18nProvider language="zh_CN">
          <ToolsPage />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ToolsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the page title", async () => {
    mockListCharacters.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText("小工具")).toBeInTheDocument();
  });

  it("renders the sprite tools section", async () => {
    mockListCharacters.mockResolvedValue([{ name: "测试角色" }]);
    renderPage();
    expect(await screen.findByText("立绘处理")).toBeInTheDocument();
  });
});
