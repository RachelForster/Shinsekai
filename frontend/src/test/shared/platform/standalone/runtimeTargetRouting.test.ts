import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { saveRemoteBridgeConfig } from "../../../../shared/platform/runtimeTarget";

describe("Standalone RuntimeTarget & Dual-Mode Platform Routing", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    window.localStorage.clear();
    delete (window as Window & { toy?: unknown }).toy;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    delete (window as Window & { toy?: unknown }).toy;
  });

  it("never resolves /api/* against bilibili.com origin in Bilibili Toy mode", async () => {
    vi.stubEnv("VITE_SHINSEKAI_TARGET", "toy");
    vi.stubEnv("VITE_SHINSEKAI_STANDALONE", "true");
    vi.stubEnv("DEV", false);
    Object.defineProperty(window, "location", {
      configurable: true,
      value: new URL("https://www.bilibili.com/toy/shinsekai/#/chat"),
    });

    const { getPlatform, resolvePlatformHttpUrl } = await import("../../../../shared/platform/platform");
    expect(resolvePlatformHttpUrl("/api/config")).toBe("/api/config");

    const plat = getPlatform();
    const config = await plat.config.get();
    expect(config.characters.length).toBeGreaterThan(0);
    expect(config.adapter_catalog?.tts.some((opt) => opt.value === "openai-speech")).toBe(true);
  });

  it("switches mobile runtime between StandalonePlatform and remote-pc HttpPlatform dynamically", async () => {
    vi.stubEnv("VITE_SHINSEKAI_TARGET", "mobile");
    vi.stubEnv("VITE_SHINSEKAI_STANDALONE", "true");

    const mod = await import("../../../../shared/platform/platform");
    const standalonePlat = mod.getPlatform();
    const standaloneConfig = await standalonePlat.config.get();
    expect(standaloneConfig.characters.some((c) => c.name === "星奈")).toBe(true);

    let modeChangeCalls = 0;
    const unsub = mod.onPlatformModeChange(() => {
      modeChangeCalls += 1;
    });

    saveRemoteBridgeConfig({
      mode: "remote-pc",
      url: "http://192.168.1.88:8787",
      token: "pc-secret",
    });
    expect(mod.resolvePlatformHttpUrl("/api/media/test.png")).toBe("http://192.168.1.88:8787/api/media/test.png");

    mod.resetPlatformForModeSwitch();
    expect(modeChangeCalls).toBe(1);

    const switchedPlat = mod.getPlatform();
    expect(switchedPlat).not.toBe(standalonePlat);
    unsub();
  });
});
