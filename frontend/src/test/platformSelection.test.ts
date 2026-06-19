import { afterEach, describe, expect, it, vi } from "vitest";

describe("platform selection", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
    delete window.__SHINSEKAI_IPC__;
    window.history.replaceState({}, "", "/");
  });

  it("prefers an explicit shinsekai_bridge URL over the build-time API base", async () => {
    const createHttpPlatform = vi.fn((baseUrl: string) => ({ baseUrl }));
    const createBrowserPreviewPlatform = vi.fn(() => ({ baseUrl: "preview" }));

    vi.doMock("../shared/platform/httpPlatform", () => ({ createHttpPlatform }));
    vi.doMock("../shared/platform/browserPreviewPlatform", () => ({ createBrowserPreviewPlatform }));
    vi.stubEnv("VITE_SHINSEKAI_API_BASE", "http://127.0.0.1:8787");

    window.history.replaceState({}, "", "/?shinsekai_bridge=http%3A%2F%2F127.0.0.1%3A8793#/");

    const { getPlatform } = await import("../shared/platform/platform");
    const platform = getPlatform() as unknown as { baseUrl: string };

    expect(platform.baseUrl).toBe("http://127.0.0.1:8793");
    expect(createHttpPlatform).toHaveBeenCalledWith("http://127.0.0.1:8793");
    expect(createBrowserPreviewPlatform).not.toHaveBeenCalled();
  });
});
