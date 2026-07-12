import { describe, expect, it } from "vitest";

import { isMoondreamInstalled } from "../../../features/media-auto-label/useMoondreamAvailability";
import type { PluginManifest } from "../../../shared/platform/types";

function plugin(overrides: Partial<PluginManifest> = {}): PluginManifest {
  return {
    author: "",
    description: "",
    enabled: false,
    entry: "plugins.example.plugin:ExamplePlugin",
    id: "example",
    loaded: false,
    permissions: [],
    settingsPages: [],
    slots: [],
    title: "Example",
    toolsTabs: [],
    version: "1.0.0",
    ...overrides,
  };
}

describe("isMoondreamInstalled", () => {
  it("recognizes an installed plugin even when it is disabled or failed to load", () => {
    expect(
      isMoondreamInstalled(
        plugin({
          directory: "C:\\Shinsekai\\plugins\\moondream_vision",
          loadError: "optional dependency missing",
        }),
      ),
    ).toBe(true);
  });

  it("does not expose the entry for unrelated plugins", () => {
    expect(isMoondreamInstalled(plugin())).toBe(false);
  });
});
