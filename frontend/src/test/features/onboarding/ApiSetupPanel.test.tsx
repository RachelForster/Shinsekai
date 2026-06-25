import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { onboardingCopy } from "../../../features/onboarding/onboardingCopy";
import { ApiSetupPanel } from "../../../features/onboarding/steps/ApiSetupPanel";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import { ToastProvider } from "../../../shared/ui";

const mocks = vi.hoisted(() => ({
  downloadTtsBundle: vi.fn(),
  fetchLlmModels: vi.fn(),
  getAppConfig: vi.fn(),
  getTtsBundleRecommendation: vi.fn(),
  saveApiConfig: vi.fn(),
  testLlmConnection: vi.fn(),
}));

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  downloadTtsBundle: (...args: unknown[]) => mocks.downloadTtsBundle(...args),
  fetchLlmModels: (...args: unknown[]) => mocks.fetchLlmModels(...args),
  getAppConfig: () => mocks.getAppConfig(),
  getTtsBundleRecommendation: (...args: unknown[]) => mocks.getTtsBundleRecommendation(...args),
  saveApiConfig: (...args: unknown[]) => mocks.saveApiConfig(...args),
  testLlmConnection: (...args: unknown[]) => mocks.testLlmConnection(...args),
  ttsBundleRecommendationQueryKey: ["tts", "bundleRecommendation"],
}));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <I18nProvider language="zh_CN">
          <ApiSetupPanel copy={onboardingCopy.zh_CN} />
        </I18nProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function appConfigForOnboarding(overrides: Partial<typeof sampleConfig.api_config> = {}) {
  return {
    ...sampleConfig,
    api_config: {
      ...sampleConfig.api_config,
      llm_api_key: { Deepseek: "sk-test" },
      llm_model: { Deepseek: "deepseek-chat" },
      tts_provider: "", // not configured yet
      gpt_sovits_url: "",
      gpt_sovits_api_path: "",
      ...overrides,
    },
  };
}

describe("ApiSetupPanel TTS bundle flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getTtsBundleRecommendation.mockResolvedValue({
      gpus: [{ device: "RTX 4090", vendor: "NVIDIA", vram_gb: 24 }],
      kind: "gptso",
      platform: "Windows",
    });
    mocks.getAppConfig.mockResolvedValue(appConfigForOnboarding());
    mocks.fetchLlmModels.mockResolvedValue([]);
    mocks.testLlmConnection.mockResolvedValue(undefined);
    mocks.saveApiConfig.mockResolvedValue({
      ...appConfigForOnboarding().api_config,
    });
    mocks.downloadTtsBundle.mockResolvedValue({
      path: "/project/data/tts_bundles/installed/gpt_sovits_v2pro/GPT-SoVITS-v2pro",
      provider: "gpt-sovits",
    });
  });

  it("passes the recommended bundle kind when the user clicks download", async () => {
    renderPanel();

    // Wait for the panel to load (LLM fields visible)
    expect(await screen.findByLabelText("基础地址")).toBeInTheDocument();

    // Click the one-click download button
    const downloadButton = screen.getByRole("button", { name: "一键下载语音包" });
    expect(downloadButton).toBeEnabled();
    fireEvent.click(downloadButton);

    await waitFor(() => {
      expect(mocks.downloadTtsBundle).toHaveBeenCalledTimes(1);
    });

    // The recommended kind "gptso" should be passed, not "genie"
    const [firstArg] = mocks.downloadTtsBundle.mock.calls[0];
    expect(firstArg).toEqual({ kind: "gptso" });
  });

  it("auto-fills TTS provider, URL, and path after successful bundle download", async () => {
    mocks.saveApiConfig.mockImplementation(async (config: Record<string, unknown>) => config);

    renderPanel();
    expect(await screen.findByLabelText("基础地址")).toBeInTheDocument();

    // Trigger download
    fireEvent.click(screen.getByRole("button", { name: "一键下载语音包" }));

    // Wait for download success → auto-save
    await waitFor(() => {
      expect(mocks.saveApiConfig).toHaveBeenCalled();
    });

    const saved = mocks.saveApiConfig.mock.calls[0][0] as Record<string, unknown>;
    expect(saved.tts_provider).toBe("gpt-sovits");
    expect(saved.gpt_sovits_url).toBe("/project/data/tts_bundles/installed/gpt_sovits_v2pro/GPT-SoVITS-v2pro");
    expect(saved.gpt_sovits_api_path).toBe("/project/data/tts_bundles/installed/gpt_sovits_v2pro/GPT-SoVITS-v2pro");
  });

  it("saves successfully after TTS bundle download without validation errors", async () => {
    mocks.saveApiConfig.mockResolvedValue({
      ...appConfigForOnboarding().api_config,
      tts_provider: "gpt-sovits",
      gpt_sovits_url: "/project/data/tts_bundles/installed/gpt_sovits_v2pro/GPT-SoVITS-v2pro",
      gpt_sovits_api_path: "/project/data/tts_bundles/installed/gpt_sovits_v2pro/GPT-SoVITS-v2pro",
    });

    renderPanel();
    expect(await screen.findByLabelText("基础地址")).toBeInTheDocument();

    // Trigger download
    fireEvent.click(screen.getByRole("button", { name: "一键下载语音包" }));

    // Wait for the onSuccess callback to call saveMutation
    await waitFor(() => {
      expect(mocks.saveApiConfig).toHaveBeenCalled();
    });

    // The save should have succeeded (no error toast)
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("saves LLM config without TTS fields triggering validation errors", async () => {
    // User fills in LLM fields but never touches TTS
    mocks.saveApiConfig.mockResolvedValue({
      ...appConfigForOnboarding({
        tts_provider: "",
        gpt_sovits_url: "",
        gpt_sovits_api_path: "",
      }).api_config,
    });

    renderPanel();
    expect(await screen.findByLabelText("基础地址")).toBeInTheDocument();

    // Click save directly (no TTS download)
    const saveButton = screen.getByRole("button", { name: "保存" });
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mocks.saveApiConfig).toHaveBeenCalled();
    });

    const saved = mocks.saveApiConfig.mock.calls[0][0] as Record<string, unknown>;
    // TTS fields are empty — save should still succeed because normalized to "none"
    expect(saved.tts_provider || "").toBe("");
  });

  it("disables the download button while the recommendation is loading", async () => {
    // Recommendation hangs — never resolves during this test
    let resolveRecommendation: (value: unknown) => void = () => {};
    mocks.getTtsBundleRecommendation.mockReturnValue(
      new Promise((resolve) => {
        resolveRecommendation = resolve;
      }),
    );

    renderPanel();
    expect(await screen.findByLabelText("基础地址")).toBeInTheDocument();

    // Button should be disabled while recommendation is still loading
    const downloadButton = screen.getByRole("button", { name: "一键下载语音包" });
    expect(downloadButton).toBeDisabled();

    // Resolve the recommendation
    resolveRecommendation({
      gpus: [{ device: "RTX 4090", vendor: "NVIDIA", vram_gb: 24 }],
      kind: "gptso",
      platform: "Windows",
    });

    await waitFor(() => {
      expect(downloadButton).toBeEnabled();
    });
  });
});
