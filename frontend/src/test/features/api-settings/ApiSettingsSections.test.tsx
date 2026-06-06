import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AdapterExtraForm } from "../../../features/api-settings/AdapterExtraForm";
import { ApiLanguageSection } from "../../../features/api-settings/ApiLanguageSection";
import { AsrSettingsSection } from "../../../features/api-settings/AsrSettingsSection";
import { LlmConnectionSection } from "../../../features/api-settings/LlmConnectionSection";
import { ResourceLinksSection } from "../../../features/api-settings/ResourceLinksSection";
import { TtsBundleSection } from "../../../features/api-settings/TtsBundleSection";
import { resourceLinks } from "../../../features/api-settings/apiSettingsUtils";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import type { TaskSnapshot, TtsBundleDownloadResult } from "../../../shared/platform/types";

const filesMock = vi.hoisted(() => ({
  openExternal: vi.fn(),
}));

vi.mock("../../../entities/files/repository", () => ({
  openExternal: filesMock.openExternal,
}));

function renderZh(children: ReactNode) {
  return render(<I18nProvider language="zh_CN">{children}</I18nProvider>);
}

function runningTask(): TaskSnapshot<TtsBundleDownloadResult> {
  return {
    createdAt: 1,
    id: "task-1",
    kind: "tts-bundle",
    logs: ["download"],
    message: "Downloading",
    phase: "download",
    progress: 0.5,
    result: null,
    status: "running",
    title: "Download",
    updatedAt: 2,
  };
}

describe("API settings sections", () => {
  it("renders adapter extra schemas with defaults and emits only the changed field", () => {
    const onChange = vi.fn();
    renderZh(
      <AdapterExtraForm
        onChange={onChange}
        schema={{
          mode: { choices: ["fast", "safe"], default: "safe", label: "Mode", type: "str" },
          temperature: { default: 0.7, label: "Temperature", step: 0.05, type: "float" },
          thinking_enabled: { default: true, label: "Thinking", type: "bool" },
        }}
        values={{}}
      />,
    );

    expect(screen.getByRole("combobox")).toHaveTextContent("safe");
    expect(screen.getByLabelText("Temperature")).toHaveValue(0.7);
    expect(screen.getByRole("checkbox", { name: "Thinking" })).toBeChecked();

    fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.2" } });
    expect(onChange).toHaveBeenCalledWith("temperature", 0.2);
  });

  it("forces unsupported thinking fields off and disabled", () => {
    renderZh(
      <AdapterExtraForm
        modelUnsupportedThinking
        onChange={() => {}}
        schema={{ thinking_enabled: { default: true, label: "Thinking", type: "bool" } }}
        values={{ thinking_enabled: true }}
      />,
    );

    const thinking = screen.getByRole("checkbox", { name: /Thinking/ });
    expect(thinking).not.toBeChecked();
    expect(thinking).toBeDisabled();
    expect(screen.getByText("该模型不支持思考模式。")).toBeInTheDocument();
  });

  it("updates UI language and persists the self-drawn color scheme toggle", () => {
    localStorage.setItem("shinsekai-color-scheme", "light");
    const onChange = vi.fn();

    renderZh(<ApiLanguageSection disabled={false} onChange={onChange} systemDraft={sampleConfig.system_config} />);

    expect(document.documentElement).toHaveAttribute("data-color-scheme", "light");
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "English" }));
    expect(onChange).toHaveBeenCalledWith("en");

    fireEvent.click(screen.getByRole("checkbox"));
    expect(localStorage.getItem("shinsekai-color-scheme")).toBe("dark");
    expect(document.documentElement).toHaveAttribute("data-color-scheme", "dark");
  });

  it("renders Vosk ASR helpers and normalizes provider changes", () => {
    const onSystemPatch = vi.fn();
    renderZh(
      <AsrSettingsSection
        activeAsrProvider="vosk"
        activeAsrSchema={{}}
        asrComputeSelectOptions={[{ label: "自动", value: "" }]}
        asrProviderSelectOptions={[
          { label: "Vosk", value: "vosk" },
          { label: "faster-whisper", value: "faster-whisper" },
        ]}
        currentAsrCompute=""
        customWhisperModel={false}
        disabled={false}
        draft={sampleConfig.api_config}
        onAsrExtraChange={() => {}}
        onSystemPatch={onSystemPatch}
        showWhisperFields={false}
        systemDraft={sampleConfig.system_config}
        whisperPresetValue="base"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Vosk 模型" }));
    expect(filesMock.openExternal).toHaveBeenCalledWith("https://alphacephei.com/vosk/models");

    fireEvent.click(screen.getAllByRole("combobox")[0]);
    fireEvent.click(screen.getByRole("option", { name: "faster-whisper" }));
    expect(onSystemPatch).toHaveBeenCalledWith({ asr_provider: "faster_whisper" });
  });

  it("renders LLM controls, model badges, and forwards field changes", () => {
    const onDraftPatch = vi.fn();
    const onProviderChange = vi.fn();
    const onProviderMapChange = vi.fn();
    const onFetchModels = vi.fn();
    const onTestConnection = vi.fn();

    renderZh(
      <LlmConnectionSection
        activeApiKey="secret"
        activeModel="deepseek-chat"
        availableModelOptions={[{ id: "deepseek-chat", tags: ["text", "vision"] }]}
        disabled={false}
        draft={sampleConfig.api_config}
        connectionOk={false}
        connectionTestPending={false}
        fetchModelsPending={false}
        llmExtraSchema={{ thinking_enabled: { default: true, label: "Thinking", type: "bool" } }}
        llmProviderSelectOptions={[{ label: "Deepseek", value: "Deepseek" }]}
        modelCandidateListId="model-id"
        modelUnsupportedThinking
        onAdapterExtraChange={() => {}}
        onDraftPatch={onDraftPatch}
        onFetchModels={onFetchModels}
        onTestConnection={onTestConnection}
        onProviderChange={onProviderChange}
        onProviderMapChange={onProviderMapChange}
        selectedOption={{ id: "deepseek-chat", tags: ["text", "vision"] }}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "https://api.example.test/v1" },
    });
    expect(onDraftPatch).toHaveBeenCalledWith({ llm_base_url: "https://api.example.test/v1" });

    fireEvent.change(screen.getByDisplayValue("secret"), { target: { value: "new-key" } });
    expect(onProviderMapChange).toHaveBeenCalledWith("llm_api_key", "new-key");

    fireEvent.click(screen.getByRole("button", { name: "获取可用模型" }));
    expect(onFetchModels).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /连通检测/ }));
    expect(onTestConnection).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Text")).toBeInTheDocument();
    expect(screen.getByText("Vision")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Thinking/ })).toBeDisabled();
  });

  it("opens resource links through the platform adapter", () => {
    renderZh(<ResourceLinksSection />);

    fireEvent.click(screen.getByRole("button", { name: "GPT-SOVITS github 源地址" }));

    expect(filesMock.openExternal).toHaveBeenCalledWith(resourceLinks[0][1]);
  });

  it("shows TTS bundle recommendation details and exposes download actions", () => {
    const onCancelDownload = vi.fn();
    const onKindChange = vi.fn();
    const onStartDownload = vi.fn();

    renderZh(
      <TtsBundleSection
        canCancelDownload
        cancelPending={false}
        dialogOpen
        downloadPending={false}
        error="下载失败"
        kind="gptso"
        onCancelDownload={onCancelDownload}
        onCloseDialog={() => {}}
        onKindChange={onKindChange}
        onOpenDialog={() => {}}
        onStartDownload={onStartDownload}
        recommendation={{
          gpus: [{ device: "RTX 4090", vendor: "NVIDIA", vram_gb: 24 }],
          kind: "gptso",
          platform: "linux-x64",
        }}
        recommendationError={false}
        recommendationLoading={false}
        savePending={false}
        task={runningTask()}
      />,
    );

    expect(screen.getByText("NVIDIA RTX 4090 / 24 GB")).toBeInTheDocument();
    expect(screen.getAllByText("GPT-SoVITS v2pro").length).toBeGreaterThan(0);
    expect(screen.getByRole("alert")).toHaveTextContent("下载失败");
    expect(screen.getByRole("status")).toHaveTextContent("50%");

    fireEvent.click(screen.getByRole("button", { name: "取消下载" }));
    fireEvent.click(screen.getByRole("button", { name: "开始下载" }));
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "50 系显卡 GPT-SoVITS v2pro" }));

    expect(onCancelDownload).toHaveBeenCalledTimes(1);
    expect(onStartDownload).toHaveBeenCalledTimes(1);
    expect(onKindChange).toHaveBeenCalledWith("gptso50");
  });
});
