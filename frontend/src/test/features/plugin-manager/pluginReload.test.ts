import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { configQueryKey, ttsBundleRecommendationQueryKey } from "../../../entities/config/repository";
import { reloadPluginService } from "../../../features/plugin-manager/pluginReload";
import { sampleConfig } from "../../../shared/platform/sampleData";

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

function configWithAsrPlugin(installed: boolean) {
  return {
    ...sampleConfig,
    adapter_catalog: {
      ...sampleConfig.adapter_catalog,
      asr: installed
        ? [
            {
              label: "faster-whisper",
              schema: {
                model_size: { default: "small", label: "Model size", type: "str" },
              },
              value: "faster_whisper",
            },
          ]
        : [],
    },
  };
}

describe("pluginReload", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 5 * 60_000 } },
    });
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
  });

  afterEach(() => {
    queryClient.clear();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("restarts the desktop bridge and returns once plugin health is ready", async () => {
    const runtime = { bridgeUrl: "http://127.0.0.1:8787/" };
    mocks.restartDesktopBridge.mockResolvedValue(runtime);
    const fetchMock = vi.fn(() => healthResponse({ ok: true, plugins: { status: "ready" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(reloadPluginService(queryClient)).resolves.toBe(runtime);

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

    await expect(reloadPluginService(queryClient)).resolves.toBe(runtime);

    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8787/api/plugins/status", { cache: "no-store" });
  });

  it("throws terminal plugin load errors without retrying", async () => {
    const cachedConfig = configWithAsrPlugin(true);
    queryClient.setQueryData(configQueryKey, cachedConfig);
    const fetchConfig = vi.fn().mockResolvedValue(configWithAsrPlugin(false));
    mocks.restartDesktopBridge.mockResolvedValue({ bridgeUrl: "http://127.0.0.1:8787" });
    const fetchMock = vi.fn(() =>
      healthResponse({ ok: true, plugins: { error: "bad plugin manifest", status: "error" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(reloadPluginService(queryClient)).rejects.toThrow("bad plugin manifest");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    await expect(queryClient.fetchQuery({ queryKey: configQueryKey, queryFn: fetchConfig })).resolves.toEqual(
      cachedConfig,
    );
    expect(fetchConfig).not.toHaveBeenCalled();
  });

  it("times out with the last health state when the service never becomes ready", async () => {
    vi.useFakeTimers();
    const cachedConfig = configWithAsrPlugin(true);
    queryClient.setQueryData(configQueryKey, cachedConfig);
    const fetchConfig = vi.fn().mockResolvedValue(configWithAsrPlugin(false));
    mocks.restartDesktopBridge.mockResolvedValue({ bridgeUrl: "http://127.0.0.1:8787" });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => healthResponse({ ok: true, plugins: { status: "loading" } })),
    );

    const result = expect(reloadPluginService(queryClient)).rejects.toThrow("Plugin service is still loading.");
    await vi.advanceTimersByTimeAsync(15_200);

    await result;
    await expect(queryClient.fetchQuery({ queryKey: configQueryKey, queryFn: fetchConfig })).resolves.toEqual(
      cachedConfig,
    );
    expect(fetchConfig).not.toHaveBeenCalled();
  });

  it("skips health polling when the restarted runtime has no bridge URL", async () => {
    const runtime = { bridgeUrl: "" };
    mocks.restartDesktopBridge.mockResolvedValue(runtime);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(reloadPluginService(queryClient)).resolves.toBe(runtime);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    { change: "adds", installedBefore: false, installedAfter: true },
    { change: "removes", installedBefore: true, installedAfter: false },
  ])("refreshes fresh config only after reload $change an ASR plugin", async ({ installedBefore, installedAfter }) => {
    vi.useFakeTimers();
    const cachedConfig = configWithAsrPlugin(installedBefore);
    const updatedConfig = configWithAsrPlugin(installedAfter);
    const fetchConfig = vi.fn().mockResolvedValue(cachedConfig);
    const configQuery = { queryKey: configQueryKey, queryFn: fetchConfig };
    await queryClient.fetchQuery(configQuery);
    fetchConfig.mockResolvedValue(updatedConfig);

    const recommendation = { kind: "genie" };
    const fetchRecommendation = vi.fn().mockResolvedValue(recommendation);
    const recommendationQuery = { queryKey: ttsBundleRecommendationQueryKey, queryFn: fetchRecommendation };
    await queryClient.fetchQuery(recommendationQuery);
    fetchRecommendation.mockResolvedValue({ kind: "gptso" });

    let ready = false;
    mocks.restartDesktopBridge.mockResolvedValue({ bridgeUrl: "http://127.0.0.1:8787" });
    const fetchHealth = vi.fn(() => healthResponse({ ok: true, plugins: { status: ready ? "ready" : "loading" } }));
    vi.stubGlobal("fetch", fetchHealth);

    const reload = reloadPluginService(queryClient);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchHealth).toHaveBeenCalledTimes(1);
    await expect(queryClient.fetchQuery(configQuery)).resolves.toEqual(cachedConfig);
    expect(fetchConfig).toHaveBeenCalledTimes(1);

    ready = true;
    await vi.advanceTimersByTimeAsync(160);
    await reload;

    await expect(queryClient.fetchQuery(configQuery)).resolves.toEqual(updatedConfig);
    expect(fetchConfig).toHaveBeenCalledTimes(2);
    await expect(queryClient.fetchQuery(recommendationQuery)).resolves.toEqual(recommendation);
    expect(fetchRecommendation).toHaveBeenCalledTimes(1);
  });
});
