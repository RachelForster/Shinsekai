import { describe, expect, it, beforeEach } from "vitest";

import { getInitialSettingsPath } from "../../../features/onboarding/onboardingState";

describe("onboarding startup routing", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("routes the first default app entry to onboarding, then future default entries to templates", () => {
    expect(getInitialSettingsPath()).toBe("/settings/onboarding");
    expect(localStorage.getItem("shinsekai-onboarding-seen")).toBe("true");
    expect(getInitialSettingsPath()).toBe("/settings/templates");
  });
});
