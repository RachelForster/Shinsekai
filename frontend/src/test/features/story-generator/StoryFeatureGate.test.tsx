import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StoryFeatureGate } from "../../../features/story-generator/components/StoryFeatureGate";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { I18nProvider, type FrontendLanguage } from "../../../shared/i18n";

const { getAppConfig, saveSystemConfig } = vi.hoisted(() => ({ getAppConfig: vi.fn(), saveSystemConfig: vi.fn() }));
vi.mock("../../../entities/config/repository", () => ({ configQueryKey: ["config"], getAppConfig, saveSystemConfig }));
function renderGate(language: FrontendLanguage = "zh_CN") {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nProvider language={language}>
        <StoryFeatureGate>
          <p>创作工作区</p>
        </StoryFeatureGate>
      </I18nProvider>
    </QueryClientProvider>,
  );
}
describe("story feature activation", () => {
  it("localizes activation and retry actions when settings fail to load", async () => {
    getAppConfig.mockRejectedValue(new Error("Connection lost"));
    renderGate("en");
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
    expect(screen.getByRole("button", { name: "Enable story mode" })).toBeDisabled();
    getAppConfig.mockResolvedValue(sampleConfig);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Enable story mode" })).toBeVisible();
  });
  beforeEach(() => {
    vi.resetAllMocks();
    getAppConfig.mockResolvedValue(sampleConfig);
  });
  it("waits for explicit activation and a successful config refresh", async () => {
    saveSystemConfig.mockImplementation(async () => {
      getAppConfig.mockResolvedValue({
        ...sampleConfig,
        system_config: { ...sampleConfig.system_config, story_system_enabled: true },
      });
    });
    renderGate();
    expect(screen.queryByText("创作工作区")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "启用剧本模式" }));
    expect(await screen.findByText("创作工作区")).toBeVisible();
    expect(saveSystemConfig).toHaveBeenCalledWith({ ...sampleConfig.system_config, story_system_enabled: true });
  });
  it("shows save failure without unlocking generation", async () => {
    saveSystemConfig.mockRejectedValue(new Error("设置写入失败"));
    renderGate();
    fireEvent.click(await screen.findByRole("button", { name: "启用剧本模式" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("设置写入失败");
    expect(screen.queryByText("创作工作区")).not.toBeInTheDocument();
  });
});
