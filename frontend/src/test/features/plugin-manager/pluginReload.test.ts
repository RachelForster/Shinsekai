import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reloadPluginService } from "../../../features/plugin-manager/pluginReload";

const mocks = vi.hoisted(() => ({
  restartDesktopBridge: vi.fn(),
}));

vi.mock("../../../shared/desktop/desktopApi", () => ({
  restartDesktopBridge: () => mocks.restartDesktopBridge(),
}));

function healthResponse(payload: unknown, ok = true, status = ok ? 200 : 503) {
  return Promise.resolve({
    json: () => Promise.resolve(payload),
    ok,
    status,
  } as Response);
}

describe("pluginReload", () => {
  beforeEach(() => {
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("restarts the desktop bridge and returns once plugin health is ready", async () => {
    const runtime = { bridgeUrl: "http://127.0.0.1:8787/" };
    mocks.restartDesktopBridge.mockResolvedValue(runtime);
    const fetchMock = vi.fn(() => healthResponse({ ok: true, plugins: { status: "ready" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(reloadPluginService()).resolves.toBe(runtime);

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8787/api/health", { cache: "no-store" });
  });

  it("falls back to the plugin status endpoint when health omits plugin load state", async () => {
    const runtime = { bridgeUrl: "http://127.0.0.1:8787" };
    mocks.restartDesktopBridge.mockResolvedValue(runtime);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ ok: true }),
        ok: true,
        status: 200,
      } as Response)
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ status: "ready" }),
        ok: true,
        status: 200,
      } as Response);
    vi.stubGlobal("fetch", fetchMock);

    await expect(reloadPluginService()).resolves.toBe(runtime);

    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8787/api/plugins/status", { cache: "no-store" });
  });

  it("throws terminal plugin load errors without retrying", async () => {
    mocks.restartDesktopBridge.mockResolvedValue({ bridgeUrl: "http://127.0.0.1:8787" });
    const fetchMock = vi.fn(() =>
      healthResponse({ ok: true, plugins: { error: "bad plugin manifest", status: "error" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(reloadPluginService()).rejects.toThrow("bad plugin manifest");

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("times out with the last health state when the service never becomes ready", async () => {
    vi.useFakeTimers();
    mocks.restartDesktopBridge.mockResolvedValue({ bridgeUrl: "http://127.0.0.1:8787" });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => healthResponse({ ok: true, plugins: { status: "loading" } })),
    );

    const result = expect(reloadPluginService()).rejects.toThrow("Plugin service is still loading.");
    await vi.advanceTimersByTimeAsync(15_200);

    await result;
  });

  it("skips health polling when the restarted runtime has no bridge URL", async () => {
    const runtime = { bridgeUrl: "" };
    mocks.restartDesktopBridge.mockResolvedValue(runtime);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(reloadPluginService()).resolves.toBe(runtime);

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
