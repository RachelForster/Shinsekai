import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SystemSettingsPage } from "../../../features/system-settings/SystemSettingsPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { AppStateProvider } from "../../../shared/app-state/AppState";
import { FileBrowserProvider, ToastProvider } from "../../../shared/ui";

const mockGetAppConfig = vi.fn();
const mockDetectNetworkProxy = vi.fn();
const mockListChatThemes = vi.fn();
const mockSetActiveChatTheme = vi.fn();
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
  saveSystemConfig: vi.fn(),
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
              <SystemSettingsPage />
            </I18nProvider>
          </AppStateProvider>
        </FileBrowserProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function mockSystemConfig() {
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
    fireEvent.click(themeSelect);
    expect(await screen.findByRole("option", { name: "风旅冒险 · 内置" })).toBeInTheDocument();
    expect(screen.getByText("镜像源")).toBeInTheDocument();
    expect(screen.getByText("系统代理")).toBeInTheDocument();
    expect(screen.getByLabelText("启用代理配置")).toBeInTheDocument();
    expect(screen.getByLabelText("HTTP 代理")).toBeInTheDocument();
    expect(screen.getByLabelText("HTTPS 代理")).toBeInTheDocument();
    expect(screen.getByLabelText("SOCKS5 代理")).toBeInTheDocument();
    expect(screen.queryByText("桌面运行环境")).not.toBeInTheDocument();
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

    expect(await screen.findByText("桌面运行环境")).toBeInTheDocument();
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
