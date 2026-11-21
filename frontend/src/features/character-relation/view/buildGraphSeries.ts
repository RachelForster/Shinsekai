import type { GraphSeriesOption } from "echarts/charts";

import type { CharacterRelationGraph } from "../../../shared/platform/types";
import { composeGraphNode } from "./composingGraphNode";
import type { Positions } from "../model/graphLayout";
import { measureEdgeLengths, relationEdgeId, type EdgeLengths } from "../model/graphLayout";
import type { GraphTheme } from "../model/graphTheme";
import { normalizeRelationName } from "../model/relationUitl";

export interface GraphSeriesOptions {
  graph: CharacterRelationGraph;
  positions: Positions;
  labelPositions: Positions;
  activeNodeKey: string;
  emptyRelationLabel: string;
  textColor: string;
  backgroundColor: string;
  fixedKeys?: ReadonlySet<string>;
  theme?: Pick<GraphTheme, "accent" | "selected" | "muted">;
  edgeLengths?: EdgeLengths;
  characters?: ReadonlyArray<{ name: string; color: string }>;
  avatars?: ReadonlyMap<string, HTMLCanvasElement>;
  selectedNodeKey?: string;
}

export function graphSeries(
  {
    graph,
    positions,
    labelPositions,
    activeNodeKey,
    emptyRelationLabel,
    textColor,
    backgroundColor,
    fixedKeys = new Set(),
    theme = { accent: textColor, selected: backgroundColor, muted: textColor },
    edgeLengths = measureEdgeLengths(graph, positions),
    characters = [],
    avatars = new Map(),
    selectedNodeKey = activeNodeKey,
  }: GraphSeriesOptions,
  graphs: readonly CharacterRelationGraph[],
): GraphSeriesOption {
  const characterColors = new Map(
    characters.map((character) => [normalizeRelationName(character.name), character.color]),
  );
  const renderEdges = graphs.flatMap((group) => group.edges.map((edge) => ({ owner: group.owner, edge })));
  const lengths = renderEdges.map(({ edge }) => edgeLengths[relationEdgeId(edge.source, edge.target)] ?? 40);
  return {
    id: "relationships",
    type: "graph",
    coordinateSystem: "view",
    // Keep equal X/Y scales so circular symbols are not stretched by the viewport.
    preserveAspect: true,
    layout: "force",
    roam: "scale",
    left: 80,
    right: 80,
    top: 80,
    bottom: 80,
    force: {
      repulsion: 400,
      edgeLength: lengths.length ? [Math.min(...lengths), Math.max(...lengths)] : 40,
      // Attraction comes from edges only, never from the layout center.
      gravity: 0.01,
      friction: 0.6,
      layoutAnimation: true,
    },
    animation: false,
    symbol: "circle",
    symbolSize: 64,
    draggable: false,
    emphasis: { focus: "none", scale: false },
    label: { show: true, position: "bottom", color: textColor, width: 110, overflow: "truncate" },
    data: graph.nodes.map((node) =>
      composeGraphNode({
        node,
        position: positions[node.key],
        owner: graph.owner,
        activeNodeKey,
        selectedNodeKey,
        fixed: fixedKeys.has(node.key),
        backgroundColor,
        theme,
        characterColors,
        avatars,
      }),
    ),
    links: renderEdges.map(({ edge, owner }) => {
      const visible = normalizeRelationName(owner) === normalizeRelationName(activeNodeKey);
      const relationText = edge.content.trim() || emptyRelationLabel;
      const source = labelPositions[edge.source];
      const target = labelPositions[edge.target];
      return {
        id: JSON.stringify([owner, edge.source, edge.target]),
        source: edge.source,
        target: edge.target,
        // ECharts maps larger edge values to shorter springs.
        value: -(edgeLengths[relationEdgeId(edge.source, edge.target)] ?? 40),
        symbol: [
          "path://M5,0 Q6,0 6,1 Q6,1.5 5.5,2 L1.5,9.5 Q1,10.5 0,10 Q-1,9.5 -0.5,8.5 L4,0.5 Q4.3,0 5,0 Z",
          "path://M5,0 Q6,0 6,1 Q6,1.5 5.5,2 L1.5,9.5 Q1,10.5 0,10 Q-1,9.5 -0.5,8.5 L4,0.5 Q4.3,0 5,0 Z",
        ],
        symbolSize: 15,
        lineStyle: {
          color: visible ? theme.accent : theme.muted,
          opacity: visible ? 1 : activeNodeKey ? 0.1 : 0.45,
          width: visible ? 2 : 1.5,
          curveness: 0,
        },
        label: {
          show: visible,
          formatter: () => (relationText.length > 64 ? relationText.slice(0, 64) + "…" : relationText),
          color: textColor,
          backgroundColor: "transparent",
          position: (source?.x ?? 0) <= (target?.x ?? 0) ? "insideMiddleTop" : "insideMiddleBottom",
          distance: 8,
        },
      };
    }),
  };
}
