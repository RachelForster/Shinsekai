import { describe, it, expect } from "vitest";
import fixtures from "../../../../../test/fixtures/avatar/l2d_states.json";
import { parseState, validateControls, packagePath } from "../../../modules/character-visual/adapters/l2d/state";

describe("L2D state contract", () => {
  it.each(fixtures.valid)("accepts shared fixture %#", (value) => expect(parseState(value)).toEqual(value));
  it.each(fixtures.invalid)("rejects shared fixture %#", (value) => expect(() => parseState(value)).toThrow());
  it.each([NaN, Infinity, -Infinity])("rejects non-finite %s", (number) =>
    expect(() => parseState({ parameters: { A: number }, expressions: [], motion: "" })).toThrow(),
  );
  it.each(["../x", "/x", "C:/x", "https://example.com/x", "%2e%2e/x", "a\\x"])("rejects dependency %s", (path) =>
    expect(() => packagePath(path)).toThrow(),
  );
  it("checks actual SDK parameter ranges and resources", () => {
    const controls = {
      parameters: [{ id: "A", min: -1, max: 1, default: 0 }],
      expressions: ["a.exp3.json"],
      motions: ["a.motion3.json"],
    };
    expect(() => validateControls({ parameters: { A: 1 }, expressions: [], motion: "" }, controls)).not.toThrow();
    expect(() => validateControls({ parameters: { A: 2 }, expressions: [], motion: "" }, controls)).toThrow();
    expect(() => validateControls({ parameters: { unknown: 0 }, expressions: [], motion: "" }, controls)).toThrow();
    expect(() =>
      validateControls({ parameters: {}, expressions: ["unknown.exp3.json"], motion: "" }, controls),
    ).toThrow();
  });
});
