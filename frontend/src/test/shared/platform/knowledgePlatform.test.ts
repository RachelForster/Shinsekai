import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpPlatform } from "../../../shared/platform/httpPlatform";
import { createBrowserPreviewPlatform } from "../../../shared/platform/browserPreviewPlatform";

describe("knowledge platform status", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("checks Knowledge status with explicit start and retry options", async () => {
    const status = { status: "loading", modelCached: true };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => status });
    vi.stubGlobal("fetch", fetchMock);
    const api = createHttpPlatform("http://localhost:8787").knowledge;

    expect(await api.getKnowledgeStatus!()).toEqual(status);
    await api.getKnowledgeStatus!({ startLoading: true, retry: false });
    await api.getKnowledgeStatus!({ startLoading: false, retry: true });

    expect(fetchMock.mock.calls.map(([url, init]) => [url, init.method, JSON.parse(init.body)])).toEqual([
      ["http://localhost:8787/api/knowledge/status", "POST", { startLoading: false, retry: false }],
      ["http://localhost:8787/api/knowledge/status", "POST", { startLoading: true, retry: false }],
      ["http://localhost:8787/api/knowledge/status", "POST", { startLoading: false, retry: true }],
    ]);
  });

  it("reports Knowledge ready in the browser preview without HTTP requests", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const status = createBrowserPreviewPlatform().knowledge.getKnowledgeStatus!({ startLoading: true });
    await vi.advanceTimersByTimeAsync(3000);
    expect(await status).toEqual({ status: "ready" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

});
