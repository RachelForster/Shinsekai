import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AsrSettingsSection } from "../../../features/api-settings/AsrSettingsSection";
import { VOSK_MODEL_PATH } from "../../../features/api-settings/apiSettingsUtils";
import type { ApiConfig, SystemConfig } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

const mocks = {
  downloadModelAsset: vi.fn(),
  getModelAssetStatus: vi.fn(),
  openExternal: vi.fn(),
};

vi.mock("../../../entities/files/repository", () => ({
  openExternal: (url: string) => mocks.openExternal(url),
}));

vi.mock("../../../entities/model-assets/repository", () => ({
  downloadModelAsset: (input: unknown, options: unknown) => mocks.downloadModelAsset(input, options),
  getModelAssetStatus: (input: unknown) => mocks.getModelAssetStatus(input),
}));

function apiConfig(overrides: Partial<ApiConfig> = {}): ApiConfig {
  return {
    asr_extra_configs: {},
    llm_api_key: {},
    llm_model: {},
    ...overrides,
  } as ApiConfig;
}

function systemConfig(overrides: Partial<SystemConfig> = {}): SystemConfig {
  return {
    asr_language: "",
    asr_provider: "vosk",
    asr_whisper_compute_type: "",
    asr_whisper_device: "auto",
    asr_whisper_model_size: "small",
    ...overrides,
  } as SystemConfig;
}

function renderSection(overrides: Partial<Parameters<typeof AsrSettingsSection>[0]> = {}) {
  const props: Parameters<typeof AsrSettingsSection>[0] = {
    activeAsrProvider: "vosk",
    activeAsrSchema: {},
    asrComputeSelectOptions: [
      { label: "Auto", value: "" },
      { label: "float16", value: "float16" },
    ],
    asrProviderSelectOptions: [
      { label: "Vosk", value: "vosk" },
      { label: "Faster Whisper", value: "faster_whisper" },
    ],
    currentAsrCompute: "",
    customWhisperModel: false,
    disabled: false,
    draft: apiConfig(),
    onAsrExtraChange: vi.fn(),
    onPersistSystemDraft: vi.fn().mockResolvedValue(undefined),
    onSystemPatch: vi.fn(),
    showWhisperFields: false,
    systemDraft: systemConfig(),
    voskModelPath: VOSK_MODEL_PATH,
    whisperPresetValue: "small",
    ...overrides,
  };

  const result = render(
    <I18nProvider language="en">
      <AsrSettingsSection {...props} />
    </I18nProvider>,
  );

  return { props, ...result };
}

describe("AsrSettingsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders Vosk model controls and opens official model resources", () => {
    const { props } = renderSection();

    fireEvent.click(screen.getByRole("button", { name: "Vosk models" }));
    expect(mocks.openExternal).toHaveBeenCalledWith(expect.stringContaining("alphacephei"));

    fireEvent.change(screen.getByDisplayValue(VOSK_MODEL_PATH), { target: { value: "D:/models/vosk" } });
    expect(props.onAsrExtraChange).toHaveBeenCalledWith("vosk", "model_path", "D:/models/vosk");
  });

  it("routes Whisper provider, language, model, device, and compute changes", () => {
    const { props } = renderSection({
      activeAsrProvider: "faster_whisper",
      currentAsrCompute: "",
      showWhisperFields: true,
      systemDraft: systemConfig({ asr_provider: "faster_whisper" }),
      whisperPresetValue: "small",
    });

    const combos = screen.getAllByRole("combobox");
    fireEvent.click(combos[0]);
    fireEvent.click(screen.getByRole("option", { name: "Vosk" }));
    expect(props.onSystemPatch).toHaveBeenCalledWith({ asr_provider: "vosk" });

    fireEvent.click(combos[1]);
    fireEvent.click(screen.getByRole("option", { name: "English" }));
    expect(props.onSystemPatch).toHaveBeenCalledWith({ asr_language: "en" });

    fireEvent.click(combos[2]);
    fireEvent.click(screen.getByRole("option", { name: "large-v3" }));
    expect(props.onSystemPatch).toHaveBeenCalledWith({ asr_whisper_model_size: "large-v3" });

    fireEvent.click(combos[3]);
    fireEvent.click(screen.getByRole("option", { name: "CPU" }));
    expect(props.onSystemPatch).toHaveBeenCalledWith({ asr_whisper_device: "cpu" });

    fireEvent.click(combos[4]);
    fireEvent.click(screen.getByRole("option", { name: "float16" }));
    expect(props.onSystemPatch).toHaveBeenCalledWith({ asr_whisper_compute_type: "float16" });
  });

  it("checks a missing Whisper model, confirms download, and reports cached without claiming it is loaded", async () => {
    const missing = {
      assetId: "asr.faster-whisper",
      cached: false,
      downloadable: true,
      repoId: "Systran/faster-whisper-small",
      source: "huggingface",
      title: "Whisper ASR",
      variant: "small",
    } as const;
    const cached = {
      ...missing,
      cached: true,
      downloaded: true,
      path: "C:/cache/models--Systran--faster-whisper-small/snapshots/abc",
    } as const;
    mocks.getModelAssetStatus.mockResolvedValue(missing);
    mocks.downloadModelAsset.mockImplementation(async (_input, options) => {
      options?.onTaskUpdate?.({
        createdAt: 1,
        id: "whisper-download",
        kind: "model-download",
        logs: [],
        message: "Downloading Whisper",
        phase: "download",
        progress: 0.5,
        result: null,
        status: "running",
        title: "Whisper model",
        updatedAt: 2,
      });
      return cached;
    });

    const { props } = renderSection({
      activeAsrProvider: "faster_whisper",
      showWhisperFields: true,
      systemDraft: systemConfig({ asr_provider: "faster_whisper" }),
      whisperPresetValue: "small",
    });

    fireEvent.click(screen.getByRole("button", { name: "Download/check model" }));

    expect(
      await screen.findByText("The model is not cached yet and must be downloaded before offline loading."),
    ).toBeInTheDocument();
    expect(mocks.getModelAssetStatus).toHaveBeenCalledWith({
      assetId: "asr.faster-whisper",
      variant: "small",
    });
    expect(props.onPersistSystemDraft).not.toHaveBeenCalled();
    expect(screen.getByText("Systran/faster-whisper-small")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Download model" }));

    await waitFor(() => expect(mocks.downloadModelAsset).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText("The model is cached. It will be loaded into memory only when voice input starts."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/model is loaded/i)).not.toBeInTheDocument();
  });

  it("persists custom models before using the configured model asset reference", async () => {
    const persistSystemDraft = vi.fn().mockResolvedValue(undefined);
    const missing = {
      assetId: "asr.faster-whisper",
      cached: false,
      downloadable: true,
      repoId: "owner/custom-whisper",
      source: "huggingface",
      title: "Whisper ASR",
      variant: "owner/custom-whisper",
    } as const;
    mocks.getModelAssetStatus.mockResolvedValue(missing);
    mocks.downloadModelAsset.mockResolvedValue({
      ...missing,
      cached: true,
      downloaded: true,
      path: "C:/cache/custom-whisper",
    });

    renderSection({
      activeAsrProvider: "faster_whisper",
      customWhisperModel: true,
      onPersistSystemDraft: persistSystemDraft,
      showWhisperFields: true,
      systemDraft: systemConfig({
        asr_provider: "faster_whisper",
        asr_whisper_model_size: "owner/custom-whisper",
      }),
      whisperPresetValue: "__custom__",
    });

    fireEvent.click(screen.getByRole("button", { name: "Download/check model" }));
    await screen.findByRole("button", { name: "Download model" });

    expect(persistSystemDraft).toHaveBeenCalledTimes(1);
    expect(mocks.getModelAssetStatus).toHaveBeenCalledWith({
      assetId: "asr.faster-whisper",
      configured: true,
    });
    expect(persistSystemDraft.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.getModelAssetStatus.mock.invocationCallOrder[0],
    );

    fireEvent.click(screen.getByRole("button", { name: "Download model" }));
    await waitFor(() => expect(mocks.downloadModelAsset).toHaveBeenCalledTimes(1));
    expect(mocks.downloadModelAsset).toHaveBeenCalledWith(
      { assetId: "asr.faster-whisper", configured: true },
      expect.any(Object),
    );
  });

  it("does not inspect a custom model when persisting settings fails", async () => {
    renderSection({
      activeAsrProvider: "faster_whisper",
      customWhisperModel: true,
      onPersistSystemDraft: vi.fn().mockRejectedValue(new Error("Could not save ASR settings")),
      showWhisperFields: true,
      systemDraft: systemConfig({
        asr_provider: "faster_whisper",
        asr_whisper_model_size: "C:/models/whisper",
      }),
      whisperPresetValue: "__custom__",
    });

    fireEvent.click(screen.getByRole("button", { name: "Download/check model" }));

    expect(await screen.findByText("Could not save ASR settings")).toBeInTheDocument();
    expect(mocks.getModelAssetStatus).not.toHaveBeenCalled();
  });

  it("lets users close and reopen a long-running model download", async () => {
    const missing = {
      assetId: "asr.faster-whisper",
      cached: false,
      downloadable: true,
      repoId: "Systran/faster-whisper-small",
      source: "huggingface",
      title: "Whisper ASR",
      variant: "small",
    } as const;
    const cached = {
      ...missing,
      cached: true,
      downloaded: true,
      path: "C:/cache/whisper-small",
    } as const;
    let resolveDownload: ((value: typeof cached) => void) | undefined;
    mocks.getModelAssetStatus.mockResolvedValue(missing);
    mocks.downloadModelAsset.mockImplementation(
      (_input, options) =>
        new Promise((resolve) => {
          resolveDownload = resolve;
          options?.onTaskUpdate?.({
            createdAt: 1,
            id: "whisper-download",
            kind: "model-download",
            logs: [],
            message: "10 MB / 20 MB",
            phase: "download",
            progress: 0.5,
            result: null,
            status: "running",
            title: "Whisper model",
            updatedAt: 2,
          });
        }),
    );

    renderSection({
      activeAsrProvider: "faster_whisper",
      showWhisperFields: true,
      systemDraft: systemConfig({ asr_provider: "faster_whisper" }),
      whisperPresetValue: "small",
    });

    fireEvent.click(screen.getByRole("button", { name: "Download/check model" }));
    await screen.findByRole("button", { name: "Download model" });
    fireEvent.click(screen.getByRole("button", { name: "Download model" }));
    expect(await screen.findByText("10 MB / 20 MB")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    const reopenButton = screen.getByRole("button", { name: "View model download progress" });
    expect(reopenButton).toBeEnabled();
    fireEvent.click(reopenButton);
    expect(await screen.findByText("10 MB / 20 MB")).toBeInTheDocument();

    resolveDownload?.(cached);
    expect(
      await screen.findByText("The model is cached. It will be loaded into memory only when voice input starts."),
    ).toBeInTheDocument();
  });
});
