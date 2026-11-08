import { init, use, type EChartsType } from "echarts/core";
import { GraphChart } from "echarts/charts";
import { SVGRenderer } from "echarts/renderers";
import { describe, expect, it } from "vitest";
import { graphSeries } from "../../../features/character-relation/view/buildGraphSeries";
import {
  installGraphBounds,
  readGraphPositions,
  seedGraphPositions,
} from "../../../features/character-relation/model/manageGraphLayout";
import type { CharacterRelationGraph } from "../../../shared/platform/types";

use([GraphChart, SVGRenderer]);

// Minimal contracts for the ECharts internals inspected by these tests.
interface ForceSimulation {
  warmUp(): void;
  step(callback?: (stopped: boolean) => void): void;
}

interface NodeSymbol {
  getBoundingRect(): { width: number; height: number };
  getComputedTransform(): number[];
}

interface NodeGraphic {
  getSymbolPath(): NodeSymbol;
}

interface GraphNodeData {
  getItemGraphicEl(index: number): NodeGraphic;
}

interface GraphSeriesModel {
  forceLayout: ForceSimulation;
  getData(): GraphNodeData;
}

interface ChartModel {
  getSeriesByIndex(index: number): GraphSeriesModel;
}

function graphModel(chart: EChartsType): GraphSeriesModel {
  const runtime = chart as unknown as { getModel(): ChartModel };
  return runtime.getModel().getSeriesByIndex(0);
}

function renderedNodeSize(chart: EChartsType, index: number) {
  const symbol = graphModel(chart).getData().getItemGraphicEl(index).getSymbolPath();
  const bounds = symbol.getBoundingRect();
  const [a, b, c, d] = symbol.getComputedTransform();
  // Matrix columns give the horizontal and vertical scale, including rotation.
  return {
    width: bounds.width * Math.hypot(a, b),
    height: bounds.height * Math.hypot(c, d),
  };
}

function expectEqualNodeDimensions(chart: EChartsType, nodeIndices: number[]): void {
  for (const index of nodeIndices) {
    const { width, height } = renderedNodeSize(chart, index);
    expect(width, `node ${index} has a visible size`).toBeGreaterThan(0);
    expect(width, `node ${index} preserves its circular proportions`).toBeCloseTo(height, 5);
  }
}

describe("ECharts force layout", () => {
  it("keeps the entire chain in the simulation while A is selected and fixed", () => {
    const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 1200, height: 800 });
    const graph: CharacterRelationGraph = {
      owner: "A", nodes: ["A", "B", "C"].map((key) => ({ key })),
      edges: [
        { source: "A", target: "B", temperature: 0, content: "first" },
        { source: "B", target: "C", temperature: 0, content: "second" },
      ],
    };
    const series = graphSeries({
      graph, positions: { A: { x: -400, y: 0 }, B: { x: 0, y: 0 }, C: { x: 400, y: 0 } },
      activeNodeKey: "A", selectedNodeKey: "A", fixedKeys: new Set(["A"]),
      emptyRelationLabel: "", textColor: "#fff", backgroundColor: "#000",
    });
    try {
      chart.setOption({ series: [{ ...series, force: { ...series.force, repulsion: 0, gravity: 0, layoutAnimation: false } }] });
      const before = readGraphPositions(chart);
      installGraphBounds(chart);
      const force = graphModel(chart).forceLayout;
      force.warmUp();
      for (let tick = 0; tick < 100; tick++) force.step();
      const after = readGraphPositions(chart);
      expect(after.C.x - after.B.x).toBeLessThan(before.C.x - before.B.x);
    } finally {
      chart.dispose();
    }
  });

  it("keeps repelling nodes against the walls without bouncing back inward", () => {
    const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 640, height: 560 });
    const graph: CharacterRelationGraph = {
      owner: "A",

      nodes: ["A", "B"].map((key) => ({ key })),
      edges: [],
    };
    const series = graphSeries({
      graph: graph,
      positions: { A: { x: -400, y: 0 }, B: { x: 400, y: 0 } },
      activeNodeKey: "",
      emptyRelationLabel: "",
      textColor: "#fff",
      backgroundColor: "#000",
    });
    try {
      chart.setOption({ series: [{ ...series, force: { ...series.force, gravity: 0, layoutAnimation: false } }] });
      installGraphBounds(chart);
      const force = graphModel(chart).forceLayout;
      force.warmUp();
      const previous = readGraphPositions(chart);
      for (let tick = 0; tick < 80; tick++) {
        force.step();
        const next = readGraphPositions(chart);
        expect(next.A.x).toBeCloseTo(previous.A.x, 6);
        expect(next.B.x).toBeCloseTo(previous.B.x, 6);
      }
    } finally {
      chart.dispose();
    }
  });

  it.each(["contracts a long edge", "stops the simulation"])("%s after installing the attraction hook", (result) => {
    const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 1200, height: 800 });
    const graph: CharacterRelationGraph = {
      owner: "A",

      nodes: ["A", "B"].map((key) => ({ key })),
      edges: [{ source: "A", target: "B", temperature: 0, content: "" }],
    };
    const positions = { A: { x: -400, y: 0 }, B: { x: 400, y: 0 } };
    const series = graphSeries({
      graph: graph,
      positions: positions,
      activeNodeKey: "",
      emptyRelationLabel: "",
      textColor: "#fff",
      backgroundColor: "#000",
      fixedKeys: new Set(["A"]),
    });
    try {
      chart.setOption({
        series: [{ ...series, force: { ...series.force, repulsion: 0, gravity: 0, layoutAnimation: false } }],
      });
      const before = readGraphPositions(chart);
      installGraphBounds(chart);
      const force = graphModel(chart).forceLayout;
      force.warmUp();
      let stopped = false;
      for (let tick = 0; tick < 1000 && !stopped; tick++)
        force.step((done) => {
          stopped = done;
        });
      const after = readGraphPositions(chart);
      if (result === "stops the simulation") expect(stopped).toBe(true);
      else expect(after.B.x - after.A.x).toBeLessThan(before.B.x - before.A.x - 10);
    } finally {
      chart.dispose();
    }
  });

  it("renders round nodes in wide and tall viewports, including after zoom", () => {
    const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 1000, height: 400 });
    const graph: CharacterRelationGraph = {
      owner: "A",
      nodes: ["A", "B"].map((key) => ({ key })),
      edges: [],
    };
    const series = graphSeries({
      graph: graph,
      positions: { A: { x: 0, y: 0 }, B: { x: 200, y: 100 } },
      activeNodeKey: "",
      emptyRelationLabel: "",
      textColor: "#fff",
      backgroundColor: "#000",
      fixedKeys: new Set(["A", "B"]),
    });
    try {
      chart.setOption({ series: [{ ...series, force: { ...series.force, layoutAnimation: false } }] });
      expectEqualNodeDimensions(chart, [0, 1]);
      chart.resize({ width: 400, height: 900 });
      expectEqualNodeDimensions(chart, [0, 1]);
      chart.setOption({ series: [{ id: "relationships", zoom: 2 }] });
      expectEqualNodeDimensions(chart, [0, 1]);
    } finally {
      chart.dispose();
    }
  });

  function simulate(distance: number, linked: boolean, repulsion: number) {
    const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 640, height: 560 });
    const graph: CharacterRelationGraph = {
      owner: "A",

      nodes: ["A", "B"].map((key) => ({ key })),
      edges: linked ? [{ source: "A", target: "B", temperature: 0, content: "" }] : [],
    };
    const positions = { A: { x: -distance / 2, y: 0 }, B: { x: distance / 2, y: 0 } };
    const series = graphSeries({
      graph: graph,
      positions: positions,
      activeNodeKey: "",
      emptyRelationLabel: "",
      textColor: "#fff",
      backgroundColor: "#000",
      fixedKeys: new Set(),
      edgeLengths: { '["A","B"]': 180 },
    });
    try {
      chart.setOption({
        series: [{ ...series, force: { ...series.force, repulsion, gravity: 0, layoutAnimation: false } }],
      });
      const result = readGraphPositions(chart);
      expect(Object.values(result).every((p) => Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true);
      return Math.hypot(result.A.x - result.B.x, result.A.y - result.B.y);
    } finally {
      chart.dispose();
    }
  }

  it("repels nearby nodes more strongly with greater repulsion", () => {
    const weak = simulate(20, false, 100);
    const strong = simulate(20, false, 1200);
    expect(weak).toBeGreaterThan(20);
    expect(strong).toBeGreaterThan(weak);
  });

  it("does not attract isolated nodes when repulsion is disabled", () => {
    expect(simulate(800, false, 0)).toBe(800);
  });

  it("repels isolated nodes without requiring any edges", () => {
    expect(simulate(800, false, 1200)).toBeGreaterThan(800);
  });

  it("attracts distant linked nodes toward the spring length", () => {
    expect(simulate(800, true, 1200)).toBeLessThan(800);
  });

  it("restores saved positions exactly while nodes are fixed for dragging", () => {
    const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 640, height: 560 });
    const graph: CharacterRelationGraph = {
      owner: "A",

      nodes: [{ key: "A" }],
      edges: [],
    };
    try {
      chart.setOption({
        series: [
          graphSeries({
            graph: graph,
            positions: { A: { x: 0, y: 0 } },
            activeNodeKey: "",
            emptyRelationLabel: "",
            textColor: "#fff",
            backgroundColor: "#000",
            fixedKeys: new Set(["A"]),
          }),
        ],
      });
      seedGraphPositions(chart, { A: { x: 123, y: -45 } });
      chart.setOption({ series: [{ id: "relationships", force: { layoutAnimation: false } }] });
      expect(readGraphPositions(chart)).toEqual({ A: { x: 123, y: -45 } });
    } finally {
      chart.dispose();
    }
  });

  it("keeps the dragged node fixed while its linked neighbour moves", () => {
    const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 640, height: 560 });
    const graph: CharacterRelationGraph = {
      owner: "A",

      nodes: [{ key: "A" }, { key: "B" }],
      edges: [{ source: "A", target: "B", temperature: 0, content: "" }],
    };
    const positions = { A: { x: 0, y: 0 }, B: { x: 800, y: 0 } };
    const series = graphSeries({
      graph: graph,
      positions: positions,
      activeNodeKey: "",
      emptyRelationLabel: "",
      textColor: "#fff",
      backgroundColor: "#000",
      fixedKeys: new Set(["A"]),
      edgeLengths: {
        '["A","B"]': 180,
      },
    });
    try {
      chart.setOption({ series: [{ ...series, force: { ...series.force, gravity: 0, layoutAnimation: false } }] });
      const held = readGraphPositions(chart);
      expect(held.A).toEqual(positions.A);
      expect(held.B.x).toBeLessThan(positions.B.x);
    } finally {
      chart.dispose();
    }
  });

  it("returns a released node to the force simulation", () => {
    const chart = init(null, undefined, { renderer: "svg", ssr: true, width: 640, height: 560 });
    const graph: CharacterRelationGraph = {
      owner: "A",

      nodes: [{ key: "A" }, { key: "B" }],
      edges: [{ source: "A", target: "B", temperature: 0, content: "" }],
    };
    const positions = { A: { x: -800, y: 0 }, B: { x: 0, y: 0 } };
    try {
      const held = graphSeries({
        graph: graph,
        positions: positions,
        activeNodeKey: "",
        emptyRelationLabel: "",
        textColor: "#fff",
        backgroundColor: "#000",
        fixedKeys: new Set(["A", "B"]),
      });
      chart.setOption({ series: [held] });
      seedGraphPositions(chart, positions);
      const released = graphSeries({
        graph: graph,
        positions: positions,
        activeNodeKey: "",
        emptyRelationLabel: "",
        textColor: "#fff",
        backgroundColor: "#000",
        fixedKeys: new Set(),
        edgeLengths: {
          '["A","B"]': 180,
        },
      });
      chart.setOption({ series: [{ ...released, force: { ...released.force, gravity: 0, layoutAnimation: false } }] });
      expect(readGraphPositions(chart).A.x).toBeGreaterThan(-800);
    } finally {
      chart.dispose();
    }
  });
});
