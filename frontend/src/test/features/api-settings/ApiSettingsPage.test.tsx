import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiSettingsPage } from "../../../features/api-settings/ApiSettingsPage";
import { AppStateProvider } from "../../../shared/app-state/AppState";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { FileBrowserProvider, ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({
  cancelTtsBundleDownload: vi.fn(),
  downloadTtsBundle: vi.fn(),
  fetchLlmModels: vi.fn(),
  getAppConfig: vi.fn(),
  getTtsBundleRecommendation: vi.fn(),
  resumeLastChat: vi.fn(),
  saveApiConfig: vi.fn(),
  saveSystemConfig: vi.fn(),
  showChatSurface: vi.fn(),
  testLlmConnection: vi.fn(),
}));

vi.mock("../../../entities/config/repository", () => ({
  cancelTtsBundleDownload: (...args: unknown[]) => mocks.cancelTtsBundleDownload(...args),
  configQueryKey: ["config"],
  downloadTtsBundle: (...args: unknown[]) => mocks.downloadTtsBundle(...args),
  fetchLlmModels: (...args: unknown[]) => mocks.fetchLlmModels(...args),
  getAppConfig: () => mocks.getAppConfig(),
  getTtsBundleRecommendation: (...args: unknown[]) => mocks.getTtsBundleRecommendation(...args),
  saveApiConfig: (...args: unknown[]) => mocks.saveApiConfig(...args),
  saveSystemConfig: (...args: unknown[]) => mocks.saveSystemConfig(...args),
  testLlmConnection: (...args: unknown[]) => mocks.testLlmConnection(...args),
  ttsBundleRecommendationQueryKey: ["tts", "bundleRecommendation"],
}));

vi.mock("../../../entities/chat/repository", () => ({
  resumeLastChat: () => mocks.resumeLastChat(),
}));

vi.mock("../../../shared/desktop/chatWindow", () => ({
  showChatSurface: () => mocks.showChatSurface(),
}));

function renderPage(children: ReactNode = <ApiSettingsPage />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <FileBrowserProvider browse={vi.fn()}>
          <AppStateProvider>
            <I18nProvider language="zh_CN">{children}</I18nProvider>
          </AppStateProvider>
        </FileBrowserProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function appConfigForTts(ttsProvider: string) {
  return {
    ...sampleConfig,
    api_config: {
      ...sampleConfig.api_config,
      gpt_sovits_api_path: "",
      gpt_sovits_url: "http://127.0.0.1:9880",
      llm_api_key: { Deepseek: "sk-test" },
      llm_model: { Deepseek: "deepseek-chat" },
      tts_provider: ttsProvider,
    },
  };
}

describe("ApiSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getTtsBundleRecommendation.mockResolvedValue({
      gpus: [],
      kind: "genie",
      platform: "linux",
    });
    mocks.fetchLlmModels.mockResolvedValue([]);
    mocks.resumeLastChat.mockResolvedValue({ sessionId: "session-1" });
    mocks.saveApiConfig.mockResolvedValue(sampleConfig.api_config);
    mocks.saveSystemConfig.mockResolvedValue(sampleConfig.system_config);
  });

  it.each([
    ["genie-tts", "Genie TTS 服务启动路径"],
    ["gpt-sovits", "GPT-SoVITS 服务启动路径"],
    ["index-tts", "IndexTTS 服务启动路径"],
  ])("shows a field error when %s startup path is empty", async (ttsProvider, pathLabel) => {
    mocks.getAppConfig.mockResolvedValue(appConfigForTts(ttsProvider));

    renderPage();

    expect(await screen.findByRole("heading", { name: "AI 服务设置" })).toBeInTheDocument();
    expect(screen.getByLabelText(pathLabel)).toHaveValue("");

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(
      await screen.findByText("本地 TTS 引擎需要填写服务启动路径。", { selector: ".field-error" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(mocks.saveApiConfig).not.toHaveBeenCalled());
  });

  it("prefills local TTS startup path from the installed bundle directory", async () => {
    mocks.getAppConfig.mockResolvedValue({
      ...appConfigForTts("genie-tts"),
      tts_bundle_installed_paths: {
        "genie-tts": "/project/data/tts_bundles/installed/genie_tts_server/Genie-TTS-Server",
      },
    });

    renderPage();

    expect(await screen.findByLabelText("Genie TTS 服务启动路径")).toHaveValue(
      "/project/data/tts_bundles/installed/genie_tts_server/Genie-TTS-Server",
    );
  });
});
