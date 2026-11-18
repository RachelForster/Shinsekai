import { describe, expect, it } from "vitest";
import { emptyState, parseState } from "../../../modules/character-visual/adapters/vrm/state";
import cases from "../../fixtures/vrm-states.json";
describe("VRM state boundary", () => {
  it.each(cases)("matches shared state fixture: $name", ({ state, valid }) => {
    if (valid) expect(() => parseState(state)).not.toThrow();
    else expect(() => parseState(state)).toThrow();
  });
  it("copies editable state without aliasing", () => {
    const state = {
      ...emptyState(),
      expressions: { happy: 0.7 },
      bones: { head: [0, 0, 0, 1] as [number, number, number, number] },
    };
    const copy = parseState(state);
    copy.expressions.happy = 0;
    expect(state.expressions.happy).toBe(0.7);
  });
  it("copies optional motion timing and rejects missing or unordered boundaries", () => {
    const timing = { entryStart: 0.6, bodyStart: 2, bodyEnd: 4, exitEnd: 5 };
    const value = { ...emptyState(), motion: "motion.vrma", motionTiming: timing };
    const parsed = parseState(value);
    parsed.motionTiming!.entryStart = 1;
    expect(timing.entryStart).toBe(0.6);
    expect(() => parseState({ ...value, motionTiming: { ...timing, bodyStart: 0 } })).toThrow();
    expect(() => parseState({ ...value, motionTiming: { entryStart: 0 } })).toThrow();
    expect(() => parseState({ ...value, motion: "" })).toThrow();
    expect(() => parseState({ ...value, motionTiming: { ...timing, exitEnd: Infinity } })).toThrow();
  });
  it.each([
    { expressions: { happy: NaN } },
    { expressions: { happy: 2 } },
    { bones: { head: [0, 0, 0, 0] } },
    { motion: "../out.vrma" },
    { motion: "https://bad/test.vrma" },
    { extra: true },
  ])("rejects invalid state %j", (patch) => {
    expect(() => parseState({ ...emptyState(), ...patch })).toThrow();
  });
});
