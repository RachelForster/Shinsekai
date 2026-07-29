import { afterEach, describe, expect, it, vi } from "vitest";

import { isRemoteMobileAccessPage, stageAssetUrl } from "../../../features/chat-stage/chatStageUtils";

describe("stageAssetUrl", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rewrites bridge loopback media URLs to the mobile page origin", () => {
    vi.stubGlobal("window", {
      location: {
        host: "192.168.1.20:8789",
        hostname: "192.168.1.20",
        protocol: "http:",
      },
    });

    expect(
      stageAssetUrl("http://127.0.0.1:8787/api/media?path=data%2Fbackground.png&shinsekai_bridge_token=secret"),
    ).toBe("http://192.168.1.20:8789/api/media?path=data%2Fbackground.png&shinsekai_bridge_token=secret");
  });

  it("keeps loopback URLs unchanged on the desktop page", () => {
    expect(stageAssetUrl("http://127.0.0.1:8787/api/media?path=data%2Fbackground.png")).toBe(
      "http://127.0.0.1:8787/api/media?path=data%2Fbackground.png",
    );
  });

  it("keeps loopback URLs unchanged in the Tauri desktop WebView", () => {
    vi.stubGlobal("window", {
      location: {
        host: "tauri.localhost",
        hostname: "tauri.localhost",
        protocol: "http:",
      },
    });

    expect(stageAssetUrl("http://127.0.0.1:8787/api/media?path=data%2Fvoice.wav&shinsekai_bridge_token=secret")).toBe(
      "http://127.0.0.1:8787/api/media?path=data%2Fvoice.wav&shinsekai_bridge_token=secret",
    );
  });

  it("identifies LAN-hosted pages as mobile access clients", () => {
    expect(isRemoteMobileAccessPage({ hostname: "192.168.1.20", protocol: "http:" })).toBe(true);
    expect(isRemoteMobileAccessPage({ hostname: "127.0.0.1", protocol: "http:" })).toBe(false);
    expect(isRemoteMobileAccessPage({ hostname: "localhost", protocol: "http:" })).toBe(false);
    expect(isRemoteMobileAccessPage({ hostname: "tauri.localhost", protocol: "http:" })).toBe(false);
    expect(isRemoteMobileAccessPage({ hostname: "localhost", protocol: "tauri:" })).toBe(false);
  });
});
