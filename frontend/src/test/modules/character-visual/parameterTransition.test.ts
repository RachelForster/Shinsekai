import { describe, expect, it } from "vitest";
import { ParameterTransition } from "../../../modules/character-visual/adapters/l2d/parameterTransition";

describe("parameter transition", () => {
  it("uses bounded smoothstep and reaches the exact target", () => {
    const blend = new ParameterTransition(300);
    blend.sample([0, 1], 0);
    blend.start(true, 100);
    expect(blend.sample([20, 0], 90)).toEqual([0, 1]);
    expect(blend.sample([20, 0], 175)).toEqual([3.125, 0.84375]);
    expect(blend.sample([20, 0], 250)).toEqual([10, 0.5]);
    expect(blend.sample([20, 0], 400)).toEqual([20, 0]);
    expect(blend.sample([30, 1], 500)).toEqual([30, 1]);
  });

  it("retargets a running blend from its displayed pose, not its old destination", () => {
    const blend = new ParameterTransition();
    blend.sample([0], 0);
    blend.start(true, 0);
    expect(blend.sample([20], 150)).toEqual([10]);
    blend.start(true, 150);
    expect(blend.sample([-20], 150)).toEqual([10]);
    expect(blend.sample([-20], 300)).toEqual([-5]);
    expect(blend.sample([-20], 450)).toEqual([-20]);
  });

  it("is frame-rate independent and can blend toward an animated target", () => {
    const manyFrames = new ParameterTransition(),
      oneFrame = new ParameterTransition();
    for (const blend of [manyFrames, oneFrame]) {
      blend.sample([0], 0);
      blend.start(true, 0);
    }
    for (let time = 1; time < 150; time++) manyFrames.sample([time / 10], time);
    expect(manyFrames.sample([20], 150)).toEqual(oneFrame.sample([20], 150));
    expect(oneFrame.sample([30], 300)).toEqual([30]);
  });

  it("applies the first pose immediately and lets restore/edit cancel a transition", () => {
    const blend = new ParameterTransition();
    blend.start(true, 0);
    expect(blend.sample([10], 0)).toEqual([10]);
    blend.start(true, 0);
    blend.sample([20], 100);
    blend.start(false, 100);
    expect(blend.sample([-10], 100)).toEqual([-10]);
  });
});
