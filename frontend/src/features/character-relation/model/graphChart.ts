import { GraphChart } from "echarts/charts";
import { init, use, type EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import type { GraphSeriesOption } from "echarts/charts";
import type { Positions } from "./graphLayout";
import { installGraphBounds, seedGraphPositions } from "./manageGraphLayout";
use([GraphChart, CanvasRenderer]);
export type GraphChartModel = EChartsType;
export interface GraphViewport {
  zoom?: number;
  center?: number[];
  nodeScaleRatio?: number;
}
export function createGraphChart(container: HTMLElement): GraphChartModel {
  const chart = init(container, undefined, {
    renderer: "canvas",
    width: container.clientWidth || 640,
    height: container.clientHeight || 560,
  });
  chart.setOption({ series: [{ id: "relationships", type: "graph", data: [], links: [] }] });
  return chart;
}
export function renderGraphChart(
  chart: GraphChartModel,
  series: GraphSeriesOption,
  positions: Positions,
  simulating: boolean,
): void {
  seedGraphPositions(chart, positions);
  const viewport = (chart.getOption().series as GraphViewport[])[0];
  chart.setOption({
    series: [
      {
        ...series,
        zoom: viewport?.zoom ?? 1,
        ...(viewport?.center ? { center: viewport.center } : {}),
        // Keep the same coordinate bounds when releasing a drag. Fixed nodes and
        // zero friction stop idle layouts immediately without changing their positions.
        ...(!simulating ? { force: { ...series.force, friction: 0, layoutAnimation: false } } : {}),
      },
    ],
  });
  if (simulating) installGraphBounds(chart);
}
export function fitGraphChart(chart: GraphChartModel, positions: Positions, simulating: boolean): void {
  const points = Object.values(positions);
  if (!points.length) return;
  const pixels = points.map((point) => chart.convertToPixel({ seriesIndex: 0 }, [point.x, point.y]));
  const xs = pixels.map((point) => point[0]);
  const ys = pixels.map((point) => point[1]);
  const spanX = Math.max(...xs) - Math.min(...xs);
  const spanY = Math.max(...ys) - Math.min(...ys);
  const series = (chart.getOption().series as GraphViewport[])[0];
  const zoom =
    (series.zoom ?? 1) *
    Math.min(
      Math.max(1, chart.getWidth() - 160) / Math.max(160, spanX),
      Math.max(1, chart.getHeight() - 160) / Math.max(160, spanY),
    );
  const center = chart.convertFromPixel({ seriesIndex: 0 }, [
    (Math.min(...xs) + Math.max(...xs)) / 2,
    (Math.min(...ys) + Math.max(...ys)) / 2,
  ]);
  chart.setOption({ series: [{ id: "relationships", center, zoom: Math.min(4, zoom) }] });
  if (simulating) installGraphBounds(chart);
}

import type { GraphDragModel } from "./graphDrag";
import { clampGraphPixel } from "./graphLayout";
export function hitGraphNode(chart: GraphChartModel, nodes: { key: string }[], positions: Positions, pixel: number[]) {
  const series = (chart.getOption().series as GraphViewport[])[0];
  const radius = 32 * (((series.zoom ?? 1) - 1) * (series.nodeScaleRatio ?? 0.6) + 1);
  return [...nodes].reverse().find((node) => {
    const position = positions[node.key];
    if (!position) return false;
    const nodePixel = chart.convertToPixel({ seriesIndex: 0 }, [position.x, position.y]);
    return nodePixel && Math.hypot(nodePixel[0] - pixel[0], nodePixel[1] - pixel[1]) <= radius;
  });
}
export function graphDragPosition(chart: GraphChartModel, drag: GraphDragModel, pixel: number[]) {
  const startPixel = chart.convertToPixel({ seriesIndex: 0 }, [drag.start.x, drag.start.y]);
  const point = chart.convertFromPixel(
    { seriesIndex: 0 },
    clampGraphPixel(
      [startPixel[0] + pixel[0] - drag.pixel[0], startPixel[1] + pixel[1] - drag.pixel[1]],
      chart.getWidth(),
      chart.getHeight(),
    ),
  );
  return { x: point[0], y: point[1] };
}
