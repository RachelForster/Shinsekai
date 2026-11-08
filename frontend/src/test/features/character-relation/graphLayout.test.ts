import { readPositions, savePositions } from "../../../features/character-relation/model/graphLayoutStorage";
import { beforeEach, describe, expect, it } from "vitest";

import { applyLongEdgeAttraction, longEdgeAttraction } from "../../../features/character-relation/model/graphLayout";

describe("applyLongEdgeAttraction", () => {
  it.each([0, longEdgeAttraction.threshold / 2, longEdgeAttraction.threshold])(
    "does not move connected nodes at distance %s within the threshold",
    (distance) => {
      const positions = { A: { x: 0, y: 0 }, B: { x: distance, y: 0 } };
      applyLongEdgeAttraction(positions, [{ source: "A", target: "B" }], new Set());
      expect(positions).toEqual({ A: { x: 0, y: 0 }, B: { x: distance, y: 0 } });
    },
  );

  it("moves both ends of a long edge toward their shared midpoint", () => {
    const positions = { A: { x: 0, y: 0 }, B: { x: 500, y: 0 } };
    applyLongEdgeAttraction(positions, [{ source: "A", target: "B" }], new Set());
    expect(positions.A.x).toBeGreaterThan(0);
    expect(positions.B.x).toBeLessThan(500);
    expect(positions.A.x + positions.B.x).toBe(500);
  });

  it("leaves nodes without edges unchanged", () => {
    const positions = { A: { x: 0, y: 0 }, B: { x: 500, y: 0 }, C: { x: 900, y: 0 } };
    applyLongEdgeAttraction(positions, [{ source: "A", target: "B" }], new Set());
    expect(positions.C).toEqual({ x: 900, y: 0 });
  });

  it("increases movement as an edge grows longer", () => {
    const shorter = { A: { x: 0, y: 0 }, B: { x: longEdgeAttraction.threshold + 100, y: 0 } };
    const longer = { A: { x: 0, y: 0 }, B: { x: longEdgeAttraction.threshold + 200, y: 0 } };
    const edges = [{ source: "A", target: "B" }];
    applyLongEdgeAttraction(shorter, edges, new Set());
    applyLongEdgeAttraction(longer, edges, new Set());
    expect(longer.A.x).toBeGreaterThan(shorter.A.x);
  });

  it.each([0, 0.5])("scales movement by the cooling factor %s", (cooling) => {
    const full = { A: { x: 0, y: 0 }, B: { x: 500, y: 0 } };
    const cooled = structuredClone(full);
    const edges = [{ source: "A", target: "B" }];
    applyLongEdgeAttraction(full, edges, new Set());
    applyLongEdgeAttraction(cooled, edges, new Set(), cooling);
    expect(cooled.A.x).toBe(full.A.x * cooling);
  });

  it("keeps a dragged node fixed", () => {
    const positions = { A: { x: 0, y: 0 }, B: { x: 400, y: 300 } };
    applyLongEdgeAttraction(positions, [{ source: "A", target: "B" }], new Set(["A"]));
    expect(positions.A).toEqual({ x: 0, y: 0 });
  });

  it("counts reciprocal edges as one attraction", () => {
    const single = { A: { x: 0, y: 0 }, B: { x: 400, y: 300 } };
    const reciprocal = structuredClone(single);
    applyLongEdgeAttraction(single, [{ source: "A", target: "B" }], new Set());
    applyLongEdgeAttraction(
      reciprocal,
      [
        { source: "A", target: "B" },
        { source: "B", target: "A" },
      ],
      new Set(),
    );
    expect(reciprocal).toEqual(single);
  });

  it("caps movement accumulated from multiple long edges", () => {
    const positions = { A: { x: 0, y: 0 }, B: { x: 10000, y: 0 }, C: { x: 10000, y: 0 } };
    applyLongEdgeAttraction(
      positions,
      [
        { source: "A", target: "B" },
        { source: "A", target: "C" },
      ],
      new Set(),
    );
    expect(positions.A).toEqual({ x: longEdgeAttraction.maxStep, y: 0 });
  });
});

describe("saved graph positions", () => {
  beforeEach(() => localStorage.clear());

  it("reads positions saved for the same owner", () => {
    const positions = { A: { x: 5, y: 9 } };
    savePositions("A", positions);
    expect(readPositions("A")).toEqual(positions);
  });

  it("does not read another owner's saved positions", () => {
    savePositions("A", { A: { x: 5, y: 9 } });
    expect(readPositions("B")).toEqual({});
  });

  it("ignores invalid coordinates while retaining valid entries", () => {
    localStorage.setItem("character-relation-layout:v1:A", '{"A":{"x":"oops","y":9},"B":{"x":1,"y":2}}');
    expect(readPositions("A")).toEqual({ B: { x: 1, y: 2 } });
  });

  it("returns no positions for malformed JSON", () => {
    localStorage.setItem("character-relation-layout:v1:A", "bad json");
    expect(readPositions("A")).toEqual({});
  });
});
