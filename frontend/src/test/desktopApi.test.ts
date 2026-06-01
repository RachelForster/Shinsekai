import { afterEach, describe, expect, it } from "vitest";

import { isTauriDesktop } from "../shared/desktop/desktopApi";

describe("desktop API environment detection", () => {
  afterEach(() => {
    delete window.__TAURI_INTERNALS__;
  });

  it("returns false in the browser preview environment", () => {
    delete window.__TAURI_INTERNALS__;
    expect(isTauriDesktop()).toBe(false);
  });

  it("detects Tauri internals when the desktop shell injects them", () => {
    window.__TAURI_INTERNALS__ = {};
    expect(isTauriDesktop()).toBe(true);
  });
});
