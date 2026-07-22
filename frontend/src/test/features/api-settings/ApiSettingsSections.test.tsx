import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdapterExtraForm } from "../../../features/api-settings/AdapterExtraForm";
import { ApiLanguageSection } from "../../../features/api-settings/ApiLanguageSection";
import { AsrSettingsSection } from "../../../features/api-settings/AsrSettingsSection";
import { LlmConnectionSection } from "../../../features/api-settings/LlmConnectionSection";
import { MemorySettingsSection } from "../../../features/api-settings/MemorySettingsSection";
import { ResourceLinksSection } from "../../../features/api-settings/ResourceLinksSection";
import { T2iSetupSection } from "../../../features/api-settings/T2iSetupSection";
import { TtsBundleSection } from "../../../features/api-settings/TtsBundleSection";
import { resourceLinks } from "../../../features/api-settings/apiSettingsUtils";
import { I18nProvider } from "../../../shared/i18n";
import { sampleConfig } from "../../../shared/platform/sampleData";
import type { TaskSnapshot, TtsBundleDownloadResult } from "../../../shared/platform/types";
import { ToastProvider } from "../../../shared/ui";

const filesMock = vi.hoisted(() => ({
  openExternal: vi.fn(),
}));

vi.mock("../../../entities/files/repository", () => ({
  openExternal: filesMock.openExternal,
}));

const modelAssetRepositoryMock = vi.hoisted(() => ({
  downloadModelAsset: vi.fn(),
  getModelAssetStatus: vi.fn(),
}));

vi.mock("../../../entities/model-assets/repository", () => ({
  downloadModelAsset: modelAssetRepositoryMock.downloadModelAsset,
  getModelAssetStatus: modelAssetRepositoryMock.getModelAssetStatus,
}));

const configRepositoryMock = vi.hoisted(() => ({
  getMemoryStatus: vi.fn(),
}));

vi.mock("../../../entities/config/repository", () => ({
  getMemoryStatus: configRepositoryMock.getMemoryStatus,
}));

const runtimeRepositoryMock = vi.hoisted(() => ({
  installMissingRuntimeDependency: vi.fn(),
}));

vi.mock("../../../entities/chat/repository", () => ({
  installMissingRuntimeDependency: runtimeRepositoryMock.installMissingRuntimeDependency,
}));

function renderZh(children: ReactNode) {
  return render(
    <I18nProvider language="zh_CN">
      <ToastProvider>{children}</ToastProvider>
    </I18nProvider>,
  );
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
  beforeEach(() => {
    vi.clearAllMocks();
    configRepositoryMock.getMemoryStatus.mockResolvedValue({ modelCached: false, status: "not_started" });
    runtimeRepositoryMock.installMissingRuntimeDependency.mockResolvedValue({
      message: "installed",
      moduleName: "mem0",
      packageName: "mem0ai",
      pipCode: 0,
      pipOutput: "",
    });
    modelAssetRepositoryMock.getModelAssetStatus.mockResolvedValue({
      assetId: "memory.embedding",
      cached: false,
      downloadable: true,
      repoId: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
      source: "huggingface",
      title: "mem0 embedding model",
      variant: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    });
    modelAssetRepositoryMock.downloadModelAsset.mockResolvedValue({
      assetId: "memory.embedding",
      cached: true,
      downloadable: true,
      downloaded: true,
      path: "C:/cache/memory",
      repoId: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
      source: "huggingface",
      title: "mem0 embedding model",
      variant: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    });
  });

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
        onPersistSystemDraft={() => Promise.resolve()}
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

  it("restores the mem0 and embedding setup status without initializing long-term memory", async () => {
    configRepositoryMock.getMemoryStatus.mockResolvedValue({ modelCached: true, status: "not_started" });
    const props = {
      disabled: false,
      draft: { ...sampleConfig.api_config, memory_auto_enabled: false },
      onChange: vi.fn(),
    };

    const first = renderZh(<MemorySettingsSection {...props} />);
    expect(await screen.findByText("mem0 已就绪 · 模型已就绪")).toBeInTheDocument();
    first.unmount();
    renderZh(<MemorySettingsSection {...props} />);

    expect(await screen.findByText("mem0 已就绪 · 模型已就绪")).toBeInTheDocument();
    expect(configRepositoryMock.getMemoryStatus).toHaveBeenCalledTimes(2);
    expect(configRepositoryMock.getMemoryStatus).toHaveBeenNthCalledWith(1, { startLoading: false });
    expect(configRepositoryMock.getMemoryStatus).toHaveBeenNthCalledWith(2, { startLoading: false });
    expect(runtimeRepositoryMock.installMissingRuntimeDependency).not.toHaveBeenCalled();
    expect(modelAssetRepositoryMock.downloadModelAsset).not.toHaveBeenCalled();
  });

  it("rechecks a cached embedding without creating a download task", async () => {
    configRepositoryMock.getMemoryStatus.mockResolvedValue({ modelCached: true, status: "not_started" });

    renderZh(
      <MemorySettingsSection draft={{ ...sampleConfig.api_config, memory_auto_enabled: false }} onChange={vi.fn()} />,
    );
    await screen.findByText("mem0 已就绪 · 模型已就绪");
    fireEvent.click(screen.getByRole("button", { name: "重新检查" }));

    await waitFor(() => expect(configRepositoryMock.getMemoryStatus).toHaveBeenCalledTimes(2));
    expect(configRepositoryMock.getMemoryStatus).toHaveBeenLastCalledWith({ startLoading: false });
    expect(modelAssetRepositoryMock.downloadModelAsset).not.toHaveBeenCalled();
  });

  it("downloads the embedding through the shared model asset service", async () => {
    let finishDownload!: () => void;
    modelAssetRepositoryMock.downloadModelAsset.mockImplementation(async (_input, options) => {
      options.onTaskUpdate({
        ...runningTask(),
        message: "Downloading mem0 embedding model (128.0 MB / 448.8 MB).",
        phase: "download",
        progress: 0.3,
        status: "running",
      });
      await new Promise<void>((resolve) => {
        finishDownload = resolve;
      });
      return {
        assetId: "memory.embedding",
        cached: true,
        downloadable: true,
        downloaded: true,
        source: "huggingface",
        title: "mem0 embedding model",
        variant: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
      };
    });

    renderZh(
      <MemorySettingsSection draft={{ ...sampleConfig.api_config, memory_auto_enabled: false }} onChange={vi.fn()} />,
    );
    await screen.findByText("mem0 已就绪 · 模型尚未下载");
    fireEvent.click(screen.getByRole("button", { name: "下载模型" }));

    expect((await screen.findAllByText("正在下载长期记忆模型…")).length).toBeGreaterThan(0);
    expect(screen.getByText("mem0 已就绪 · 模型尚未下载")).toBeInTheDocument();
    expect(screen.getByText("Downloading mem0 embedding model (128.0 MB / 448.8 MB).")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "正在下载长期记忆模型…" }));
    expect(modelAssetRepositoryMock.downloadModelAsset).toHaveBeenCalledTimes(1);
    finishDownload();
    expect(await screen.findByText("mem0 已就绪 · 模型已就绪")).toBeInTheDocument();
    expect(modelAssetRepositoryMock.downloadModelAsset).toHaveBeenCalledWith(
      { assetId: "memory.embedding" },
      { onTaskUpdate: expect.any(Function) },
    );
    expect(configRepositoryMock.getMemoryStatus).toHaveBeenCalledTimes(3);
    for (const [options] of configRepositoryMock.getMemoryStatus.mock.calls) {
      expect(options).toEqual({ startLoading: false });
    }
  });

  it("keeps automatic memory disabled and points to model setup when dependencies are missing", async () => {
    const onChange = vi.fn();
    configRepositoryMock.getMemoryStatus.mockResolvedValue({
      moduleName: "mem0",
      packageName: "mem0ai",
      status: "missing_dependency",
    });

    renderZh(
      <MemorySettingsSection draft={{ ...sampleConfig.api_config, memory_auto_enabled: false }} onChange={onChange} />,
    );
    await screen.findByText("缺少 mem0ai 依赖。");
    fireEvent.click(screen.getByRole("checkbox", { name: "启用自动长期记忆" }));

    expect(await screen.findByText("检测到你还没有下载长期记忆依赖，请点击右上角下载模型进行下载")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(runtimeRepositoryMock.installMissingRuntimeDependency).not.toHaveBeenCalled();
    expect(modelAssetRepositoryMock.downloadModelAsset).not.toHaveBeenCalled();
    expect(configRepositoryMock.getMemoryStatus).toHaveBeenCalledTimes(2);
    expect(configRepositoryMock.getMemoryStatus).toHaveBeenLastCalledWith({ startLoading: false });
  });

  it("enables automatic memory after a fresh setup check succeeds", async () => {
    const onChange = vi.fn();
    configRepositoryMock.getMemoryStatus
      .mockResolvedValueOnce({ modelCached: false, status: "not_started" })
      .mockResolvedValueOnce({ modelCached: true, status: "not_started" });

    renderZh(
      <MemorySettingsSection draft={{ ...sampleConfig.api_config, memory_auto_enabled: false }} onChange={onChange} />,
    );
    await screen.findByText("mem0 已就绪 · 模型尚未下载");
    fireEvent.click(screen.getByRole("checkbox", { name: "启用自动长期记忆" }));

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ memory_auto_enabled: true })));
    expect(configRepositoryMock.getMemoryStatus).toHaveBeenCalledTimes(2);
    expect(configRepositoryMock.getMemoryStatus).toHaveBeenLastCalledWith({ startLoading: false });
  });

  it("installs a missing mem0 dependency before downloading the embedding", async () => {
    const missingDependency = {
      moduleName: "mem0",
      packageName: "mem0ai",
      status: "missing_dependency" as const,
    };
    configRepositoryMock.getMemoryStatus
      .mockResolvedValueOnce(missingDependency)
      .mockResolvedValueOnce(missingDependency)
      .mockResolvedValueOnce({ modelCached: false, status: "not_started" })
      .mockResolvedValueOnce({ modelCached: true, status: "not_started" });
    let finishInstall!: () => void;
    runtimeRepositoryMock.installMissingRuntimeDependency.mockImplementation(async (_input, options) => {
      options.onTaskUpdate({
        ...runningTask(),
        kind: "runtime-dependency-install",
        message: "Raw pip output",
        phase: "pip",
      });
      await new Promise<void>((resolve) => {
        finishInstall = resolve;
      });
      return { message: "installed", moduleName: "mem0", packageName: "mem0ai", pipCode: 0, pipOutput: "" };
    });

    renderZh(
      <MemorySettingsSection draft={{ ...sampleConfig.api_config, memory_auto_enabled: false }} onChange={vi.fn()} />,
    );
    await screen.findByText("缺少 mem0ai 依赖。");
    fireEvent.click(screen.getByRole("button", { name: "安装依赖" }));

    expect((await screen.findAllByText("正在安装 mem0ai…")).length).toBeGreaterThan(0);
    expect(screen.getByText("Raw pip output")).toBeInTheDocument();
    finishInstall();

    expect(await screen.findByText("mem0 已就绪 · 模型已就绪")).toBeInTheDocument();
    expect(runtimeRepositoryMock.installMissingRuntimeDependency).toHaveBeenCalledWith(
      { moduleName: "mem0" },
      { onTaskUpdate: expect.any(Function) },
    );
    expect(modelAssetRepositoryMock.downloadModelAsset).toHaveBeenCalledTimes(1);
    for (const [options] of configRepositoryMock.getMemoryStatus.mock.calls) {
      expect(options).toEqual({ startLoading: false });
    }
  });

  it("does not start a second model download while chat is already loading memory", async () => {
    configRepositoryMock.getMemoryStatus.mockResolvedValue({
      modelCached: false,
      status: "loading",
      task: { ...runningTask(), kind: "memory", phase: "download" },
    });

    renderZh(
      <MemorySettingsSection draft={{ ...sampleConfig.api_config, memory_auto_enabled: true }} onChange={vi.fn()} />,
    );
    expect((await screen.findAllByText("正在下载长期记忆模型…")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "重新检查" }));

    await waitFor(() => expect(configRepositoryMock.getMemoryStatus).toHaveBeenCalledTimes(2));
    expect(modelAssetRepositoryMock.downloadModelAsset).not.toHaveBeenCalled();
  });

  it("does not expose an earlier runtime API-key error during setup checks", async () => {
    configRepositoryMock.getMemoryStatus.mockResolvedValue({ message: "Invalid API key: secret", status: "error" });

    renderZh(
      <MemorySettingsSection draft={{ ...sampleConfig.api_config, memory_auto_enabled: true }} onChange={vi.fn()} />,
    );
    expect(await screen.findByText("记忆系统不可用。")).toBeInTheDocument();
    expect(screen.queryByText(/Invalid API key/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新检查" }));

    await waitFor(() => expect(configRepositoryMock.getMemoryStatus).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/Invalid API key/)).not.toBeInTheDocument();
    expect(modelAssetRepositoryMock.downloadModelAsset).not.toHaveBeenCalled();
  });

  it("makes T2I setup optional and applies local ComfyUI defaults", () => {
    const onChange = vi.fn();
    const draft = {
      ...sampleConfig.api_config,
      t2i_api_url: "",
      t2i_default_workflow_path: "",
      t2i_output_node_id: "",
      t2i_prompt_node_id: "",
      t2i_work_path: "",
    };

    renderZh(
      <T2iSetupSection
        disabled={false}
        draft={draft}
        errors={{}}
        extraSchema={{}}
        extraValues={{}}
        onAdapterExtraChange={() => {}}
        onChange={onChange}
        providerOptions={[{ label: "ComfyUI", value: "comfyui" }]}
      />,
    );

    expect(screen.getByRole("radio", { name: /暂不配置/ })).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("radio", { name: /本机 ComfyUI/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        t2i_api_url: "http://127.0.0.1:8188",
        t2i_output_node_id: "9",
        t2i_prompt_node_id: "6",
        t2i_provider: "comfyui",
      }),
    );
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
    fireEvent.click(screen.getAllByRole("option", { name: /GPT-SoVITS v2pro/ })[1]);

    expect(onCancelDownload).toHaveBeenCalledTimes(1);
    expect(onStartDownload).toHaveBeenCalledTimes(1);
    expect(onKindChange).toHaveBeenCalledWith("gptso50");
  });
});
