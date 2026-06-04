import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SystemSettingsPage } from "../../../features/system-settings/SystemSettingsPage";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { AppStateProvider } from "../../../shared/app-state/AppState";
import { FileBrowserProvider, ToastProvider } from "../../../shared/ui";

const mockGetAppConfig = vi.fn();
const browseFiles = vi.fn();
const desktopApi = vi.hoisted(() => ({
  browseDesktopFiles: vi.fn(),
  chooseDesktopRuntimePython: vi.fn(),
  isDesktopBridgeConnectionError: vi.fn(),
  isTauriDesktop: vi.fn(),
  onDesktopRuntimeProgress: vi.fn(),
  repairDesktopRuntime: vi.fn(),
  scanDesktopRuntime: vi.fn(),
  selectDesktopRuntime: vi.fn(),
}));

vi.mock("../../../entities/config/repository", () => ({
  configQueryKey: ["config"],
  getAppConfig: () => mockGetAppConfig(),
  saveSystemConfig: vi.fn(),
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
      font_pixel_size: 0,
      height: 0,
      live_room_id: "",
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
    desktopApi.chooseDesktopRuntimePython.mockResolvedValue({ bridgeUrl: "", candidates: [], status: "needsAction" });
    desktopApi.isDesktopBridgeConnectionError.mockReturnValue(false);
    desktopApi.isTauriDesktop.mockReturnValue(false);
    desktopApi.onDesktopRuntimeProgress.mockResolvedValue(vi.fn());
    desktopApi.repairDesktopRuntime.mockResolvedValue({ bridgeUrl: "", candidates: [], status: "needsAction" });
    desktopApi.scanDesktopRuntime.mockResolvedValue({ bridgeUrl: "", candidates: [], status: "needsAction" });
    desktopApi.selectDesktopRuntime.mockResolvedValue({
      bridgeUrl: "http://127.0.0.1:8787",
      candidates: [],
      status: "ready",
    });
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
  });

  it("shows error state", async () => {
    mockGetAppConfig.mockRejectedValue(new Error("网络错误"));
    renderPage();
    expect(await screen.findByText("操作失败")).toBeInTheDocument();
  });

  it("renders the page title", async () => {
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());
    renderPage();
    expect(await screen.findByText("系统")).toBeInTheDocument();
    expect(screen.queryByText("桌面运行环境")).not.toBeInTheDocument();
  });

  it("manages desktop runtime candidates in the system settings wizard", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    const runtimeView = {
      bridgeUrl: "",
      candidates: [
        {
          id: "python-ready",
          kind: "conda",
          label: "conda env shinsekai",
          managed: false,
          missingImports: [],
          missingPackages: [],
          path: "/opt/miniconda3/envs/shinsekai/bin/python",
          repairActions: ["start"],
          score: 100,
          selected: false,
          status: "ready",
          version: "3.10.20",
          warnings: [],
        },
        {
          id: "python-missing",
          kind: "conda",
          label: "conda env missing deps",
          managed: false,
          missingImports: ["pygame"],
          missingPackages: ["pyyaml"],
          path: "/opt/miniconda3/envs/missing/bin/python",
          repairActions: ["installRuntimeDeps"],
          score: 20,
          selected: false,
          status: "missingCoreDeps",
          version: "3.10.20",
          warnings: [],
        },
      ],
      message: "Python was found, but Shinsekai core dependencies are missing.",
      status: "needsAction",
    };
    desktopApi.scanDesktopRuntime.mockResolvedValue(runtimeView);
    desktopApi.repairDesktopRuntime.mockResolvedValue(runtimeView);
    desktopApi.selectDesktopRuntime.mockResolvedValue(runtimeView);
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());

    renderPage();

    expect(await screen.findByText("桌面运行环境")).toBeInTheDocument();
    expect(await screen.findByText("conda env shinsekai")).toBeInTheDocument();
    expect(screen.getByText("conda env missing deps")).toBeInTheDocument();
    expect(screen.getByText(/pyyaml, pygame/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "安装依赖" }));
    await waitFor(() => {
      expect(desktopApi.repairDesktopRuntime).toHaveBeenCalledWith("python-missing", "installRuntimeDeps");
    });

    fireEvent.click(screen.getByRole("button", { name: "使用此运行环境" }));
    await waitFor(() => {
      expect(desktopApi.selectDesktopRuntime).toHaveBeenCalledWith("python-ready");
    });
  });

  it("uses a manually selected Python runtime path from system settings", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.scanDesktopRuntime.mockResolvedValue({
      bridgeUrl: "",
      candidates: [],
      message: "未找到 Python 运行环境。",
      status: "needsAction",
    });
    mockGetAppConfig.mockResolvedValue(mockSystemConfig());

    renderPage();

    await screen.findByText("未找到 Python 运行环境。");
    fireEvent.change(await screen.findByLabelText("Python 可执行文件"), {
      target: { value: "/opt/python/bin/python" },
    });
    const usePythonButton = screen.getByRole("button", { name: "使用 Python" });
    await waitFor(() => expect(usePythonButton).toBeEnabled());
    fireEvent.click(usePythonButton);

    await waitFor(() => {
      expect(desktopApi.chooseDesktopRuntimePython).toHaveBeenCalledWith("/opt/python/bin/python");
    });
  });
});
