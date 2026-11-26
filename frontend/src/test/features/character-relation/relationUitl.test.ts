import { describe, expect, it } from "vitest";

import { normalizeRelationName } from "../../../features/character-relation/model/relationUitl";

describe("normalizeRelationName", () => {
  it("normalizes character names", () => {
    expect(normalizeRelationName(" B ")).toBe("b");
  });
});
