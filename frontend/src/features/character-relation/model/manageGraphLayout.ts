import type { EChartsType } from "echarts/core";

import type { Point, Positions } from "./graphLayout";
import { applyLongEdgeAttraction, clampGraphPixel } from "./graphLayout";

interface LayoutNode {
  id: string;
  getLayout(): number[];
}

interface ForceNode {
  /** Current position in the ECharts force simulation. */
  p: number[];
  /** Previous position used to calculate movement in the force simulation. */
  pp: number[];
  fixed: boolean;
}

interface GraphSeriesModel {
  forceLayout?: {
    step(callback?: (stopped: boolean) => void): void;
    beforeStep(callback: (nodes: ForceNode[]) => void): void;
    warmUp(): void;
  };
  getGraph(): {
    eachEdge(
      callback: (edge: { node1: LayoutNode; node2: LayoutNode; setLayout(points: number[][]): void }) => void,
    ): void;
  };
  preservedPoints?: Record<string, number[]>;
  getData(): {
    each(callback: (index: number) => void): void;
    getId(index: number): string;
    getItemModel(index: number): { get(key: "fixed"): boolean | undefined };
    getItemLayout(index: number): number[] | undefined;
  };
}

interface GraphSeriesView {
  _layouting: boolean;
  updateLayout(model: GraphSeriesModel): void;
  _startForceLayoutIteration(
    force: NonNullable<GraphSeriesModel["forceLayout"]>,
    api: unknown,
    animation: boolean,
  ): void;
}

interface GraphChartRuntime {
  _api: unknown;
  getModel(): { getSeriesByIndex(index: number): GraphSeriesModel | undefined };
  getViewOfSeriesModel(model: GraphSeriesModel): GraphSeriesView;
}

const boundedForces = new WeakSet<object>();

function attractLongEdges(chart: EChartsType, cooling: number, forceNodes?: ForceNode[]): void {
  const model = graphModel(chart);
  if (!model) return;
  const positions = readGraphPositions(chart);
  const fixed = new Set<string>();
  const data = model.getData();
  data.each((index) => {
    if (data.getItemModel(index).get("fixed")) fixed.add(data.getId(index));
  });
  const edges: { source: string; target: string }[] = [];
  model.getGraph().eachEdge((edge) => edges.push({ source: edge.node1.id, target: edge.node2.id }));
  applyLongEdgeAttraction(positions, edges, fixed, cooling);
  data.each((index) => {
    const point = data.getItemLayout(index);
    const next = positions[data.getId(index)];
    if (point && next) {
      const node = forceNodes?.[index];
      if (node) {
        node.pp[0] += next.x - point[0];
        node.pp[1] += next.y - point[1];
      }
      point[0] = next.x;
      point[1] = next.y;
    }
  });
}

export function constrainGraph(chart: EChartsType, forceNodes?: ForceNode[]): void {
  const model = graphModel(chart);
  if (!model) return;
  const data = model.getData();
  data.each((index) => {
    const point = data.getItemLayout(index);
    if (!point || !point.every(Number.isFinite)) return;
    const pixel = chart.convertToPixel({ seriesIndex: 0 }, point);
    const bounded = clampGraphPixel(pixel, chart.getWidth(), chart.getHeight());
    if (Math.abs(pixel[0] - bounded[0]) < 0.01 && Math.abs(pixel[1] - bounded[1]) < 0.01) return;
    const next = chart.convertFromPixel({ seriesIndex: 0 }, bounded);
    // Mutate the simulation's position array as well as the rendered layout.
    point[0] = next[0];
    point[1] = next[1];
    // Cancel movement into the wall in the simulation's history too. Otherwise
    // the next step treats the boundary correction as movement back inward.
    const node = forceNodes?.[index];
    if (node) {
      for (let axis = 0; axis < 2; axis++) {
        node.p[axis] = next[axis];
        if (Math.abs(pixel[axis] - bounded[axis]) >= 0.01) node.pp[axis] = next[axis];
      }
    }
  });
  model.getGraph().eachEdge((edge) => edge.setLayout([[...edge.node1.getLayout()], [...edge.node2.getLayout()]]));
}

export function installGraphBounds(chart: EChartsType): void {
  const force = graphModel(chart)?.forceLayout;
  if (!force || boundedForces.has(force)) return;
  boundedForces.add(force);
  const step = force.step.bind(force);
  let forceNodes: ForceNode[] | undefined;
  force.beforeStep((nodes) => {
    const firstStep = !forceNodes;
    forceNodes = nodes;
    // Preserve ECharts' original beforeStep behaviour for fixed nodes.
    const data = graphModel(chart)?.getData();
    nodes.forEach((node, index) => {
      const point = data?.getItemLayout(index);
      if (node.fixed && point) {
        node.p[0] = point[0];
        node.p[1] = point[1];
      }
      if (firstStep) {
        // Installation can clamp positions before the first wrapped step.
        node.pp[0] = node.p[0];
        node.pp[1] = node.p[1];
      }
    });
  });
  // Match ECharts' cooling rate, retaining its own termination condition.
  let cooling = 1;
  force.step = (callback) => {
    attractLongEdges(chart, cooling, forceNodes);
    cooling *= 0.992;
    step((stopped) => {
      constrainGraph(chart, forceNodes);
      callback?.(stopped);
    });
  };
  constrainGraph(chart);
}

// Update the existing graph model and view, without rebuilding the force layout.
// These view internals match the installed ECharts version and stay in this adapter.
export function moveGraphNode(chart: EChartsType, key: string, position: Point): void {
  const model = graphModel(chart);
  if (!model?.forceLayout) return;
  const data = model.getData();
  data.each((index) => {
    if (data.getId(index) !== key) return;
    const point = data.getItemLayout(index);
    if (point) {
      point[0] = position.x;
      point[1] = position.y;
    }
  });
  const runtime = chart as unknown as GraphChartRuntime;
  constrainGraph(chart);
  const view = runtime.getViewOfSeriesModel(model);
  view.updateLayout(model);
  model.forceLayout.warmUp();
  if (!view._layouting) view._startForceLayoutIteration(model.forceLayout, runtime._api, true);
}

// ECharts keeps force-simulated positions in its model, not in getOption().
// Keep this version-dependent access here so persistence and dragging share it.
function graphModel(chart: EChartsType): GraphSeriesModel | undefined {
  const runtime = chart as unknown as GraphChartRuntime;
  return runtime.getModel().getSeriesByIndex(0);
}

export function readGraphPositions(chart: EChartsType): Positions {
  const data = graphModel(chart)?.getData();
  const positions: Positions = {};
  data?.each((index: number) => {
    const point = data.getItemLayout(index);
    if (point && Number.isFinite(point[0]) && Number.isFinite(point[1])) {
      positions[data.getId(index)] = { x: point[0], y: point[1] };
    }
  });
  return positions;
}

export function seedGraphPositions(chart: EChartsType, positions: Positions): void {
  const model = graphModel(chart);
  if (model)
    model.preservedPoints = Object.fromEntries(
      Object.entries(positions).map(([key, point]) => [key, [point.x, point.y]]),
    );
}
