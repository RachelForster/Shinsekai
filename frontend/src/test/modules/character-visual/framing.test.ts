import { describe, expect, it } from "vitest";
import {
  defaultVisualFraming,
  normalizeVisualFraming,
  visualFramingStyle,
} from "../../../modules/character-visual/framing";

describe("format-independent visual framing", () => {
  it.each([undefined, null, false, "bad", [], { heightRatio: NaN, verticalPosition: Infinity }])(
    "defaults safely for %j",
    (value) => {
      expect(normalizeVisualFraming(value)).toEqual(defaultVisualFraming);
      expect(visualFramingStyle(value)).toBeUndefined();
    },
  );
  it("clamps both fields without coercing untrusted strings", () => {
    expect(normalizeVisualFraming({ heightRatio: -1, verticalPosition: 2 })).toEqual({
      heightRatio: 0.2,
      verticalPosition: 1,
    });
    expect(normalizeVisualFraming({ heightRatio: 2, verticalPosition: -1 })).toEqual(defaultVisualFraming);
    expect(normalizeVisualFraming({ heightRatio: "0.5", verticalPosition: "1" })).toEqual(defaultVisualFraming);
  });
  it.each([
    [0, "0%"],
    [0.5, "-50%"],
    [1, "-100%"],
  ])("keeps the selected half inside the host at position %s", (verticalPosition, offset) => {
    expect(visualFramingStyle({ heightRatio: 0.5, verticalPosition })).toEqual({
      transform: `translateY(${offset}) scale(2)`,
      transformOrigin: "top center",
    });
  });
  it("leaves a full surface and its existing placement untouched", () => {
    expect(visualFramingStyle({ heightRatio: 1, verticalPosition: 1 })).toBeUndefined();
  });
});
