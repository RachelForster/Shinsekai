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
  checkDesktopUpdate,
  installDesktopUpdate,
  isTauriDesktop,
  onDesktopUpdateProgress,
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
});
