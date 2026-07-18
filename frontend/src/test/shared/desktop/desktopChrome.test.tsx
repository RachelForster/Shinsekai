import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const desktopApi = vi.hoisted(() => ({
  browseDesktopFiles: vi.fn(),
  closeDesktopWindow: vi.fn<() => Promise<void>>(),
  desktopRestartErrorMessage: vi.fn((error: unknown) => (error instanceof Error ? error.message : String(error))),
  getDesktopProjectRootStatus: vi.fn(),
  getDesktopRuntimeState: vi.fn(),
  isDesktopBridgeConnectionError: vi.fn(() => false),
  isTauriDesktop: vi.fn(),
  minimizeDesktopWindow: vi.fn<() => Promise<void>>(),
  onDesktopRuntimeProgress: vi.fn(),
  repairDesktopRuntime: vi.fn(),
  restartDesktopApp: vi.fn<() => Promise<void>>(),
  selectDesktopProjectRoot: vi.fn(),
  startDesktopWindowDrag: vi.fn<() => Promise<void>>(),
  toggleMaximizeDesktopWindow: vi.fn<() => Promise<void>>(),
}));

vi.mock("../../../shared/desktop/desktopApi", () => desktopApi);

import { DesktopChrome } from "../../../shared/desktop/DesktopChrome";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";

const safeProjectRootStatus = {
  candidates: [
    {
      hasProjectData: true,
      path: "C:\\Users\\test\\Shinsekai",
      selectable: true,
      source: "persistedLocator",
    },
  ],
  conflict: false,
  currentPath: "C:\\Users\\test\\Shinsekai",
  locatorPath: "C:\\Users\\test\\project-root.json",
  requiresSelection: false,
};

const conflictingProjectRootStatus = {
  candidates: [
    {
      hasProjectData: true,
      path: "C:\\Users\\test\\Shinsekai",
      selectable: true,
      source: "currentAppData",
    },
    {
      hasProjectData: true,
      path: "D:\\旧数据\\Shinsekai",
      selectable: true,
      source: "restartLogProjectRoot",
    },
  ],
  conflict: true,
  currentPath: "C:\\Users\\test\\Shinsekai",
  locatorPath: "C:\\Users\\test\\project-root.json",
  requiresSelection: true,
};

function renderChrome(children: ReactNode, initialEntries = ["/settings/api"]) {
  return render(
    <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }} initialEntries={initialEntries}>
      <I18nProvider language="en">
        <DesktopChrome>{children}</DesktopChrome>
      </I18nProvider>
    </MemoryRouter>,
  );
}

describe("DesktopChrome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: async () => ({ ok: true }),
        ok: true,
      }),
    );
    desktopApi.closeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.getDesktopProjectRootStatus.mockResolvedValue(safeProjectRootStatus);
    desktopApi.minimizeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.onDesktopRuntimeProgress.mockResolvedValue(vi.fn());
    desktopApi.repairDesktopRuntime.mockResolvedValue({
      bridgeUrl: "http://127.0.0.1:8787",
      candidates: [],
      status: "ready",
    });
    desktopApi.startDesktopWindowDrag.mockResolvedValue(undefined);
    desktopApi.toggleMaximizeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "http://127.0.0.1:8787",
      candidates: [],
      status: "ready",
    });
    desktopApi.isTauriDesktop.mockReturnValue(false);
    desktopApi.browseDesktopFiles.mockResolvedValue({
      cwd: "/tmp",
      entries: [
        {
          kind: "directory",
          modifiedAt: 1,
          name: "runtime",
          path: "/tmp/runtime",
        },
        {
          kind: "file",
          modifiedAt: 1,
          name: "shinsekai-runtime-linux-x64.tar.gz",
          path: "/tmp/shinsekai-runtime-linux-x64.tar.gz",
          size: 1024,
        },
        {
          kind: "file",
          modifiedAt: 1,
          name: "notes.txt",
          path: "/tmp/notes.txt",
          size: 1024,
        },
      ],
      parent: "/",
      roots: [{ label: "Temp", path: "/tmp" }],
    });
  });

  it("renders plain children outside the Tauri desktop shell", () => {
    renderChrome(<main>App content</main>);

    expect(screen.getByText("App content")).toBeInTheDocument();
    expect(screen.queryByText("Shinsekai")).not.toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).not.toHaveBeenCalled();
  });

  it("renders the custom title bar after the desktop runtime is ready", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);

    renderChrome(<main>App content</main>);

    expect(await screen.findByText("Shinsekai")).toBeInTheDocument();
    expect(await screen.findByText("App content")).toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).toHaveBeenCalledTimes(1);
  });

  it("blocks the runtime gate and child providers until a project root is selected", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopProjectRootStatus.mockResolvedValue(conflictingProjectRootStatus);
    const childRender = vi.fn();
    const RuntimeChild = () => {
      childRender();
      return <main>Runtime-dependent content</main>;
    };

    renderChrome(<RuntimeChild />);

    expect(await screen.findByRole("dialog", { name: "Choose project data location" })).toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).not.toHaveBeenCalled();
    expect(childRender).not.toHaveBeenCalled();
    expect(screen.queryByText("Runtime-dependent content")).not.toBeInTheDocument();
  });

  it("bypasses desktop chrome for standalone chat routes", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);

    renderChrome(<main>Chat stage</main>, ["/chat-stage"]);

    expect(await screen.findByText("Chat stage")).toBeInTheDocument();
    expect(screen.queryByText("Shinsekai")).not.toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).not.toHaveBeenCalled();
  });

  it("still requires project-root selection before mounting a standalone chat route", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopProjectRootStatus.mockResolvedValue(conflictingProjectRootStatus);
    const childRender = vi.fn();
    const ChatChild = () => {
      childRender();
      return <main>Chat stage</main>;
    };

    renderChrome(<ChatChild />, ["/chat-stage"]);

    expect(await screen.findByRole("dialog", { name: "Choose project data location" })).toBeInTheDocument();
    expect(childRender).not.toHaveBeenCalled();
    expect(screen.queryByText("Chat stage")).not.toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).not.toHaveBeenCalled();
  });

  it("bypasses desktop chrome for the /chat route as well", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);

    renderChrome(<main>Live chat</main>, ["/chat"]);

    expect(await screen.findByText("Live chat")).toBeInTheDocument();
    expect(screen.queryByText("Shinsekai")).not.toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).not.toHaveBeenCalled();
  });

  it("keeps the runtime gate open when the bundled runtime is unavailable", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      candidates: [],
      message: "缺少 Python 运行环境",
      status: "missing",
    });

    renderChrome(<main>App content</main>);

    expect(await screen.findByText("Runtime update required")).toBeInTheDocument();
    expect(screen.getByText("缺少 Python 运行环境")).toBeInTheDocument();
    expect(screen.queryByText("App content")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Python executable")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Update" })).not.toBeInTheDocument();
  });

  it("does not show a manual dependency command for a bridge startup error", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      candidates: [
        {
          id: "python-ready",
          displayPath: "C:\\Users\\test\\Shinsekai\\runtime\\python.exe",
          kind: "managed",
          label: "Shinsekai bundled runtime",
          managed: true,
          missingImports: [],
          missingPackages: [],
          path: "\\\\?\\C:\\Users\\test\\Shinsekai\\runtime\\python.exe",
          repairActions: ["start"],
          score: 100,
          selected: true,
          status: "ready",
          version: "3.10.20",
          warnings: [],
        },
      ],
      message: "Python bridge exited before startup completed: exit code: 1",
      status: "error",
    });

    renderChrome(<main>App content</main>);

    expect(await screen.findByText("Runtime update required")).toBeInTheDocument();
    expect(screen.queryByText("Install dependencies manually")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy command" })).not.toBeInTheDocument();
    expect(screen.queryByText("App content")).not.toBeInTheDocument();
  });

  it("shows the manual dependency command only after automatic installation fails", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    const manualInstallCommand =
      "& 'C:\\Users\\test\\Shinsekai\\runtime\\python.exe' -m pip install --requirement 'C:\\Program Files\\Shinsekai\\requirements-runtime-core.txt'";
    const missingDependencyState = {
      bridgeUrl: "",
      candidates: [
        {
          id: "python-ready",
          displayPath: "C:\\Users\\test\\Shinsekai\\runtime\\python.exe",
          kind: "managed" as const,
          label: "Shinsekai bundled runtime",
          managed: true,
          missingImports: ["pydantic"],
          missingPackages: ["pydantic"],
          path: "\\\\?\\C:\\Users\\test\\Shinsekai\\runtime\\python.exe",
          repairActions: ["installRuntimeDeps" as const],
          score: 100,
          selected: false,
          status: "missingCoreDeps" as const,
          version: "3.10.20",
          warnings: [],
        },
      ],
      message: "Python was found, but Shinsekai core dependencies are missing.",
      status: "needsAction" as const,
    };
    desktopApi.getDesktopRuntimeState.mockResolvedValueOnce(missingDependencyState).mockResolvedValueOnce({
      ...missingDependencyState,
      manualInstallCommand,
      message: "Dependency download failed",
      status: "error",
    });
    desktopApi.repairDesktopRuntime.mockRejectedValueOnce(new Error("Dependency download failed"));

    renderChrome(<main>App content</main>);

    await waitFor(() => {
      expect(desktopApi.repairDesktopRuntime).toHaveBeenCalledWith("python-ready", "installRuntimeDeps");
    });
    expect(await screen.findByText("Install dependencies manually")).toBeInTheDocument();
    expect(screen.getByText(manualInstallCommand)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy command" })).toBeInTheDocument();
    expect(desktopApi.repairDesktopRuntime).toHaveBeenCalledTimes(1);
  });

  it("wires title bar buttons and drag region to desktop commands", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);

    const { container } = renderChrome(<main>App content</main>);

    await screen.findByText("App content");
    fireEvent.click(screen.getByRole("button", { name: "Minimize" }));
    fireEvent.click(screen.getByRole("button", { name: "Maximize" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.mouseDown(container.querySelector(".desktop-titlebar")!, { button: 0 });

    expect(desktopApi.minimizeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApi.toggleMaximizeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApi.closeDesktopWindow).toHaveBeenCalledTimes(1);
    expect(desktopApi.startDesktopWindowDrag).toHaveBeenCalledTimes(1);
  });

  it("auto-installs missing dependencies for the bundled runtime on the startup gate", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
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
          repairActions: ["installRuntimeDeps"],
          score: 100,
          selected: true,
          status: "missingCoreDeps",
          version: "3.10.20",
          warnings: [],
        },
      ],
      message: "Python was found, but Shinsekai core dependencies are missing.",
      status: "needsAction",
    });

    renderChrome(<main>App content</main>);

    await waitFor(() => {
      expect(desktopApi.repairDesktopRuntime).toHaveBeenCalledWith("python-ready", "installRuntimeDeps");
    });
    expect(await screen.findByText("App content")).toBeInTheDocument();
  });

  it("shows runtime dependency install progress events", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      candidates: [],
      message: "Install Python dependencies.",
      status: "needsAction",
    });
    desktopApi.onDesktopRuntimeProgress.mockImplementation(async (listener) => {
      listener({
        logLine: "Collecting pydantic",
        message: "Installing Shinsekai runtime dependencies",
        phase: "installingDeps",
      });
      listener({
        logLine: "Installing collected packages: pydantic",
        message: "Installing Shinsekai runtime dependencies",
        phase: "installingDeps",
      });
      return vi.fn();
    });

    renderChrome(<main>App content</main>);

    expect(await screen.findByText("Installing Shinsekai runtime dependencies")).toBeInTheDocument();
    expect(screen.getByText(/Collecting pydantic/)).toBeInTheDocument();
    expect(screen.getByText(/Installing collected packages: pydantic/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Runtime progress" })).toBeInTheDocument();
  });

  it("auto-installs missing dependencies into the bundled runtime", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      candidates: [
        {
          id: "python-managed",
          kind: "managed",
          label: "Shinsekai bundled runtime",
          managed: true,
          missingImports: ["pygame"],
          missingPackages: ["pyyaml"],
          path: "/opt/Shinsekai/runtime/bin/python3",
          repairActions: ["installRuntimeDeps"],
          score: 10,
          selected: false,
          status: "missingCoreDeps",
          version: "3.11.9",
          warnings: [],
        },
      ],
      message: "Python was found, but Shinsekai core dependencies are missing.",
      status: "needsAction",
    });

    renderChrome(<main>App content</main>);

    await waitFor(() => {
      expect(desktopApi.repairDesktopRuntime).toHaveBeenCalledWith("python-managed", "installRuntimeDeps");
    });
  });
});
