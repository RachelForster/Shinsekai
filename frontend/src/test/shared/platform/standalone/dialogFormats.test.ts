import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resetPlatformForModeSwitch } from "../../../../shared/platform/platform";
import { createStandalonePlatform } from "../../../../shared/platform/standalone";
import { clearAllStandaloneStorage } from "../../../../shared/platform/standalone/storage/indexedDbStore";

describe("standalone dialog output format capability", () => {
  beforeEach(async () => {
    await clearAllStandaloneStorage();
    window.localStorage?.clear();
    resetPlatformForModeSwitch();
  });

  afterEach(() => {
    resetPlatformForModeSwitch();
  });

  it("exposes only json_v1 in standalone mode until custom format decoders exist", async () => {
    const platform = createStandalonePlatform({ target: "toy" });
    const formats = await platform.templates.listDialogFormats();
    expect(formats).toEqual([{ id: "json_v1", label: "JSON", builtin: true }]);
  });
});
