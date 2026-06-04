import { afterEach, describe, expect, it, vi } from "vitest";

const { mockInvoke, mockListen } = vi.hoisted(() => ({
  mockInvoke: vi.fn(),
  mockListen: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: mockInvoke,
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: mockListen,
}));

import {
  browseDesktopFiles,
  checkDesktopUpdate,
  chooseDesktopRuntimePython,
  installDesktopRuntimeProfile,
  installDesktopUpdate,
  isTauriDesktop,
  onDesktopRuntimeProgress,
  onDesktopUpdateProgress,
  repairDesktopRuntime,
  scanDesktopRuntime,
  selectDesktopRuntime,
  startDesktopRuntime,
} from "../shared/desktop/desktopApi";

describe("desktop API environment detection", () => {
  afterEach(() => {
    delete window.__TAURI_INTERNALS__;
    delete window.__SHINSEKAI_RESTARTING__;
    mockInvoke.mockReset();
    mockListen.mockReset();
  });

  it("returns false in the browser preview environment", () => {
    delete window.__TAURI_INTERNALS__;
    expect(isTauriDesktop()).toBe(false);
  });

  it("detects Tauri internals when the desktop shell injects them", () => {
    window.__TAURI_INTERNALS__ = {};
    expect(isTauriDesktop()).toBe(true);
  });

  it("invokes the desktop updater check command", async () => {
    mockInvoke.mockResolvedValueOnce({ body: "notes", date: "2026-06-02", version: "1.0.1" });

    await expect(checkDesktopUpdate()).resolves.toEqual({
      body: "notes",
      date: "2026-06-02",
      version: "1.0.1",
    });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_update_check", undefined);
  });

  it("invokes desktop runtime scan and start commands", async () => {
    mockInvoke.mockResolvedValue({ bridgeUrl: "", candidates: [], status: "needsAction" });

    await scanDesktopRuntime();
    await startDesktopRuntime("python-ready");
    await selectDesktopRuntime("python-ready");
    await repairDesktopRuntime("python-missing", "createManagedVenv");
    await repairDesktopRuntime("python-conda", "installRuntimeDeps");
    await chooseDesktopRuntimePython("/opt/python/bin/python");
    await installDesktopRuntimeProfile("media");
    await browseDesktopFiles({ path: "/tmp", showHidden: true });

    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_scan", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_start", { candidateId: "python-ready" });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_select", { candidateId: "python-ready" });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_repair", {
      action: "createManagedVenv",
      candidateId: "python-missing",
    });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_repair", {
      action: "installRuntimeDeps",
      candidateId: "python-conda",
    });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_choose_python", { path: "/opt/python/bin/python" });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_install_profile", { profile: "media" });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_files_browse", { path: "/tmp", showHidden: true });
  });

  it("passes desktop file browser defaults and Windows paths through unchanged", async () => {
    mockInvoke.mockResolvedValue({ cwd: "", entries: [], parent: "", roots: [] });

    await browseDesktopFiles();
    await browseDesktopFiles({ path: "C:\\Users\\Tester\\Pictures", showHidden: false });
    await browseDesktopFiles({ path: "\\\\server\\share\\folder", showHidden: true });

    expect(mockInvoke).toHaveBeenCalledWith("desktop_files_browse", {});
    expect(mockInvoke).toHaveBeenCalledWith("desktop_files_browse", {
      path: "C:\\Users\\Tester\\Pictures",
      showHidden: false,
    });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_files_browse", {
      path: "\\\\server\\share\\folder",
      showHidden: true,
    });
  });

  it("marks restart state while installing a desktop update", async () => {
    mockInvoke.mockResolvedValue(undefined);

    await installDesktopUpdate();

    expect(window.__SHINSEKAI_RESTARTING__).toBe(true);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_update_install", undefined);
  });

  it("subscribes to desktop updater progress events", async () => {
    const unlisten = vi.fn();
    const listener = vi.fn();
    mockListen.mockImplementation(async (_eventName, callback) => {
      callback({ payload: { contentLength: 20, downloaded: 10, event: "progress" } });
      return unlisten;
    });

    const dispose = await onDesktopUpdateProgress(listener);
    dispose();

    expect(mockListen).toHaveBeenCalledWith("shinsekai:update-progress", expect.any(Function));
    expect(listener).toHaveBeenCalledWith({ contentLength: 20, downloaded: 10, event: "progress" });
    expect(unlisten).toHaveBeenCalledTimes(1);
  });

  it("subscribes to desktop runtime progress events", async () => {
    const unlisten = vi.fn();
    const listener = vi.fn();
    mockListen.mockImplementation(async (_eventName, callback) => {
      callback({ payload: { message: "Scanning", phase: "probing" } });
      return unlisten;
    });

    const dispose = await onDesktopRuntimeProgress(listener);
    dispose();

    expect(mockListen).toHaveBeenCalledWith("shinsekai:runtime-progress", expect.any(Function));
    expect(listener).toHaveBeenCalledWith({ message: "Scanning", phase: "probing" });
    expect(unlisten).toHaveBeenCalledTimes(1);
  });
});
