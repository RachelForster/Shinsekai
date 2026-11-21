import { describe, expect, it } from "vitest";

import { graphSeries } from "../../../features/character-relation/view/buildGraphSeries";
import type { CharacterRelationGraph } from "../../../shared/platform/types";

describe("graphSeries", () => {
  it("uses the selected owner's separately supplied relationship group", () => {
    const edge = { source: "A", target: "B", content: "A view", temperature: 0 };
    const positions = { A: { x: 0, y: 0 }, B: { x: 100, y: 0 } };
    const series = graphSeries(
      {
        graph: { owner: "A", nodes: [{ key: "A" }, { key: "B" }], edges: [] },
        positions,
        labelPositions: positions,
        activeNodeKey: "B",
        emptyRelationLabel: "",
        textColor: "#fff",
        backgroundColor: "#000",
      },
      [
        { owner: "A", nodes: [], edges: [edge] },
        { owner: "B", nodes: [], edges: [{ ...edge, content: "B view" }] },
      ],
    );
    const links = series.links as Array<{ id: string; label: { show: boolean; formatter: () => string } }>;
    expect(links[0].id).not.toBe(links[1].id);
    expect(links[0].label.show).toBe(false);
    expect(links[1].label.show).toBe(true);
    expect(links[1].label.formatter()).toBe("B view");
  });

  it("uses the selected character color for its node border", () => {
    const graph: CharacterRelationGraph = {
      owner: "A",
      nodes: [{ key: "A" }, { key: "B" }],
      edges: [],
    };
    const series = graphSeries(
      {
        graph: graph,
        positions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 } },
        labelPositions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 } },
        activeNodeKey: "A",
        emptyRelationLabel: "",
        textColor: "#fff",
        backgroundColor: "#000",
        characters: [{ name: " a ", color: "#123abc" }],
      },
      [graph],
    );
    expect(series.data).toMatchObject([
      { itemStyle: { borderColor: "#123abc" } },
      { itemStyle: { borderColor: "#fff" } },
    ]);
  });

  it("uses the default border color when no node is selected", () => {
    const graph: CharacterRelationGraph = {
      owner: "A",
      nodes: [{ key: "A" }],
      edges: [],
    };
    const series = graphSeries(
      {
        graph: graph,
        positions: { A: { x: 0, y: 0 } },
        labelPositions: { A: { x: 0, y: 0 } },
        activeNodeKey: "",
        emptyRelationLabel: "",
        textColor: "#fff",
        backgroundColor: "#000",
        characters: [{ name: "A", color: "#123abc" }],
      },
      [graph],
    );
    expect(series.data).toMatchObject([{ itemStyle: { borderColor: "#fff" } }]);
  });

  it("shows the hovered character color without requiring selection", () => {
    const series = graphSeries(
      {
        graph: { owner: "A", nodes: [{ key: "A" }, { key: "B" }], edges: [] },
        positions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 } },
        labelPositions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 } },
        activeNodeKey: "B",
        selectedNodeKey: "",
        emptyRelationLabel: "",
        textColor: "#fff",
        backgroundColor: "#000",
        characters: [{ name: "B", color: "#123abc" }],
      },
      [{ owner: "A", nodes: [{ key: "A" }, { key: "B" }], edges: [] }],
    );
    expect(series.data).toMatchObject([
      { itemStyle: { borderColor: "#fff" } },
      { itemStyle: { borderColor: "#123abc" } },
    ]);
  });

  it("keeps all edges while highlighting the active owner’s relationships", () => {
    const graph: CharacterRelationGraph = {
      owner: "A",
      nodes: [{ key: "A" }, { key: "B" }, { key: "C" }],
      edges: [
        { source: "A", target: "B", temperature: 1, content: "A to B" },
        { source: "B", target: "A", temperature: 2, content: "B to A" },
        { source: "B", target: "C", temperature: 3, content: "B to C" },
      ],
    };
    const series = graphSeries(
      {
        graph: graph,
        positions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 }, C: { x: 200, y: 0 } },
        labelPositions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 }, C: { x: 200, y: 0 } },
        activeNodeKey: "B",
        emptyRelationLabel: "",
        textColor: "#fff",
        backgroundColor: "#000",
      },
      [
        { ...graph, edges: [graph.edges[0]] },
        { ...graph, owner: "B", edges: graph.edges.slice(1) },
      ],
    );
    expect(series.links?.map(({ source, target, label }) => ({ source, target, show: label?.show }))).toEqual([
      { source: "A", target: "B", show: false },
      { source: "B", target: "A", show: true },
      { source: "B", target: "C", show: true },
    ]);
    expect(series.links?.[0].lineStyle?.opacity).toBe(0.1);
    expect(series.links?.[1].lineStyle?.opacity).toBe(1);
  });

  it("shows all edges dimly when no node is active", () => {
    const series = graphSeries(
      {
        graph: {
          owner: "A",
          nodes: [{ key: "A" }, { key: "B" }, { key: "C" }],
          edges: [
            { source: "A", target: "B", temperature: 0, content: "first" },
            { source: "B", target: "C", temperature: 0, content: "second" },
          ],
        },
        positions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 }, C: { x: 200, y: 0 } },
        labelPositions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 }, C: { x: 200, y: 0 } },
        activeNodeKey: "",
        selectedNodeKey: "",
        emptyRelationLabel: "",
        textColor: "#fff",
        backgroundColor: "#000",
      },
      [
        {
          owner: "A",
          nodes: [{ key: "A" }, { key: "B" }, { key: "C" }],
          edges: [
            { source: "A", target: "B", temperature: 0, content: "first" },
            { source: "B", target: "C", temperature: 0, content: "second" },
          ],
        },
      ],
    );
    expect(series.links).toHaveLength(2);
    expect(series.links?.map((edge) => [edge.label?.show, edge.lineStyle?.opacity])).toEqual([
      [false, 0.45],
      [false, 0.45],
    ]);
  });

  it("uses the graph foreground color for relationship lines", () => {
    const graph: CharacterRelationGraph = {
      owner: "A",
      nodes: [{ key: "A" }, { key: "B" }],
      edges: [{ source: "A", target: "B", temperature: 8, content: "Friends" }],
    };
    const series = graphSeries(
      {
        graph: graph,
        positions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 } },
        labelPositions: { A: { x: 0, y: 0 }, B: { x: 100, y: 0 } },
        activeNodeKey: "A",
        emptyRelationLabel: "",
        textColor: "#fff",
        backgroundColor: "#000",
      },
      [graph],
    );
    expect(series.links?.[0].lineStyle?.color).toBe("#fff");
  });
});
