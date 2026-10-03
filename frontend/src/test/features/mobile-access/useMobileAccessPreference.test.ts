import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  mobileAccessPreferenceKey,
  setMobileAccessPreference,
  useMobileAccessPreference,
} from "../../../features/mobile-access/useMobileAccessPreference";

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  setMobileAccessPreference(false);
  localStorage.clear();
});

describe("shared mobile access launch preference", () => {
  it.each([null, "false", "invalid"])("defaults to disabled for %s", (stored) => {
    if (stored !== null) localStorage.setItem(mobileAccessPreferenceKey, stored);
    const { result } = renderHook(useMobileAccessPreference);
    expect(result.current[0]).toBe(false);
  });
  it("synchronizes mounted launch entries and restores the preference after remount", () => {
    const first = renderHook(useMobileAccessPreference);
    const second = renderHook(useMobileAccessPreference);
    act(() => first.result.current[1](true));
    expect(first.result.current[0]).toBe(true);
    expect(second.result.current[0]).toBe(true);
    expect(localStorage.getItem(mobileAccessPreferenceKey)).toBe("true");
    first.unmount();
    second.unmount();
    expect(renderHook(useMobileAccessPreference).result.current[0]).toBe(true);
  });
  it("handles other-window updates and storage clearing but ignores unrelated keys", () => {
    const { result } = renderHook(useMobileAccessPreference);
    localStorage.setItem(mobileAccessPreferenceKey, "true");
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: "unrelated" })));
    expect(result.current[0]).toBe(false);
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: mobileAccessPreferenceKey })));
    expect(result.current[0]).toBe(true);
    localStorage.clear();
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: null })));
    expect(result.current[0]).toBe(false);
  });
  it("still changes the current-window preference when persistent storage is unavailable", () => {
    const { result } = renderHook(useMobileAccessPreference);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Storage unavailable", "QuotaExceededError");
    });
    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
    act(() => result.current[1](false));
    expect(result.current[0]).toBe(false);
  });
});
