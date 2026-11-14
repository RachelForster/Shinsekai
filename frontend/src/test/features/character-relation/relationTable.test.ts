import { describe, expect, it } from "vitest";

import {
  convertGraphToRows,
  tableOperations,
  type RelationRow,
} from "../../../features/character-relation/model/relationTable";
import type { CharacterRelationGraph } from "../../../shared/platform/types";

const nodes = [{ key: "A" }, { key: "B" }];

function createRows(overrides: Partial<RelationRow> = {}): RelationRow[] {
  return [
    {
      source: "A",
      target: "B",
      relation: "Friends",
      temperature: "8",
      ...overrides,
    },
    { source: "", target: "", relation: "", temperature: "0" },
  ];
}

describe("tableOperations", () => {
  it("converts an edited relationship row into an edge operation", () => {
    const rows = createRows();
    expect(tableOperations(rows, nodes)).toEqual([
      { op: "upsert_edge", edge: { source: "A", target: "B", content: "Friends", temperature: 8 } },
    ]);
  });

  it("returns no operations for an unchanged relationship", () => {
    const rows = createRows({
      edge: { source: "A", target: "B", content: "Friends", temperature: 8 },
    });
    expect(tableOperations(rows, nodes)).toEqual([]);
  });

  it.each([
    ["an out-of-range temperature", { temperature: "11" }, "invalidTemperature"],
    ["relationship text longer than 100 characters", { relation: "雪".repeat(101) }, "invalidRelation"],
  ] as const)("rejects %s", (_condition, overrides, message) => {
    const rows = createRows(overrides);
    expect(() => tableOperations(rows, nodes)).toThrow(message);
  });

  it("rejects duplicate directed relationships", () => {
    const rows = createRows();
    Object.assign(rows[1], { source: "A", target: "B" });
    expect(() => tableOperations(rows, nodes)).toThrow("duplicateEdge");
  });

  it("validates endpoints against the graph nodes", () => {
    const rows = createRows({ target: "Missing" });
    expect(() => tableOperations(rows, nodes)).toThrow("invalidEndpoints");
    expect(tableOperations(rows, [...nodes, { key: "Missing" }])).toEqual([
      { op: "upsert_edge", edge: { source: "A", target: "Missing", content: "Friends", temperature: 8 } },
    ]);
  });

  it("preserves newlines in relationship text at the 100-character limit", () => {
    const content = "First line\n" + "雪".repeat(89);
    const rows = createRows({ relation: content });
    expect(tableOperations(rows, nodes)).toEqual([
      { op: "upsert_edge", edge: { source: "A", target: "B", content, temperature: 8 } },
    ]);
  });

  it("preserves relationship text when only the temperature changes", () => {
    const rows = createRows({
      temperature: "9",
      edge: { source: "A", target: "B", content: "Friends", temperature: 8 },
    });
    expect(tableOperations(rows, nodes)).toEqual([
      { op: "upsert_edge", edge: { source: "A", target: "B", content: "Friends", temperature: 9 } },
    ]);
  });
});

describe("convertGraphToRows", () => {
  it("creates rows for edges and one blank row independently of node count", () => {
    const graph: CharacterRelationGraph = {
      owner: "A",
      nodes: [{ key: "A" }, { key: "B" }, { key: "C" }],
      edges: [],
    };
    expect(convertGraphToRows(graph)).toHaveLength(1);
    expect(tableOperations(convertGraphToRows(graph), graph.nodes)).toEqual([]);
    graph.edges = [{ source: "A", target: "B", content: "Friends", temperature: 8 }];
    expect(convertGraphToRows(graph)).toHaveLength(2);
    expect(tableOperations(convertGraphToRows(graph), graph.nodes)).toEqual([]);
  });

  it("preserves multiline relationship text in the editable row", () => {
    const graph: CharacterRelationGraph = {
      owner: "A",
      nodes: [{ key: "A" }, { key: "B" }],
      edges: [{ source: "A", target: "B", content: "First line\nSecond line", temperature: 0 }],
    };
    expect(convertGraphToRows(graph)[0].relation).toBe("First line\nSecond line");
  });
});
