import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isValidEffectStorageName, suggestUniqueSpritePrefix } from "../../shared/assets/spritePrefix";
import { useDebouncedAutoSave } from "../../shared/hooks/useDebouncedAutoSave";

describe("spritePrefix utilities", () => {
  it("generates non-colliding ASCII prefixes from names or numbered fallbacks", () => {
    expect(suggestUniqueSpritePrefix("", [], "char")).toBe("char_1");
    expect(suggestUniqueSpritePrefix("星奈", ["char_1"], "char")).toBe("char_2");
    expect(suggestUniqueSpritePrefix("School Night!", [], "bg")).toBe("school_night");
    expect(suggestUniqueSpritePrefix("School Night!", ["school_night", "school_night_2"], "bg")).toBe("school_night_3");
    expect(suggestUniqueSpritePrefix("__self__", [], "char")).toBe("self");
    expect(suggestUniqueSpritePrefix("自设", ["__self__"], "char")).toBe("char_1");
  });

  it("validates effect storage names against path traversal and illegal characters", () => {
    expect(isValidEffectStorageName("Rain & Wind")).toBe(true);
    expect(isValidEffectStorageName("")).toBe(false);
    expect(isValidEffectStorageName("..")).toBe(false);
    expect(isValidEffectStorageName("bad/name")).toBe(false);
    expect(isValidEffectStorageName("bad\\name")).toBe(false);
    expect(isValidEffectStorageName("trailing.")).toBe(false);
  });
});

describe("useDebouncedAutoSave", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces changes, cancels when reverted to baseline, and retries on failure", async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new Error("network down")).mockResolvedValue({ ok: true });
    const onError = vi.fn();

    const { rerender, result } = renderHook(
      ({ baselineKey, currentKey }: { baselineKey: string; currentKey: string }) =>
        useDebouncedAutoSave({
          baselineKey,
          buildPayload: () => ({ value: currentKey }),
          currentKey,
          debounceMs: 600,
          enabled: true,
          onError,
          onSave,
          resetKey: "item-1",
        }),
      { initialProps: { baselineKey: "v1", currentKey: "v1" } },
    );

    expect(result.current.phase).toBe("idle");

    // Edit then revert before 600ms -> zero saves
    rerender({ baselineKey: "v1", currentKey: "v2" });
    expect(result.current.phase).toBe("pending");
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    rerender({ baselineKey: "v1", currentKey: "v1" });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(onSave).not.toHaveBeenCalled();

    // Edit and wait 600ms -> fails once and pauses in error phase until retry()
    rerender({ baselineKey: "v1", currentKey: "v3" });
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("error");
    expect(result.current.errorMessage).toBe("network down");
    expect(onError).toHaveBeenCalledTimes(1);

    await act(async () => {
      result.current.retry();
    });
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(result.current.phase).toBe("saved");
  });

  it("flushes pending save immediately when resetKey switches or hook unmounts", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);

    const { rerender, unmount } = renderHook(
      ({ currentKey, resetKey }: { currentKey: string; resetKey: string }) =>
        useDebouncedAutoSave({
          baselineKey: "base",
          buildPayload: () => ({ currentKey, resetKey }),
          currentKey,
          debounceMs: 600,
          enabled: true,
          onSave,
          resetKey,
        }),
      { initialProps: { currentKey: "edited-1", resetKey: "item-1" } },
    );

    // Switch item before 600ms -> flushes item-1 immediately
    rerender({ currentKey: "base", resetKey: "item-2" });
    expect(onSave).toHaveBeenCalledWith({ currentKey: "edited-1", resetKey: "item-1" });

    // Edit item-2 and unmount before 600ms -> flushes item-2 immediately
    rerender({ currentKey: "edited-2", resetKey: "item-2" });
    unmount();
    expect(onSave).toHaveBeenCalledWith({ currentKey: "edited-2", resetKey: "item-2" });
  });
});
