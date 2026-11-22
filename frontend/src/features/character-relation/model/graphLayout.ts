import type { CharacterRelationGraph } from "../../../shared/platform/types";

export type Point = { x: number; y: number };
export type Positions = Record<string, Point>;
export type EdgeLengths = Record<string, number>;

export interface GraphPixelBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

const MIN_EDGE_LENGTH = 40;
const HORIZONTAL_NODE_MARGIN = 60;
const TOP_NODE_MARGIN = 38;
const BOTTOM_NODE_MARGIN = 64;
export const longEdgeAttraction = { threshold: 120, strength: 0.08, maxStep: 12 };

// Accumulate from a snapshot so edge ordering does not affect the result.
export function applyLongEdgeAttraction(
  positions: Positions,
  edges: ReadonlyArray<{ source: string; target: string }>,
  fixed: ReadonlySet<string>,
  cooling = 1,
): void {
  const offsets: Positions = {};
  const seen = new Set<string>();
  for (const { source, target } of edges) {
    const key = JSON.stringify([source, target].sort());
    if (seen.has(key)) continue;
    seen.add(key);
    const sourcePosition = positions[source];
    const targetPosition = positions[target];
    if (!sourcePosition || !targetPosition) continue;
    const dx = targetPosition.x - sourcePosition.x;
    const dy = targetPosition.y - sourcePosition.y;
    const distance = Math.hypot(dx, dy);
    if (!Number.isFinite(distance) || distance <= longEdgeAttraction.threshold) continue;
    const amount = ((distance - longEdgeAttraction.threshold) * longEdgeAttraction.strength) / 2;
    for (const [id, direction] of [
      [source, 1],
      [target, -1],
    ] as const) {
      if (fixed.has(id)) continue;
      const offset = offsets[id] ?? (offsets[id] = { x: 0, y: 0 });
      offset.x += ((direction * dx) / distance) * amount;
      offset.y += ((direction * dy) / distance) * amount;
    }
  }
  for (const [id, offset] of Object.entries(offsets)) {
    const scale = Math.min(1, longEdgeAttraction.maxStep / Math.hypot(offset.x, offset.y)) * cooling;
    positions[id].x += offset.x * scale;
    positions[id].y += offset.y * scale;
  }
}

export const relationEdgeId = (source: string, target: string): string => JSON.stringify([source, target]);

export function measureEdgeLengths(graph: CharacterRelationGraph, positions: Positions): EdgeLengths {
  return Object.fromEntries(
    graph.edges.map((edge) => {
      const source = positions[edge.source];
      const target = positions[edge.target];
      return [
        relationEdgeId(edge.source, edge.target),
        Math.max(MIN_EDGE_LENGTH, Math.hypot(target.x - source.x, target.y - source.y)),
      ];
    }),
  );
}

// Leave room for the node circle, outline and its name below it.
export function graphPixelBounds(width: number, height: number): GraphPixelBounds {
  return {
    left: Math.min(HORIZONTAL_NODE_MARGIN, width / 2),
    right: Math.max(width / 2, width - HORIZONTAL_NODE_MARGIN),
    top: Math.min(TOP_NODE_MARGIN, height / 2),
    bottom: Math.max(height / 2, height - BOTTOM_NODE_MARGIN),
  };
}

export function clampGraphPixel(point: number[], width: number, height: number): number[] {
  const bounds = graphPixelBounds(width, height);
  return [
    Math.max(bounds.left, Math.min(bounds.right, point[0])),
    Math.max(bounds.top, Math.min(bounds.bottom, point[1])),
  ];
}
export function initialPositions(graph: CharacterRelationGraph): Positions {
  const others = graph.nodes.filter((node) => node.key !== graph.owner);
  const radius = Math.max(200, others.length * 22);
  return Object.fromEntries(
    graph.nodes.map((node) => {
      if (node.key === graph.owner) return [node.key, { x: 0, y: 0 }];
      const angle = (2 * Math.PI * others.indexOf(node)) / Math.max(1, others.length) - Math.PI / 2;
      return [node.key, { x: radius * Math.cos(angle), y: radius * Math.sin(angle) }];
    }),
  );
}

export interface GraphLayoutModel {
  positions: Positions;
  defaults: Positions;
  edgeLengths: EdgeLengths;
}

export function createGraphLayout(graph: CharacterRelationGraph, saved: Positions = {}): GraphLayoutModel {
  const model = { positions: saved, defaults: {}, edgeLengths: {} };
  reconcileGraphLayout(model, graph);
  return model;
}

export function reconcileGraphLayout(model: GraphLayoutModel, graph: CharacterRelationGraph): void {
  model.defaults = initialPositions(graph);
  model.positions = Object.fromEntries(
    graph.nodes.map(({ key }) => [
      key,
      Object.prototype.hasOwnProperty.call(model.positions, key) ? model.positions[key] : { ...model.defaults[key] },
    ]),
  );
  model.edgeLengths = Object.fromEntries(
    Object.entries(measureEdgeLengths(graph, model.positions)).map(([key, length]) => [
      key,
      model.edgeLengths[key] ?? length,
    ]),
  );
}

export function syncGraphLayout(model: GraphLayoutModel, positions: Positions, heldKey?: string): void {
  for (const [key, point] of Object.entries(positions)) {
    if (key !== heldKey && Object.prototype.hasOwnProperty.call(model.positions, key)) model.positions[key] = point;
  }
}

export function resetGraphLayout(model: GraphLayoutModel, graph: CharacterRelationGraph): void {
  Object.assign(model, createGraphLayout(graph));
}
