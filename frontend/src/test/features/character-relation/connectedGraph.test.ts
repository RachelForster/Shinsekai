import { describe, expect, it } from "vitest";
import { connectedGraph } from "../../../features/character-relation/view/connectedGraph";

describe("connectedGraph", () => {
  it("finds owners through all nodes, including isolated and transitive nodes", () => {
    const root = { owner: "A", nodes: [{ key: "A" }], edges: [] };
    const people = [
      { name: "A", relation_graph: root },
      { name: "B", relation_graph: { nodes: [{ key: "B" }, { key: "A" }, { key: "C" }], edges: [] } },
      { name: "C", relation_graph: { nodes: [{ key: "C" }, { key: "D" }], edges: [] } },
      { name: "Unrelated", relation_graph: { nodes: [{ key: "Unrelated" }], edges: [] } },
    ];
    const result = connectedGraph(root, people);
    expect(result.nodes.map((n) => n.key)).toEqual(["A", "B", "C", "D"]);
    expect(result.graphs.map((graph) => graph.owner)).toEqual(["A", "B", "C"]);
  });

  it("keeps conflicting relationship descriptions in their owner groups", () => {
    const edge = { source: "A", target: "B", content: "A view", temperature: 0 };
    const root = { owner: "A", nodes: [{ key: "A" }, { key: "B" }], edges: [edge] };
    const result = connectedGraph(root, [
      { name: "B", relation_graph: { nodes: root.nodes, edges: [{ ...edge, content: "B view" }] } },
    ]);
    expect(result.graphs.map((graph) => [graph.owner, graph.edges[0].content])).toEqual([
      ["A", "A view"],
      ["B", "B view"],
    ]);
    expect(result.edges).toHaveLength(2);
    expect(result.edges[0]).toMatchObject({ source: "A", target: "B" });
    expect(result.edges.map((edge) => edge.content)).toEqual(["A view", "B view"]);
  });

  it("normalizes edge endpoints for rendering without changing the personal graph", () => {
    const root = {
      owner: "A",
      nodes: [{ key: "A" }, { key: "b" }],
      edges: [{ source: "A", target: "b", content: "friend", temperature: 0 }],
    };
    const result = connectedGraph(root, [{ name: "B", relation_graph: { nodes: [{ key: "B" }], edges: [] } }]);
    expect(result.graphs[0].edges[0].target).toBe("B");
    expect(result.edges[0].target).toBe("B");
    expect(root.edges[0].target).toBe("b");
  });
});
