import { describe, expect, it } from "vitest";
import { avatarRenderSize } from "../../../modules/character-visual/renderSize";

describe("avatar render size", () => {
  it("keeps display pixel density for full, half-body and close-up framing", () => {
    for (const scale of [1, 2, 1 / 0.3]) {
      const size = avatarRenderSize(300 * scale, 300 * scale, 2);
      expect(size.width).toBeCloseTo(600 * scale);
      expect(size.height).toBeCloseTo(600 * scale);
    }
    expect(avatarRenderSize(300, 600, 3)).toEqual({ width: 600, height: 1200 });
  });

  it.each([
    [3000, 6000, 2048, 4096],
    [6000, 3000, 4096, 2048],
  ])("preserves aspect ratio for an oversized %d x %d surface", (width, height, pixelWidth, pixelHeight) => {
    expect(avatarRenderSize(width, height, 2)).toEqual({ width: pixelWidth, height: pixelHeight });
  });

  it("retains a valid canvas for an unmeasured surface", () => {
    expect(avatarRenderSize(0, 0, 0)).toEqual({ width: 1, height: 1 });
  });
});
