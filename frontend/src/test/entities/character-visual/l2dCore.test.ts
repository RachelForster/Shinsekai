import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
});
afterEach(() => {
  document.querySelectorAll('script[src="/live2d/live2dcubismcore.min.js"]').forEach((script) => script.remove());
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
const script = () => document.querySelector<HTMLScriptElement>('script[src="/live2d/live2dcubismcore.min.js"]')!;

describe("licensed local Core loading", () => {
  it("uses an existing global without creating a script", async () => {
    vi.stubGlobal("Live2DCubismCore", {});
    const { hasCore, loadCore } = await import("../../../entities/character-visual/adapters/l2d/core");
    await loadCore(new AbortController().signal);
    expect(hasCore()).toBe(true);
    expect(script()).toBeNull();
  });

  it("shares a pending local load and validates the global", async () => {
    const { loadCore } = await import("../../../entities/character-visual/adapters/l2d/core");
    const signal = new AbortController().signal;
    const first = loadCore(signal),
      second = loadCore(signal);
    expect(document.querySelectorAll('script[src="/live2d/live2dcubismcore.min.js"]')).toHaveLength(1);
    vi.stubGlobal("Live2DCubismCore", {});
    script().dispatchEvent(new Event("load"));
    await Promise.all([first, second]);
  });

  it.each(["error", "load", "timeout"])("reports and cleans up failed loads: %s", async (failure) => {
    const { loadCore } = await import("../../../entities/character-visual/adapters/l2d/core");
    const loading = loadCore(new AbortController().signal);
    const rejected = expect(loading).rejects.toThrow("Core is missing");
    if (failure === "timeout") await vi.advanceTimersByTimeAsync(15000);
    else script().dispatchEvent(new Event(failure));
    await rejected;
    expect(script()).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
    const retry = loadCore(new AbortController().signal);
    vi.stubGlobal("Live2DCubismCore", {});
    script().dispatchEvent(new Event("load"));
    await retry;
  });

  it("honours cancellation before and after a shared load", async () => {
    const { loadCore } = await import("../../../entities/character-visual/adapters/l2d/core");
    const abort = new AbortController();
    abort.abort();
    await expect(loadCore(abort.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(script()).toBeNull();
    const active = new AbortController();
    const loading = loadCore(active.signal);
    active.abort();
    vi.stubGlobal("Live2DCubismCore", {});
    script().dispatchEvent(new Event("load"));
    await expect(loading).rejects.toMatchObject({ name: "AbortError" });
  });
});
