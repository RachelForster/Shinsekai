import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  getChatSnapshot: vi.fn(),
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
  chatQueryKey: ["chat"],
  getChatSnapshot: () => mocks.getChatSnapshot(),
  resumeLastChat: () => mocks.resumeLastChat(),
}));

vi.mock("../../../shared/desktop/chatWindow", () => ({
  showChatSurface: (...args: unknown[]) => mocks.showChatSurface(...args),
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

function validAppConfig() {
  return {
    ...sampleConfig,
    api_config: {
      ...sampleConfig.api_config,
      gpt_sovits_api_path: "",
      llm_api_key: { Deepseek: "sk-test" },
      llm_model: { Deepseek: "deepseek-chat" },
      tts_provider: "none",
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
    mocks.getChatSnapshot.mockResolvedValue({
      dialogText: "",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    });
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

  it("saves valid API/system settings and resumes the last chat", async () => {
    const config = validAppConfig();
    mocks.getAppConfig.mockResolvedValue(config);
    mocks.saveApiConfig.mockImplementation(async (api) => api);
    mocks.saveSystemConfig.mockImplementation(async (system) => system);
    mocks.resumeLastChat.mockResolvedValue({
      dialogText: "继续聊天",
      historyPath: "data/chat_history/default.json",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
      statusMessage: "已恢复",
    });

    renderPage();

    expect(await screen.findByRole("heading", { name: "AI 服务设置" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() =>
      expect(mocks.saveApiConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          llm_api_key: { Deepseek: "sk-test" },
          llm_model: { Deepseek: "deepseek-chat" },
          tts_provider: "none",
        }),
      ),
    );
    expect(mocks.saveSystemConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        ui_language: "zh_CN",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "加载上次聊天并启动" }));

    await waitFor(() => expect(mocks.resumeLastChat).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(mocks.showChatSurface).toHaveBeenCalledWith({
        snapshot: expect.objectContaining({ statusMessage: "已恢复" }),
      }),
    );
  });

  it("shows config load errors and retries the settings query", async () => {
    mocks.getAppConfig.mockRejectedValueOnce(new Error("config boom")).mockResolvedValueOnce(validAppConfig());

    renderPage();

    expect(await screen.findByText("操作失败")).toBeInTheDocument();
    expect(screen.getByText("config boom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => expect(mocks.getAppConfig).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("heading", { name: "AI 服务设置" })).toBeInTheDocument();
  });

  it("surfaces save, language, resume, and LLM operation failures", async () => {
    mocks.getAppConfig.mockResolvedValue(validAppConfig());
    mocks.saveApiConfig.mockRejectedValueOnce(new Error("save api boom"));
    mocks.saveSystemConfig.mockRejectedValueOnce(new Error("language boom"));
    mocks.resumeLastChat.mockRejectedValueOnce(new Error("resume boom"));
    mocks.fetchLlmModels.mockRejectedValueOnce(new Error("fetch boom"));
    mocks.testLlmConnection.mockRejectedValueOnce(new Error("test boom"));

    renderPage();

    await screen.findByRole("heading", { name: "AI 服务设置" });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("save api boom")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("combobox")[0]);
    fireEvent.click(screen.getByRole("option", { name: "English" }));
    expect(await screen.findByText("language boom")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "加载上次聊天并启动" }));
    expect(await screen.findByText("resume boom")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("LLM API Key"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "获取可用模型" }));
    expect(await screen.findByText("请先填写 LLM 基础地址和 API Key。")).toBeInTheDocument();
    expect(mocks.fetchLlmModels).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("LLM API Key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByRole("button", { name: "获取可用模型" }));
    expect(await screen.findByText("fetch boom")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("模型 ID"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "连通检测" }));
    const missingModelDialog = await screen.findByRole("dialog", { name: "LLM 连通检测" });
    expect(missingModelDialog).toHaveTextContent("请先填写 LLM 模型 ID。");
    fireEvent.click(within(missingModelDialog).getAllByRole("button", { name: "关闭" })[1]);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "LLM 连通检测" })).not.toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("模型 ID"), { target: { value: "deepseek-chat" } });
    fireEvent.click(screen.getByRole("button", { name: "连通检测" }));

    expect(await screen.findByRole("dialog", { name: "LLM 连通检测" })).toHaveTextContent("test boom");
    expect(screen.getByRole("button", { name: "连通检测" })).toBeInTheDocument();
  });

  it("blocks invalid save payloads before persistence", async () => {
    mocks.getAppConfig.mockResolvedValue(validAppConfig());
    renderPage();

    await screen.findByRole("heading", { name: "AI 服务设置" });

    fireEvent.change(screen.getByLabelText("LLM API Key"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("服务商、基础地址、API Key 和模型 ID 都需要填写。")).toBeInTheDocument();
    expect(mocks.saveApiConfig).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("LLM API Key"), { target: { value: "sk-test" } });
    fireEvent.change(screen.getByLabelText("LLM API 基础网址"), { target: { value: '"https://api.example.test"' } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("LLM API 基础网址不能包含引号。")).toBeInTheDocument();
    expect(mocks.saveApiConfig).not.toHaveBeenCalled();
  });

  it("fetches LLM models and tests the selected connection", async () => {
    mocks.getAppConfig.mockResolvedValue({
      ...validAppConfig(),
      api_config: {
        ...validAppConfig().api_config,
        llm_model: { Deepseek: "" },
      },
    });
    mocks.fetchLlmModels.mockResolvedValue([{ id: "deepseek-chat", tags: ["text", "vision"] }]);
    mocks.testLlmConnection.mockResolvedValue({ message: "连接成功" });

    renderPage();

    await screen.findByRole("heading", { name: "AI 服务设置" });
    fireEvent.click(screen.getByRole("button", { name: "获取可用模型" }));

    await waitFor(() =>
      expect(mocks.fetchLlmModels).toHaveBeenCalledWith({
        apiKey: "sk-test",
        baseUrl: "https://api.deepseek.com/v1",
        provider: "Deepseek",
      }),
    );
    await waitFor(() => expect(screen.getByPlaceholderText("模型 ID")).toHaveValue("deepseek-chat"));
    expect(screen.getByText("Text")).toBeInTheDocument();
    expect(screen.getByText("Vision")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "连通检测" }));

    await waitFor(() =>
      expect(mocks.testLlmConnection).toHaveBeenCalledWith({
        apiKey: "sk-test",
        baseUrl: "https://api.deepseek.com/v1",
        model: "deepseek-chat",
        provider: "Deepseek",
      }),
    );
    expect(await screen.findByRole("dialog", { name: "LLM 连通检测" })).toHaveTextContent("连接成功");
    expect(screen.getByRole("button", { name: "已连通" })).toBeInTheDocument();
  });

  it("downloads a TTS bundle and writes the returned provider path into the draft", async () => {
    mocks.getAppConfig.mockResolvedValue(validAppConfig());
    mocks.getTtsBundleRecommendation.mockResolvedValue({
      gpus: [{ device: "RTX 5090", vendor: "NVIDIA", vram_gb: 32 }],
      kind: "gptso50",
      platform: "Windows 11",
    });
    mocks.downloadTtsBundle.mockImplementation(async (_input, options) => {
      options?.onTaskUpdate?.({
        createdAt: 1,
        id: "tts-task",
        kind: "tts-bundle",
        logs: ["download ok"],
        message: "done",
        phase: "completed",
        progress: 1,
        result: { path: "D:/tts/GPT-SoVITS", provider: "gpt-sovits" },
        status: "succeeded",
        title: "download",
        updatedAt: 2,
      });
      return { path: "D:/tts/GPT-SoVITS", provider: "gpt-sovits" };
    });

    renderPage();

    await screen.findByRole("heading", { name: "AI 服务设置" });
    fireEvent.click(screen.getByRole("button", { name: "选择整合包" }));

    const dialog = await screen.findByRole("dialog", { name: "下载 TTS 整合包" });
    expect(dialog).toHaveTextContent("NVIDIA RTX 5090 / 32 GB");
    expect(dialog).toHaveTextContent("50 系显卡 GPT-SoVITS v2pro");

    fireEvent.click(screen.getByRole("button", { name: "开始下载" }));

    await waitFor(() => expect(mocks.downloadTtsBundle).toHaveBeenCalledWith({ kind: "gptso50" }, expect.any(Object)));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "下载 TTS 整合包" })).not.toBeInTheDocument());
    expect(await screen.findByLabelText("GPT-SoVITS 服务启动路径")).toHaveValue("D:/tts/GPT-SoVITS");
  });

  it("shows TTS bundle failures with manual archive guidance", async () => {
    mocks.getAppConfig.mockResolvedValue(validAppConfig());
    mocks.downloadTtsBundle.mockRejectedValue(new Error("download: 404; archive saved at /tmp/tts.zip"));

    renderPage();

    await screen.findByRole("heading", { name: "AI 服务设置" });
    fireEvent.click(screen.getByRole("button", { name: "选择整合包" }));
    fireEvent.click(await screen.findByRole("button", { name: "开始下载" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("下载失败：404");
    expect(screen.getByRole("alert")).toHaveTextContent("已保留压缩包，可手动解压：/tmp/tts.zip");
  });

  it("cancels a running TTS bundle download task", async () => {
    mocks.getAppConfig.mockResolvedValue(validAppConfig());
    mocks.downloadTtsBundle.mockImplementation(
      (_input, options) =>
        new Promise(() => {
          options?.onTaskUpdate?.({
            createdAt: 1,
            id: "tts-task",
            kind: "tts-bundle",
            logs: ["downloading"],
            message: "running",
            phase: "download",
            progress: 0.5,
            result: null,
            status: "running",
            title: "download",
            updatedAt: 2,
          });
        }),
    );
    mocks.cancelTtsBundleDownload.mockResolvedValue({
      createdAt: 1,
      id: "tts-task",
      kind: "tts-bundle",
      logs: ["cancelled"],
      message: "cancelled",
      phase: "cancelled",
      progress: null,
      result: null,
      status: "cancelled",
      title: "download",
      updatedAt: 3,
    });

    renderPage();

    await screen.findByRole("heading", { name: "AI 服务设置" });
    fireEvent.click(screen.getByRole("button", { name: "选择整合包" }));
    fireEvent.click(await screen.findByRole("button", { name: "开始下载" }));

    const cancelButton = await screen.findByRole("button", { name: "取消下载" });
    fireEvent.click(cancelButton);

    await waitFor(() => expect(mocks.cancelTtsBundleDownload).toHaveBeenCalledWith("tts-task"));
  });
});
