import { describe, expect, it } from "vitest";

import { isPortablePathComponent, normalizePathSeparatorsForIdentity } from "../../../shared/paths/pathContract";

describe("normalizePathSeparatorsForIdentity", () => {
  it("preserves literal backslashes only in native POSIX absolute paths", () => {
    expect(normalizePathSeparatorsForIdentity(String.raw`/tmp/literal\child.png`)).toBe(
      String.raw`/tmp/literal\child.png`,
    );
  });

  it("normalizes Windows drive and UNC path separators", () => {
    expect(normalizePathSeparatorsForIdentity(String.raw`C:\project\data\asset.png`)).toBe("C:/project/data/asset.png");
    expect(normalizePathSeparatorsForIdentity(String.raw`\\server\share\asset.png`)).toBe("//server/share/asset.png");
    expect(normalizePathSeparatorsForIdentity(String.raw`//server/share\asset.png`)).toBe("//server/share/asset.png");
  });
});

describe("isPortablePathComponent", () => {
  it("rejects every Windows device alias that can break after migration", () => {
    for (const value of ["CLOCK$", "CONIN$.log", "CONOUT$", "COM¹", "COM².txt", "COM³", "LPT¹", "LPT².txt", "LPT³"]) {
      expect(isPortablePathComponent(value)).toBe(false);
    }
    expect(isPortablePathComponent("COM10")).toBe(true);
    expect(isPortablePathComponent("LPT0.txt")).toBe(true);
  });

  it("enforces the common 255-byte portable component boundary", () => {
    expect(isPortablePathComponent("界".repeat(85))).toBe(true);
    expect(isPortablePathComponent("界".repeat(86))).toBe(false);
    expect(isPortablePathComponent("a".repeat(256))).toBe(false);
  });
});
