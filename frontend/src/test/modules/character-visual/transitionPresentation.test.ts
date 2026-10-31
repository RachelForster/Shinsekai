import { expect, it } from "vitest";
import { transitionAdjustment } from "../../../modules/character-visual/transitionPresentation";
import type { SpriteFramePresentation } from "../../../shared/assets/spriteTransition";

const reference: SpriteFramePresentation = { width: 480, height: 768, bounds: [0.1, 0, 0.9, 1], luma: 100 };
const padded: SpriteFramePresentation = { width: 480, height: 800, bounds: [0.1, 0.02, 0.9, 0.98], luma: 96 };
const presentation = { from: padded, first: padded, last: padded, to: reference };

it("matches a padded 480x800 bridge to a 480x768 target without changing the target", () => {
  expect(transitionAdjustment(presentation, 0, 0.625)).toEqual({ scale: 1, x: 0, y: 0, brightness: 1 });
  const end = transitionAdjustment(presentation, 1, 0.625);
  expect(end.scale).toBeCloseTo(800 / 768);
  expect(end.y).toBeCloseTo(0);
  expect(end.brightness).toBeCloseTo(100 / 96);
  expect(transitionAdjustment(presentation, 0.5, 0.625).scale).toBeCloseTo((1 + 800 / 768) / 2);
});

it("keeps reference placement correct when the stage is too narrow for a full-height sprite", () => {
  const end = transitionAdjustment(presentation, 1, 0.4);
  expect(end.scale).toBeCloseTo(1);
  expect(end.y).toBeCloseTo(0.0133333333333333);
});

it("bounds corrections and tolerates missing or unusable calibration", () => {
  expect(transitionAdjustment(undefined, 0.5, 1)).toEqual({ scale: 1, x: 0, y: 0, brightness: 1 });
  const extreme = { ...padded, bounds: [0.4, 0.4, 0.6, 0.6] as [number, number, number, number], luma: 1 };
  const end = transitionAdjustment({ ...presentation, last: extreme }, 2, 0.625);
  expect(end.scale).toBe(1.12);
  expect(end.brightness).toBe(1);
  expect(Math.abs(end.y)).toBeLessThanOrEqual(0.08);
});
