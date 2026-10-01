import { describe, expect, it } from "vitest";
import {
  blinkClosure,
  defaultCamera,
  detectBindings,
  neutralState,
  parseState,
  validateControls,
} from "../../../modules/character-visual/adapters/mmd/state";

const controls = {
  morphs: [
    { name: "笑顔", englishName: "Smile", category: 2 },
    { name: "あ", englishName: "A", category: 3 },
    { name: "まばたき", englishName: "Blink", category: 2 },
  ],
};

describe("MMD morph state", () => {
  it("keeps relative motion references and remains compatible with morph-only states", () => {
    const state = { ...neutralState(), motion: "states/abc/0/motion.vmd" };
    expect(parseState(state)).toEqual(state);
    expect(parseState({ ...state, motion: "" })).toEqual(neutralState());
  });
  it.each([
    "../pose.vpd",
    "/pose.vpd",
    "C:/pose.vpd",
    "a\\pose.vpd",
    "%2e%2e/pose.vpd",
    "pose.vpd?x",
    "pose.json",
    null,
  ])("rejects unsafe/invalid motion reference %j", (motion) => {
    expect(() => parseState({ ...neutralState(), motion })).toThrow();
  });
  it("normalizes older states and preserves saved camera settings", () => {
    expect(parseState({ morphs: {}, mouthMorph: "", blinkMorph: "" }).camera).toEqual(defaultCamera());
    const state = { ...neutralState(), camera: { yaw: 35, pitch: -10, zoom: 2, panX: 0.1, panY: -0.2 } };
    expect(parseState(JSON.parse(JSON.stringify(state)))).toEqual(state);
  });

  it.each([
    null,
    {},
    { ...defaultCamera(), unknown: 1 },
    { ...defaultCamera(), yaw: 181 },
    { ...defaultCamera(), pitch: -81 },
    { ...defaultCamera(), zoom: 0 },
    { ...defaultCamera(), panX: 2 },
    { ...defaultCamera(), panY: Number.NaN },
  ])("rejects invalid camera settings %j", (camera) => {
    expect(() => parseState({ ...neutralState(), camera })).toThrow();
  });

  it("detects PMX mouth and blink morphs and preserves their bindings", () => {
    const bindings = detectBindings(controls.morphs);
    expect(bindings).toEqual({ mouthMorph: "あ", blinkMorph: "まばたき" });
    const state = { ...neutralState(bindings.mouthMorph, bindings.blinkMorph), morphs: { 笑顔: 0.6 } };
    expect(parseState(state)).toEqual(state);
    expect(() => validateControls(state, controls)).not.toThrow();
  });

  it("rejects invalid and unknown morphs", () => {
    expect(() => parseState({ ...neutralState(), morphs: { 笑顔: Number.NaN } })).toThrow();
    expect(() => parseState({ ...neutralState(), morphs: { 笑顔: 2 } })).toThrow();
    expect(() => validateControls({ ...neutralState(), mouthMorph: "not-a-morph" }, controls)).toThrow();
    expect(() => validateControls({ ...neutralState(), morphs: { unknown: 0.5 } }, controls)).toThrow();
  });

  it("falls back to PMX category when names differ", () => {
    expect(detectBindings([{ name: "lip_custom", englishName: "", category: 3 }])).toEqual({
      mouthMorph: "lip_custom",
      blinkMorph: "",
    });
  });

  it("drives a smooth automatic blink envelope", () => {
    expect([0, 50, 100, 150, 225, 300].map(blinkClosure)).toEqual([0, 0.5, 1, 1, 0.5, 0]);
  });
});
