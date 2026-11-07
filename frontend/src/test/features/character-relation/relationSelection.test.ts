import { describe, expect, it } from "vitest";

import { normalizeRelationName, relationOwnerKey } from "../../../features/character-relation/relationSelection";
import type { CharacterRelationGraph } from "../../../shared/platform/types";

function createGraph(keys: string[]): CharacterRelationGraph {
  return { owner: "A", nodes: keys.map((key) => ({ key })), edges: [], };
}

describe("relationOwnerKey", () => {
  it("prefers an exact owner match", () => {
    expect(relationOwnerKey(createGraph(["a", "A"]))).toBe("A");
  });

  it("matches the owner without case or surrounding whitespace", () => {
    expect(relationOwnerKey(createGraph([" a ", "B"]))).toBe(" a ");
  });

  it("falls back to the owner name when no node matches", () => {
    expect(relationOwnerKey(createGraph(["B"]))).toBe("A");
  });

  it("normalizes names used by the picker", () => {
    expect(normalizeRelationName(" B ")).toBe("b");
  });
});
