import { waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { mockEmit, mockInvoke, mockListen } = vi.hoisted(() => ({
  mockEmit: vi.fn(),
  mockInvoke: vi.fn(),
  mockListen: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: mockInvoke,
}));

vi.mock("@tauri-apps/api/event", () => ({
  emit: mockEmit,
  listen: mockListen,
}));

import {
  browseDesktopFiles,
  checkDesktopUpdate,
  emitDesktopChatStageRuntimeConfigChange,
  getDesktopProjectRootStatus,
  getDesktopRuntimeState,
  hideDesktopWindow,
  destroyDesktopChatWindow,
  installDesktopRuntimeProfile,
  installDesktopUpdate,
  isTauriDesktop,
  minimizeDesktopWindow,
  openDesktopChatWindow,
  onDesktopChatStageRuntimeConfigChange,
  onDesktopRuntimeProgress,
  onDesktopUpdateProgress,
  repairDesktopRuntime,
  reloadDesktopFrontend,
  selectDesktopProjectRoot,
  setDesktopWindowAlwaysOnTop,
  startDesktopWindowDrag,
  toggleMaximizeDesktopWindow,
  closeDesktopWindow,
} from "../../../shared/desktop/desktopApi";

describe("desktop API environment detection", () => {
  afterEach(() => {
    delete window.__TAURI_INTERNALS__;
    delete window.__SHINSEKAI_RESTARTING__;
    delete window.__SHINSEKAI_BRIDGE_RESTARTING__;
    delete window.__SHINSEKAI_BRIDGE_RESTART_EVENTS_BOUND__;
    mockEmit.mockReset();
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

  it("reads and explicitly selects a desktop project root", async () => {
    mockInvoke.mockResolvedValue({
      candidates: [],
      conflict: false,
      currentPath: "D:\\Shinsekai",
      locatorPath: "C:\\Users\\test\\project-root.json",
      requiresSelection: false,
    });

    await getDesktopProjectRootStatus();
    await selectDesktopProjectRoot("D:\\项目 数据\\Shinsekai");

    expect(mockInvoke).toHaveBeenCalledWith("desktop_project_root_status", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_project_root_select", {
      path: "D:\\项目 数据\\Shinsekai",
    });
  });

  it("invokes desktop runtime state and dependency commands", async () => {
    mockInvoke.mockResolvedValue({ bridgeUrl: "", candidates: [], status: "needsAction" });

    await getDesktopRuntimeState();
    await repairDesktopRuntime("install-runtime", "installRuntimeDeps");
    await installDesktopRuntimeProfile("local-ai");
    await browseDesktopFiles({ path: "/tmp", showHidden: true });
    await hideDesktopWindow();
    await destroyDesktopChatWindow();
    await minimizeDesktopWindow();
    await setDesktopWindowAlwaysOnTop(false);
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
    expect(mockInvoke).toHaveBeenCalledWith("desktop_window_hide", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_chat_window_destroy", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_window_minimize", undefined);
    expect(mockInvoke).toHaveBeenCalledWith("desktop_window_set_always_on_top", { alwaysOnTop: false });
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

  it("broadcasts and subscribes to chat runtime config changes across desktop webviews", async () => {
    const config = { configThemeColor: "#336699" };
    const listener = vi.fn();
    const unlisten = vi.fn();
    const tauriInvoke = vi.fn().mockResolvedValue(undefined);
    mockEmit.mockResolvedValue(undefined);
    mockListen.mockImplementation(async (eventName, callback) => {
      if (eventName === "shinsekai:chat-stage-runtime-config-change") {
        callback({ payload: config });
      }
      return unlisten;
    });
    window.__TAURI_INTERNALS__ = { invoke: tauriInvoke };

    await emitDesktopChatStageRuntimeConfigChange(config);
    const dispose = await onDesktopChatStageRuntimeConfigChange(listener);
    dispose();

    expect(tauriInvoke).toHaveBeenCalledWith(
      "plugin:event|emit",
      {
        event: "shinsekai:chat-stage-runtime-config-change",
        payload: config,
      },
      undefined,
    );
    expect(mockListen).toHaveBeenCalledWith("shinsekai:chat-stage-runtime-config-change", expect.any(Function));
    expect(listener).toHaveBeenCalledWith(config);
    expect(unlisten).toHaveBeenCalledTimes(1);
  });
});
