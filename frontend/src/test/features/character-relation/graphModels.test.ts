import { describe, expect, it } from "vitest";
import {
  createGraphLayout,
  reconcileGraphLayout,
  syncGraphLayout,
  resetGraphLayout,
} from "../../../features/character-relation/model/graphLayout";
import { beginGraphDrag, advanceGraphDrag } from "../../../features/character-relation/model/graphDrag";
import {
  createGraphSelection,
  selectGraphNode,
  hoverGraphNode,
  activeGraphNode,
  clearGraphSelection,
} from "../../../features/character-relation/model/graphSelection";
import type { CharacterRelationGraph } from "../../../shared/platform/types";

const graph: CharacterRelationGraph = { owner: "A", nodes: [{ key: "A" }, { key: "B" }], edges: [] };

describe("graph models", () => {
  it("reconciles added and deleted nodes without losing saved positions", () => {
    const model = createGraphLayout(graph, { A: { x: 50, y: 60 }, removed: { x: 1, y: 1 } });
    expect(Object.keys(model.positions)).toEqual(["A", "B"]);
    reconcileGraphLayout(model, { ...graph, nodes: [{ key: "A" }, { key: "C" }] });
    expect(model.positions.A).toEqual({ x: 50, y: 60 });
    expect(model.positions.B).toBeUndefined();
    expect(model.positions.C).toEqual(model.defaults.C);
  });

  it("keeps pointer-owned positions and default coordinates separate from simulation", () => {
    const model = createGraphLayout(graph);
    const defaults = structuredClone(model.defaults);
    syncGraphLayout(model, { A: { x: 10, y: 10 }, B: { x: 30, y: 40 } }, "A");
    expect(model.positions.A).toEqual(defaults.A);
    expect(model.positions.B).toEqual({ x: 30, y: 40 });
    model.positions.A.x = 99;
    expect(model.defaults).toEqual(defaults);
    resetGraphLayout(model, graph);
    expect(model.positions).toEqual(defaults);
  });

  it("ignores other pointers and only starts simulation after the movement threshold", () => {
    const drag = beginGraphDrag("A", 1, { x: 0, y: 0 }, [10, 10]);
    expect(advanceGraphDrag(drag, 2, [100, 100])).toBeUndefined();
    expect(advanceGraphDrag(drag, 1, [12, 10])).toBeUndefined();
    expect(advanceGraphDrag(drag, 1, [14, 10])).toEqual({ starting: true });
    expect(advanceGraphDrag(drag, 1, [10, 10])).toEqual({ starting: false });
  });

  it("restores pinned highlighting after hover and clears both on dismissal", () => {
    const selection = createGraphSelection();
    selectGraphNode(selection, "A");
    hoverGraphNode(selection, "B");
    expect(activeGraphNode(selection)).toBe("B");
    hoverGraphNode(selection, "");
    expect(activeGraphNode(selection)).toBe("A");
    clearGraphSelection(selection);
    expect(activeGraphNode(selection)).toBe("");
    expect(selection.selectedKey).toBe("");
  });
});
