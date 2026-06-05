import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AsrSettingsSection } from "../../../features/api-settings/AsrSettingsSection";
import { VOSK_MODEL_PATH } from "../../../features/api-settings/apiSettingsUtils";
import type { ApiConfig, SystemConfig } from "../../../entities/config/types";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

const mocks = {
  openExternal: vi.fn(),
};

vi.mock("../../../entities/files/repository", () => ({
  openExternal: (url: string) => mocks.openExternal(url),
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
});
