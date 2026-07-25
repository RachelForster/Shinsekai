import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SystemSettingsPage } from "../../../features/system-settings/SystemSettingsPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { AppStateProvider } from "../../../shared/app-state/AppState";
import { FileBrowserProvider, ToastProvider } from "../../../shared/ui";

const mockGetAppConfig = vi.fn();
const mockDetectNetworkProxy = vi.fn();
const mockListChatThemes = vi.fn();
const mockSetActiveChatTheme = vi.fn();
const mockSaveSystemConfig = vi.fn();
const browseFiles = vi.fn();
const desktopApi = vi.hoisted(() => ({
  browseDesktopFiles: vi.fn(),
  getDesktopRuntimeState: vi.fn(),
  installDesktopRuntimeProfile: vi.fn(),
  isDesktopBridgeConnectionError: vi.fn(),
  isTauriDesktop: vi.fn(),
  onDesktopRuntimeProgress: vi.fn(),
  repairDesktopRuntime: vi.fn(),
}));

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  detectNetworkProxy: () => mockDetectNetworkProxy(),
  getAppConfig: () => mockGetAppConfig(),
  saveSystemConfig: (config: unknown) => mockSaveSystemConfig(config),
}));

vi.mock("../../../entities/chat/repository", () => ({
  chatThemeQueryKey: ["chat", "themes"],
  listChatThemes: () => mockListChatThemes(),
  setActiveChatTheme: (id: string) => mockSetActiveChatTheme(id),
}));

vi.mock("../../../shared/desktop/desktopApi", () => desktopApi);

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <FileBrowserProvider browse={browseFiles}>
          <AppStateProvider>
            <I18nProvider language="zh_CN">
              <MemoryRouter initialEntries={["/settings/system"]}>
                <Routes>
                  <Route element={<SystemSettingsPage />} path="/settings/system" />
                  <Route element={<h1>Theme management destination</h1>} path="/settings/system/chat-themes" />
                </Routes>
              </MemoryRouter>
            </I18nProvider>
          </AppStateProvider>
        </FileBrowserProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function mockSystemConfig(systemOverrides: Record<string, unknown> = {}) {
  return {
    system_config: {
      asr_language: "",
      asr_provider: "vosk",
      asr_whisper_compute_type: "",
      asr_whisper_device: "auto",
      asr_whisper_model_size: "base",
      chat_ui_runtime_mode: "react",
      chat_ui_theme_id: "windborne-adventure",
      chat_ui_theme_path: "",
      react_chat_fork_experimental_enabled: false,
      react_chat_flowchart_experimental_enabled: false,
      font_pixel_size: 0,
      height: 0,
      live_room_id: "",
      mirror_auto_detect_china: true,
      mirror_region: "auto",
      huggingface_mirror_url: "",
      huggingface_cache_dir: "./data/cache/huggingface",
      github_mirror_url: "",
      pypi_mirror_url: "",
      network_proxy_enabled: false,
      http_proxy_url: "",
      https_proxy_url: "",
      socks5_proxy_url: "",
      settings_window_height: 0,
      settings_window_width: 0,
      splash_duration: 75,
      system_name: "",
      ui_language: "zh_CN",
      voice_language: "ja",
      width: 0,
      ...systemOverrides,
    },
  };
}

describe("SystemSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    desktopApi.getDesktopRuntimeState.mockResolvedValue({ bridgeUrl: "", candidates: [], status: "needsAction" });
    desktopApi.installDesktopRuntimeProfile.mockResolvedValue({ bridgeUrl: "", candidates: [], status: "needsAction" });
    desktopApi.isDesktopBridgeConnectionError.mockReturnValue(false);
    desktopApi.isTauriDesktop.mockReturnValue(false);
    desktopApi.onDesktopRuntimeProgress.mockResolvedValue(vi.fn());
    desktopApi.repairDesktopRuntime.mockResolvedValue({ bridgeUrl: "", candidates: [], status: "needsAction" });
    desktopApi.browseDesktopFiles.mockResolvedValue({
      cwd: "/tmp",
      entries: [
        {
          kind: "file",
          modifiedAt: 1,
          name: "shinsekai-runtime-linux-x64.tar.gz",
          path: "/tmp/shinsekai-runtime-linux-x64.tar.gz",
          size: 1024,
        },
      ],
      parent: "/",
      roots: [{ label: "Temp", path: "/tmp" }],
    });
    browseFiles.mockResolvedValue({
      cwd: "/tmp",
      entries: [
        {
          kind: "file",
          modifiedAt: 1,
          name: "shinsekai-runtime-linux-x64.tar.gz",
          path: "/tmp/shinsekai-runtime-linux-x64.tar.gz",
          size: 1024,
        },
      ],
      parent: "/",
      roots: [{ label: "Temp", path: "/tmp" }],
    });
    mockListChatThemes.mockResolvedValue([
      {
        id: "windborne-adventure",
        name: { en: "Windborne Adventure", zh_CN: "风旅冒险" },
        source: "builtin",
      },
    ]);
    mockSetActiveChatTheme.mockResolvedValue(undefined);
    mockSaveSystemConfig.mockImplementation(async (config) => config);
    mockDetectNetworkProxy.mockResolvedValue({
      http_proxy_url: "",
      https_proxy_url: "",
      socks5_proxy_url: "",
      source: "",
    });
  });

  it("shows error state", async () => {
    mockGetAppConfig.mockRejectedValue(new Error("网络错误"));
    renderPage();
    expect(await screen.findByText("操作失败")).toBeInTheDocument();
  });

  it("renders the page title", async () => {
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());
    renderPage();
    expect(await screen.findByText("程序设置")).toBeInTheDocument();
    const themeSelect = await screen.findByRole("combobox", { name: "聊天主题" });
    await waitFor(() => expect(themeSelect).toHaveTextContent("风旅冒险 · 内置"));
    const sectionGuide = screen.getByRole("navigation", { name: "程序设置" });
    expect(within(sectionGuide).getByRole("button", { name: "界面" })).toBeInTheDocument();
    expect(within(sectionGuide).getByRole("button", { name: "聊天主题" })).toBeInTheDocument();
    expect(within(sectionGuide).getByRole("button", { name: "系统代理" })).toBeInTheDocument();
    expect(within(sectionGuide).getByRole("button", { name: "镜像源" })).toBeInTheDocument();
    expect(within(sectionGuide).getByRole("button", { name: "媒体与直播" })).toBeInTheDocument();
    expect(document.getElementById("system-ui")).toHaveClass("page-section-anchor");
    expect(document.getElementById("system-chat-theme")).toHaveClass("page-section-anchor");
    expect(document.getElementById("system-network-proxy")).toHaveClass("page-section-anchor");
    expect(screen.getByRole("button", { name: "主题管理" })).toBeInTheDocument();
    fireEvent.click(themeSelect);
    expect(await screen.findByRole("option", { name: "风旅冒险 · 内置" })).toBeInTheDocument();
    const uiHeading = screen.getByRole("heading", { name: "界面" });
    const themeHeading = screen.getByRole("heading", { name: "聊天主题" });
    const proxyHeading = screen.getByRole("heading", { name: "系统代理" });
    expect(screen.getByRole("heading", { name: "镜像源" })).toBeInTheDocument();
    expect(proxyHeading).toBeInTheDocument();
    expect(uiHeading.compareDocumentPosition(themeHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(themeHeading.compareDocumentPosition(proxyHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("这是 React Stage 的聊天主题。")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "聊天界面模式" })).not.toBeInTheDocument();
    expect(screen.queryByText("原生窗口")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("原生聊天主题 JSON")).not.toBeInTheDocument();
    expect(screen.getByLabelText("启用代理配置")).toBeInTheDocument();
    expect(screen.getByLabelText("HTTP 代理")).toBeInTheDocument();
    expect(screen.getByLabelText("HTTPS 代理")).toBeInTheDocument();
    expect(screen.getByLabelText("SOCKS5 代理")).toBeInTheDocument();
    expect(screen.queryByText("桌面运行环境")).not.toBeInTheDocument();
  });

  it("navigates to the standalone chat theme management page", async () => {
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "主题管理" }));

    expect(await screen.findByRole("heading", { name: "Theme management destination" })).toBeInTheDocument();
  });

  it("migrates a legacy native setting to the React chat UI", async () => {
    mockGetAppConfig.mockResolvedValue(
      mockSystemConfig({
        chat_ui_runtime_mode: "native",
      }),
    );
    renderPage();

    const themeSelect = await screen.findByRole("combobox", { name: "聊天主题" });

    expect(themeSelect).toBeEnabled();
    expect(screen.queryByRole("combobox", { name: "聊天界面模式" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() =>
      expect(mockSaveSystemConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          chat_ui_runtime_mode: "react",
        }),
      ),
    );
  });

  it("detects the current system proxy into the draft", async () => {
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());
    mockDetectNetworkProxy.mockResolvedValue({
      http_proxy_url: "http://127.0.0.1:7890",
      https_proxy_url: "http://127.0.0.1:7890",
      socks5_proxy_url: "socks5://127.0.0.1:7891",
      source: "environment",
    });
    renderPage();

    await screen.findByText("程序设置");
    expect(screen.getByLabelText("HTTP 代理")).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "检测当前系统代理" }));

    await waitFor(() => expect(mockDetectNetworkProxy).toHaveBeenCalled());
    expect(screen.getByLabelText("启用代理配置")).toBeChecked();
    expect(screen.getByLabelText("HTTP 代理")).toHaveValue("http://127.0.0.1:7890");
    expect(screen.getByLabelText("HTTPS 代理")).toHaveValue("http://127.0.0.1:7890");
    expect(screen.getByLabelText("SOCKS5 代理")).toHaveValue("socks5://127.0.0.1:7891");
  });

  it("shows only the active desktop runtime and installs optional runtime profiles", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    const runtimeView = {
      bridgeUrl: "",
      candidates: [
        {
          id: "python-ready",
          displayPath: "C:\\Shinsekai\\runtime\\python.exe",
          kind: "managed",
          label: "Shinsekai bundled runtime",
          managed: true,
          missingImports: [],
          missingPackages: [],
          path: "\\\\?\\C:\\Shinsekai\\runtime\\python.exe",
          repairActions: ["start"],
          score: 100,
          selected: true,
          status: "ready",
          version: "3.10.20",
          warnings: [],
        },
        {
          id: "python-missing",
          kind: "managed",
          label: "Shinsekai managed runtime",
          managed: true,
          missingImports: ["pygame"],
          missingPackages: ["pyyaml"],
          path: "/home/user/.local/share/Shinsekai/runtime/bin/python3",
          repairActions: ["installRuntimeDeps"],
          score: 20,
          selected: false,
          status: "missingCoreDeps",
          version: "3.10.20",
          warnings: [],
        },
      ],
      selectedCandidateId: "python-ready",
      status: "ready",
    };
    desktopApi.getDesktopRuntimeState.mockResolvedValue(runtimeView);
    desktopApi.installDesktopRuntimeProfile.mockResolvedValue(runtimeView);
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());

    renderPage();

    expect(await screen.findByRole("heading", { name: "桌面运行环境" })).toBeInTheDocument();
    expect(await screen.findByText("Shinsekai bundled runtime")).toBeInTheDocument();
    expect(screen.queryByText("Shinsekai managed runtime")).not.toBeInTheDocument();
    expect(screen.getByText("C:\\Shinsekai\\runtime\\python.exe")).toBeInTheDocument();
    expect(screen.queryByText(/\\\\\?/)).not.toBeInTheDocument();
    expect(screen.queryByText(/pyyaml, pygame/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "安装媒体运行环境" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "安装本地 AI 运行环境" }));
    await waitFor(() => {
      expect(desktopApi.installDesktopRuntimeProfile).toHaveBeenCalledWith("local-ai");
    });
  });

  it("does not offer manual Python selection from system settings", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      candidates: [],
      message: "未找到安装目录 runtime 运行环境。",
      status: "needsAction",
    });
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());

    renderPage();

    await screen.findByText("未找到安装目录 runtime 运行环境。");
    expect(screen.queryByLabelText("Python 可执行文件")).not.toBeInTheDocument();
  });

  it("repairs core dependencies for the current desktop runtime", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    const runtimeView = {
      bridgeUrl: "",
      candidates: [
        {
          id: "install-dir-runtime",
          displayPath: "C:\\Shinsekai\\runtime\\python.exe",
          kind: "managed",
          label: "Shinsekai bundled runtime",
          managed: true,
          missingImports: [],
          missingPackages: [],
          path: "\\\\?\\C:\\Shinsekai\\runtime\\python.exe",
          repairActions: ["start"],
          score: 100,
          selected: true,
          status: "ready",
          version: "3.10.20",
          warnings: [],
        },
      ],
      selectedCandidateId: "install-dir-runtime",
      status: "ready",
    };
    desktopApi.getDesktopRuntimeState.mockResolvedValue(runtimeView);
    desktopApi.repairDesktopRuntime.mockResolvedValue(runtimeView);
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());

    renderPage();

    const repairButton = await screen.findByRole("button", { name: "修复核心依赖" });
    await screen.findByText("Shinsekai bundled runtime");
    await waitFor(() => {
      expect(repairButton).toBeEnabled();
    });

    fireEvent.click(repairButton);
    await waitFor(() => {
      expect(desktopApi.repairDesktopRuntime).toHaveBeenCalledWith("install-dir-runtime", "installRuntimeDeps");
    });
  });
});
