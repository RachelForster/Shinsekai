import { describe, expect, it } from "vitest";
import { BlinkMotion } from "../../../modules/character-visual/adapters/mmd/blink";

function peaks(values: number[]) {
  return values.filter((value, i) => value >= 0.95 && (i === 0 || values[i - 1] < 0.95)).length;
}

describe("MMD varied and contextual blinking", () => {
  it("retains spontaneous blinks with open pauses and a bounded, smooth envelope", () => {
    const blink = new BlinkMotion(() => 0.8);
    const values = Array.from({ length: 600 }, (_, i) => blink.sample(i * 20));
    expect(values.slice(0, 200).every((value) => value === 0)).toBe(true);
    expect(peaks(values)).toBe(2);
    for (let i = 1; i < values.length; i++) {
      expect(values[i]).toBeGreaterThanOrEqual(0);
      expect(values[i]).toBeLessThanOrEqual(1);
      expect(Math.abs(values[i] - values[i - 1])).toBeLessThan(0.3);
    }
  });

  it("occasionally blinks twice with a fully open gap, then rests", () => {
    const blink = new BlinkMotion(() => 0.05);
    blink.sample(0);
    blink.request("reply-start", 0);
    const values = Array.from({ length: 60 }, (_, i) => blink.sample(i * 20));
    expect(peaks(values)).toBe(2);
    expect(values.slice(20, 23).some((value) => value === 0)).toBe(true);
    expect(values.slice(40).every((value) => value === 0)).toBe(true);
  });

  it("occasionally opens more slowly without extending the closed hold", () => {
    const blink = new BlinkMotion(() => 0.2);
    blink.sample(0);
    blink.request("sentence-end", 0);
    blink.sample(100);
    expect(blink.sample(200)).toBe(1);
    expect(blink.sample(250)).toBe(1);
    expect(blink.sample(400)).toBeCloseTo(0.5);
    expect(blink.sample(550)).toBe(0);
  });

  it("merges coincident cues and drops bursts during a blink or its recovery", () => {
    const blink = new BlinkMotion(() => 0.8);
    blink.sample(0);
    blink.request("reply-start", 0);
    blink.request("gaze-shift", 0);
    blink.request("sentence-end", 0);
    const values = Array.from({ length: 70 }, (_, i) => {
      const now = i * 20;
      if (now >= 150) blink.request("gaze-shift", now);
      return blink.sample(now);
    });
    expect(peaks(values)).toBe(1);
    expect(values.slice(25).every((value) => value === 0)).toBe(true);
  });

  it("discards pending and active blinks for editing or authored blink tracks", () => {
    const blink = new BlinkMotion(() => 0.8);
    blink.sample(0);
    blink.request("reply-start", 0);
    expect(blink.sample(120)).toBe(0);
    expect(blink.sample(220)).toBe(1);
    expect(blink.sample(230, false)).toBe(0);
    blink.request("sentence-end", 240);
    expect(blink.sample(1000)).toBe(0);
    expect(blink.sample(2000)).toBe(0);
  });

  it("keeps a simple single blink when variation is disabled", () => {
    const blink = new BlinkMotion(() => 0.05);
    blink.sample(0, true, false);
    blink.request("reply-start", 0);
    const values = Array.from({ length: 55 }, (_, i) => blink.sample(i * 20, true, false));
    expect(peaks(values)).toBe(1);
    expect(values.slice(20).every((value) => value === 0)).toBe(true);
    expect(blink.sample(NaN)).toBe(0);
  });
});
