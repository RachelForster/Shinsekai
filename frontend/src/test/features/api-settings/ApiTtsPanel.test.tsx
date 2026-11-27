import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiSettingsPage } from "../../../features/api-settings/ApiSettingsPage";
import { AppStateProvider } from "../../../shared/app-state/AppState";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { FileBrowserProvider, ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({
  getAppConfig: vi.fn(),
  getChatSnapshot: vi.fn(),
  getMemoryStatus: vi.fn(),
  getModelAssetStatus: vi.fn(),
  getTtsBundleRecommendation: vi.fn(),
  refreshRuntimeStatus: vi.fn(),
  saveApiConfig: vi.fn(),
  saveSystemConfig: vi.fn(),
  updateRuntimeStatusFromSnapshot: vi.fn(),
  useChatLaunchGuard: vi.fn(),
}));

vi.mock("../../../entities/config/repository", () => ({
  cancelTtsBundleDownload: vi.fn(),
  configQueryKey: ["config"],
  downloadTtsBundle: vi.fn(),
  fetchLlmModels: vi.fn().mockResolvedValue([]),
  getAppConfig: () => mocks.getAppConfig(),
  getMemoryStatus: (...args: unknown[]) => mocks.getMemoryStatus(...args),
  getTtsBundleRecommendation: (...args: unknown[]) => mocks.getTtsBundleRecommendation(...args),
  saveApiConfig: (...args: unknown[]) => mocks.saveApiConfig(...args),
  saveSystemConfig: (...args: unknown[]) => mocks.saveSystemConfig(...args),
  testComfyuiConnection: vi.fn(),
  testLlmConnection: vi.fn(),
  ttsBundleRecommendationQueryKey: ["tts", "bundleRecommendation"],
}));

vi.mock("../../../entities/chat/repository", () => ({
  chatQueryKey: ["chat"],
  getChatSnapshot: () => mocks.getChatSnapshot(),
  installMissingRuntimeDependency: vi.fn(),
  resumeLastChat: vi.fn(),
}));

vi.mock("../../../features/chat-startup/useChatLaunchGuard", () => ({
  useChatLaunchGuard: () => mocks.useChatLaunchGuard(),
}));

vi.mock("../../../entities/model-assets/repository", () => ({
  downloadModelAsset: vi.fn(),
  getModelAssetStatus: (...args: unknown[]) => mocks.getModelAssetStatus(...args),
}));

vi.mock("../../../shared/desktop/desktopApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../shared/desktop/desktopApi")>()),
  restartDesktopBridge: vi.fn(),
}));

function renderPage(children: ReactNode = <ApiSettingsPage />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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

function configWithFishTts(provider = "fish-audio-s2-pro") {
  return {
    ...sampleConfig,
    adapter_catalog: {
      ...sampleConfig.adapter_catalog!,
      tts: [
        ...sampleConfig.adapter_catalog!.tts,
        {
          label: "Fish Audio S2 Pro",
          schema: {
            api_key: {
              default: "",
              label: "Fish Audio API Key",
              labelKey: "ops.api.tts.fishAudio.extra.apiKey",
              secret: true,
              type: "str",
            },
            base_url: {
              default: "https://api.fish.audio",
              label: "Fish Audio API / Local Server URL",
              labelKey: "ops.api.tts.fishAudio.extra.baseUrl",
              type: "str",
            },
          },
          value: "fish-audio-s2-pro",
        },
      ],
    },
    api_config: {
      ...sampleConfig.api_config,
      gpt_sovits_api_path: "",
      llm_api_key: { Deepseek: "sk-test" },
      llm_model: { Deepseek: "deepseek-chat" },
      tts_provider: provider,
    },
  };
}

describe("ApiTtsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.useChatLaunchGuard.mockReturnValue({
      refreshRuntimeStatus: mocks.refreshRuntimeStatus,
      runtimeLaunchDisabled: false,
      updateRuntimeStatusFromSnapshot: mocks.updateRuntimeStatusFromSnapshot,
    });
    mocks.getTtsBundleRecommendation.mockResolvedValue({ gpus: [], kind: "genie", platform: "linux" });
    mocks.getChatSnapshot.mockResolvedValue({
      dialogText: "",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    });
    mocks.getModelAssetStatus.mockResolvedValue({
      assetId: "asr.faster-whisper",
      cached: false,
      downloadable: true,
      repoId: "owner/custom-whisper",
      source: "huggingface",
      title: "Whisper ASR",
      variant: "owner/custom-whisper",
    });
    mocks.getMemoryStatus.mockResolvedValue({ modelCached: false, status: "not_started" });
    mocks.saveApiConfig.mockImplementation(async (api) => api);
    mocks.saveSystemConfig.mockImplementation(async (sys) => sys);
  });

  afterEach(() => {
    cleanup();
  });

  it("renders collapsible TTS extra options inside the TTS section before vision and links", async () => {
    mocks.getAppConfig.mockResolvedValue(configWithFishTts("fish-audio-s2-pro"));
    renderPage();

    const summary = await screen.findByText("Fish Audio S2 Pro 扩展参数");
    const details = summary.closest("details")!;
    const ttsSettingsHeading = screen.getByRole("heading", { name: "TTS" });
    const ttsSection = ttsSettingsHeading.closest("section")!;
    const visionSection = document.getElementById("api-vision")!;
    const linksSection = document.getElementById("api-links")!;

    expect(details.closest("section")).toBe(ttsSection);
    expect(document.getElementById("api-tts-extra")).toBeNull();
    expect(ttsSection.compareDocumentPosition(visionSection) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(visionSection.compareDocumentPosition(linksSection) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(details.open).toBe(false);

    fireEvent.click(summary);
    expect(details.open).toBe(true);

    const apiKeyInput = screen.getByLabelText("Fish Audio API Key");
    fireEvent.change(apiKeyInput, { target: { value: "sk-fish-updated" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() =>
      expect(mocks.saveApiConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          tts_extra_configs: expect.objectContaining({
            "fish-audio-s2-pro": expect.objectContaining({
              api_key: "sk-fish-updated",
            }),
          }),
        }),
      ),
    );
  });

  it("omits collapsible extra options when the active TTS provider has no schema", async () => {
    mocks.getAppConfig.mockResolvedValue(configWithFishTts("none"));
    renderPage();

    await screen.findByRole("heading", { name: "TTS" });
    expect(document.querySelector(".api-tts-panel__extra")).toBeNull();
  });
});
