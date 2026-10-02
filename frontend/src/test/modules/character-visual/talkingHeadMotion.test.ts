import { describe, expect, it } from "vitest";
import { TalkingHeadMotion } from "../../../modules/character-visual/talkingHeadMotion";

const zero = { pitch: 0, yaw: 0, roll: 0 };

describe("shared talking head motion", () => {
  it("stays neutral without speech, including invalid inputs and audio noise", () => {
    const motion = new TalkingHeadMotion(0);
    for (const level of [0, -1, NaN, Infinity, 0.01]) {
      motion.setLevel(level);
      expect(motion.sample(0.05)).toEqual(zero);
    }
  });

  it("fades in, stays bounded and fades completely out without a pose jump", () => {
    const motion = new TalkingHeadMotion(1);
    motion.setLevel(2);
    expect(motion.sample(0)).toEqual(zero);
    const start = motion.sample(1 / 60);
    expect(Math.abs(start.yaw)).toBeLessThan(0.005);
    const samples = Array.from({ length: 600 }, () => motion.sample(1 / 60));
    for (const sample of samples) {
      expect(Math.abs(sample.pitch)).toBeLessThanOrEqual((1.6 * Math.PI) / 180);
      expect(Math.abs(sample.yaw)).toBeLessThanOrEqual((2.2 * Math.PI) / 180);
      expect(Math.abs(sample.roll)).toBeLessThanOrEqual((0.8 * Math.PI) / 180);
    }
    expect(new Set(samples.map((sample) => sample.yaw)).size).toBe(600);
    motion.setLevel(0);
    const fading = motion.sample(1 / 60);
    expect(Math.abs(fading.yaw - samples.at(-1)!.yaw)).toBeLessThan(0.005);
    for (let i = 0; i < 150; i++) motion.sample(1 / 60);
    expect(motion.sample(1 / 60)).toEqual(zero);
  });

  it("is frame-rate independent and gives different instances distinct rhythms", () => {
    const sample = (fps: number, phase = 1) => {
      const motion = new TalkingHeadMotion(phase);
      motion.setLevel(0.7);
      let result = zero;
      for (let i = 0; i < fps * 2; i++) result = motion.sample(1 / fps);
      return result;
    };
    const a = sample(30);
    const b = sample(60);
    for (const axis of ["pitch", "yaw", "roll"] as const) expect(a[axis]).toBeCloseTo(b[axis], 10);
    expect(sample(60, 2)).not.toEqual(b);
  });

  it("disables immediately for editing/reduced motion and restarts gently", () => {
    const motion = new TalkingHeadMotion(1);
    motion.setLevel(1);
    for (let i = 0; i < 30; i++) motion.sample(0.05);
    expect(motion.sample(0.05, false)).toEqual(zero);
    expect(Math.abs(motion.sample(1 / 60).yaw)).toBeLessThan(0.005);
    motion.reset();
    expect(motion.sample(0.05)).toEqual(zero);
    motion.setLevel(1);
    expect(motion.sample(NaN)).toEqual(zero);
    expect(motion.sample(-1)).toEqual(zero);
  });
});
