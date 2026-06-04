import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const desktopApi = vi.hoisted(() => ({
  browseDesktopFiles: vi.fn(),
  chooseDesktopRuntimePython: vi.fn(),
  closeDesktopWindow: vi.fn<() => Promise<void>>(),
  getDesktopRuntimeState: vi.fn(),
  isTauriDesktop: vi.fn(),
  minimizeDesktopWindow: vi.fn<() => Promise<void>>(),
  onDesktopRuntimeProgress: vi.fn(),
  repairDesktopRuntime: vi.fn(),
  selectDesktopRuntime: vi.fn(),
  startDesktopWindowDrag: vi.fn<() => Promise<void>>(),
  toggleMaximizeDesktopWindow: vi.fn<() => Promise<void>>(),
}));

vi.mock("../shared/desktop/desktopApi", () => desktopApi);

import { DesktopChrome } from "../shared/desktop/DesktopChrome";
import { I18nProvider } from "../shared/i18n/I18nProvider";

function renderChrome(children: ReactNode) {
  return render(
    <I18nProvider language="en">
      <DesktopChrome>{children}</DesktopChrome>
    </I18nProvider>,
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
    desktopApi.chooseDesktopRuntimePython.mockResolvedValue({
      bridgeUrl: "http://127.0.0.1:8787",
      candidates: [],
      status: "ready",
    });
    desktopApi.minimizeDesktopWindow.mockResolvedValue(undefined);
    desktopApi.onDesktopRuntimeProgress.mockResolvedValue(vi.fn());
    desktopApi.repairDesktopRuntime.mockResolvedValue({
      bridgeUrl: "http://127.0.0.1:8787",
      candidates: [],
      status: "ready",
    });
    desktopApi.startDesktopWindowDrag.mockResolvedValue(undefined);
    desktopApi.selectDesktopRuntime.mockResolvedValue({
      bridgeUrl: "http://127.0.0.1:8787",
      candidates: [],
      status: "ready",
    });
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
    expect(screen.getByText("App content")).toBeInTheDocument();
    expect(desktopApi.getDesktopRuntimeState).toHaveBeenCalledTimes(1);
  });

  it("keeps the runtime gate open for manual Python selection when no candidate exists", async () => {
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
    expect(screen.getByLabelText("Python executable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Update" })).not.toBeInTheDocument();
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

  it("shows runtime candidates and starts a ready candidate", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
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
          kind: "path",
          label: "PATH python3",
          managed: false,
          missingImports: ["pygame"],
          missingPackages: ["pyyaml"],
          path: "/usr/bin/python3",
          repairActions: ["createManagedVenv"],
          score: 10,
          selected: false,
          status: "missingCoreDeps",
          version: "3.11.9",
          warnings: ["Python reports an externally-managed environment."],
        },
      ],
      message: "Python was found, but Shinsekai core dependencies are missing.",
      status: "needsAction",
    });

    renderChrome(<main>App content</main>);

    expect(await screen.findByText("Runtime candidates")).toBeInTheDocument();
    expect(screen.getByText("conda env shinsekai")).toBeInTheDocument();
    expect(screen.getByText("PATH python3")).toBeInTheDocument();
    expect(screen.getByText(/pyyaml, pygame/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Use this runtime" }));

    await waitFor(() => {
      expect(desktopApi.selectDesktopRuntime).toHaveBeenCalledWith("python-ready");
    });
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
        message: "Installing Shinsekai runtime dependencies",
        phase: "installingDeps",
      });
      return vi.fn();
    });

    renderChrome(<main>App content</main>);

    expect(await screen.findByText("Installing Shinsekai runtime dependencies")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar", { name: "Runtime progress" })).not.toBeInTheDocument();
  });

  it("repairs a missing dependency candidate with an isolated runtime", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      candidates: [
        {
          id: "python-missing",
          kind: "path",
          label: "PATH python3",
          managed: false,
          missingImports: ["pygame"],
          missingPackages: ["pyyaml"],
          path: "/usr/bin/python3",
          repairActions: ["createManagedVenv"],
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

    fireEvent.click(await screen.findByRole("button", { name: "Create isolated runtime" }));

    await waitFor(() => {
      expect(desktopApi.repairDesktopRuntime).toHaveBeenCalledWith("python-missing", "createManagedVenv");
    });
  });

  it("installs missing dependencies into a conda runtime candidate", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      candidates: [
        {
          id: "python-conda",
          kind: "conda",
          label: "conda env shinsekai",
          managed: false,
          missingImports: ["pygame"],
          missingPackages: ["pyyaml"],
          path: "/opt/miniconda3/envs/shinsekai/bin/python",
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

    fireEvent.click(await screen.findByRole("button", { name: "Install dependencies" }));

    await waitFor(() => {
      expect(desktopApi.repairDesktopRuntime).toHaveBeenCalledWith("python-conda", "installRuntimeDeps");
    });
  });

  it("uses a manually selected Python runtime path from the gate", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      candidates: [],
      message: "No Python runtime candidates were found.",
      status: "needsAction",
    });

    renderChrome(<main>App content</main>);

    fireEvent.change(await screen.findByLabelText("Python executable"), {
      target: { value: "/opt/python/bin/python" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use Python" }));

    await waitFor(() => {
      expect(desktopApi.chooseDesktopRuntimePython).toHaveBeenCalledWith("/opt/python/bin/python");
    });
  });

  it("selects a runtime directory from the gate file browser", async () => {
    desktopApi.isTauriDesktop.mockReturnValue(true);
    desktopApi.getDesktopRuntimeState.mockResolvedValue({
      bridgeUrl: "",
      candidates: [],
      message: "No Python runtime candidates were found.",
      status: "needsAction",
    });

    renderChrome(<main>App content</main>);

    fireEvent.click(await screen.findByRole("button", { name: "Choose Python" }));
    fireEvent.click(await screen.findByText("runtime"));
    fireEvent.click(screen.getByRole("button", { name: "Select path" }));
    fireEvent.click(screen.getByRole("button", { name: "Use Python" }));

    await waitFor(() => {
      expect(desktopApi.chooseDesktopRuntimePython).toHaveBeenCalledWith("/tmp/runtime");
    });
  });
});
