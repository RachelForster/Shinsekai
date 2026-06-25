import { waitFor } from "@testing-library/react";
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
  getDesktopRuntimeState,
  installDesktopRuntimeProfile,
  installDesktopUpdate,
  isTauriDesktop,
  isWindowsDesktopEnvironment,
  minimizeDesktopWindow,
  openDesktopChatWindow,
  onDesktopRuntimeProgress,
  onDesktopUpdateProgress,
  repairDesktopRuntime,
  reloadDesktopFrontend,
  startDesktopWindowDrag,
  supportsTransparentDesktopClickThrough,
  toggleMaximizeDesktopWindow,
  closeDesktopWindow,
} from "../shared/desktop/desktopApi";

describe("desktop API environment detection", () => {
  afterEach(() => {
    delete window.__TAURI_INTERNALS__;
    delete window.__SHINSEKAI_RESTARTING__;
    delete window.__SHINSEKAI_BRIDGE_RESTARTING__;
    delete window.__SHINSEKAI_BRIDGE_RESTART_EVENTS_BOUND__;
    mockInvoke.mockReset();
    mockListen.mockReset();
    vi.unstubAllGlobals();
  });

  it("returns false in the browser preview environment", () => {
    delete window.__TAURI_INTERNALS__;
    expect(isTauriDesktop()).toBe(false);
  });

  it("detects Tauri internals when the desktop shell injects them", () => {
    window.__TAURI_INTERNALS__ = {};
    expect(isTauriDesktop()).toBe(true);
  });

  it("disables transparent desktop click-through on Windows", () => {
    vi.stubGlobal("navigator", {
      platform: "Win32",
      userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    });

    expect(isWindowsDesktopEnvironment()).toBe(true);
    expect(supportsTransparentDesktopClickThrough()).toBe(false);
  });

  it("subscribes to bridge restart state events and mirrors them into window state", async () => {
    let bridgeRestartListener: (event: { payload: boolean }) => void = (_event) => {
      throw new Error("bridge restart listener was not bound");
    };
    mockListen.mockImplementation(async (eventName, callback) => {
      if (eventName === "shinsekai:bridge-restart-state") {
        bridgeRestartListener = callback as (event: { payload: boolean }) => void;
      }
      return vi.fn();
    });

    window.__TAURI_INTERNALS__ = {};
    expect(isTauriDesktop()).toBe(true);
    await waitFor(() =>
      expect(mockListen).toHaveBeenCalledWith("shinsekai:bridge-restart-state", expect.any(Function)),
    );
    expect(window.__SHINSEKAI_BRIDGE_RESTART_EVENTS_BOUND__).toBe(true);

    bridgeRestartListener({ payload: true });
    expect(window.__SHINSEKAI_BRIDGE_RESTARTING__).toBe(true);

    bridgeRestartListener({ payload: false });
    expect(window.__SHINSEKAI_BRIDGE_RESTARTING__).toBe(false);
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

  it("invokes desktop runtime state and dependency commands", async () => {
    mockInvoke.mockResolvedValue({ bridgeUrl: "", candidates: [], status: "needsAction" });

    await getDesktopRuntimeState();
    await repairDesktopRuntime("install-runtime", "installRuntimeDeps");
    await installDesktopRuntimeProfile("local-ai");
    await browseDesktopFiles({ path: "/tmp", showHidden: true });
    await minimizeDesktopWindow();
    await toggleMaximizeDesktopWindow();
    await startDesktopWindowDrag();
    await closeDesktopWindow();
    await openDesktopChatWindow();
    await reloadDesktopFrontend();

    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_state", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_repair", {
      action: "installRuntimeDeps",
      candidateId: "install-runtime",
    });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_runtime_install_profile", { profile: "local-ai" });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_files_browse", { path: "/tmp", showHidden: true });
    expect(mockInvoke).toHaveBeenCalledWith("desktop_window_minimize", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_window_toggle_maximize", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_window_start_drag", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_window_close", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_open_chat_window", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_frontend_reload", undefined);
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
