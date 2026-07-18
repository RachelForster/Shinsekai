import { describe, expect, it } from "vitest";

import {
  compareReleaseVersions,
  getUnseenReleaseHighlights,
  isReleaseVersion,
} from "../../../features/release-highlights/releaseHighlightsState";

describe("release highlight state", () => {
  it("compares normalized release versions", () => {
    expect(compareReleaseVersions("v2.3.0", "2.2.9")).toBe(1);
    expect(compareReleaseVersions("2.3", "2.3.0")).toBe(0);
    expect(compareReleaseVersions("2.2.9", "2.3.0")).toBe(-1);
    expect(compareReleaseVersions("preview", "2.3.0")).toBeNull();
    expect(isReleaseVersion("2.3.0")).toBe(true);
    expect(isReleaseVersion("2.3.0-dev")).toBe(false);
  });

  it("returns only bundled releases newer than the last seen version", () => {
    expect(getUnseenReleaseHighlights("2.2.0", "")).toEqual([]);
    expect(getUnseenReleaseHighlights("2.3.0", "2.2.0").map((release) => release.version)).toEqual(["2.3.0"]);
    expect(getUnseenReleaseHighlights("2.4.0", "2.3.0")).toEqual([]);
    expect(getUnseenReleaseHighlights("preview", "")).toEqual([]);
  });
});
