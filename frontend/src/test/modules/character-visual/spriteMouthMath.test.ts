import { expect, it } from "vitest";
import { mouthMatrixAt, mouthPatchMatrix, mouthPose } from "../../../modules/character-visual/spriteMouthMath";
import type { SpriteMouthManifest } from "../../../shared/platform/types";

const profile: SpriteMouthManifest = {
  version: 1,
  width: 512,
  height: 672,
  fps: 24,
  duration: 2,
  patchBox: [240, 280, 280, 300],
  mouths: { closed: "c.png", half: "h.png", open: "o.png" },
  correction: { offsetX: 0, offsetY: 0, scale: 1, rotation: 0, gain: 1 },
  track: [
    { time: 0, matrix: [1, 0, 0, 1, 0, 0] },
    { time: 2, matrix: [1, 0, 0, 1, 10, 20] },
  ],
};

it("uses hysteresis to avoid flicker and closes immediately during silence", () => {
  expect(mouthPose(0.07, "closed")).toBe("closed");
  expect(mouthPose(0.07, "half")).toBe("half");
  expect(mouthPose(0.4, "open")).toBe("open");
  expect(mouthPose(0.4, "half")).toBe("half");
  expect(mouthPose(0.6)).toBe("open");
  expect(mouthPose(0, "open")).toBe("closed");
  expect(mouthPose(NaN, "open")).toBe("closed");
  expect(mouthPose(0.3, "half", 2)).toBe("open");
});

it("interpolates by decoded video time, including seek and loop back to zero", () => {
  expect(mouthMatrixAt(profile, 1)).toEqual([1, 0, 0, 1, 5, 10]);
  expect(mouthMatrixAt(profile, 9)).toEqual([1, 0, 0, 1, 10, 20]);
  expect(mouthMatrixAt(profile, 0)).toEqual([1, 0, 0, 1, 0, 0]);
  expect(mouthMatrixAt({ ...profile, track: profile.track.slice(0, 1) }, 100)).toEqual([1, 0, 0, 1, 0, 0]);
});

it("applies correction around the mouth center before head tracking", () => {
  expect(mouthPatchMatrix(profile, 1)).toEqual([1, 0, 0, 1, 245, 290]);
  const result = mouthPatchMatrix(
    { ...profile, correction: { ...profile.correction, scale: 2, offsetX: 3, offsetY: -2 } },
    1,
  );
  // The patch's center remains at (260, 290), plus correction and the current head translation.
  expect(result[0]).toBe(2);
  expect(result[3]).toBe(2);
  expect(result[0] * 20 + result[4]).toBe(268);
  expect(result[3] * 10 + result[5]).toBe(298);
});
