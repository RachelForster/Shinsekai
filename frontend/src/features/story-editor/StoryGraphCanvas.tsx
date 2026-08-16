import { useMemo } from "react";

import type { StoryGraphProjection } from "../../entities/story/types";
import { useI18n } from "../../shared/i18n";
import "./StoryGraphCanvas.css";

const GRAPH_NODE_WIDTH = 168;
const GRAPH_NODE_HEIGHT = 56;
const GRAPH_RULE_GAP = 72;

type GraphKind = "narrative" | "rules";

type CanvasNode = {
  id: string;
  kind: GraphKind;
  title: string;
  type: string;
  x: number;
  y: number;
};

type CanvasEdge = {
  d: string;
  id: string;
  kind: GraphKind;
  label: string;
  midX: number;
  midY: number;
};

function graphEdgePath(from: CanvasNode, to: CanvasNode) {
  const startX = from.x + GRAPH_NODE_WIDTH;
  const startY = from.y + GRAPH_NODE_HEIGHT / 2;
  const endX = to.x;
  const endY = to.y + GRAPH_NODE_HEIGHT / 2;
  const dx = Math.max(48, Math.abs(endX - startX) / 2);
  if (endX >= startX) {
    return {
      d: `M ${startX} ${startY} C ${startX + dx} ${startY}, ${endX - dx} ${endY}, ${endX} ${endY}`,
      midX: (startX + endX) / 2,
      midY: (startY + endY) / 2 - 8,
    };
  }
  const lift = Math.min(startY, endY) - 36;
  return {
    d: `M ${startX} ${startY} C ${startX + 48} ${lift}, ${endX - 48} ${lift}, ${endX} ${endY}`,
    midX: (startX + endX) / 2,
    midY: lift,
  };
}

function layoutGraphCanvas(graph: StoryGraphProjection) {
  const narrativeMaxY = Math.max(0, ...graph.narrative.nodes.map((node) => node.y + GRAPH_NODE_HEIGHT));
  const rulesOffsetY = graph.narrative.nodes.length ? narrativeMaxY + GRAPH_RULE_GAP : 0;
  const nodes: CanvasNode[] = [
    ...graph.narrative.nodes.map((node) => ({ ...node, kind: "narrative" as const })),
    ...graph.rules.nodes.map((node) => ({
      ...node,
      kind: "rules" as const,
      y: node.y + rulesOffsetY,
    })),
  ];
  const byKey = new Map(nodes.map((node) => [`${node.kind}:${node.id}`, node]));
  const edges: CanvasEdge[] = [];
  const labels: string[] = [];
  for (const edge of graph.narrative.edges) {
    const from = byKey.get(`narrative:${edge.from}`);
    const to = byKey.get(`narrative:${edge.to}`);
    const label = `${edge.from} → ${edge.to} · ${edge.label}`;
    labels.push(label);
    if (!from || !to) continue;
    const path = graphEdgePath(from, to);
    edges.push({ id: edge.id, kind: "narrative", label: edge.label, ...path });
  }
  for (const edge of graph.rules.edges) {
    const from = byKey.get(`rules:${edge.from}`);
    const to = byKey.get(`rules:${edge.to}`);
    const label = `${edge.from}.${edge.fromPort} → ${edge.to}.${edge.toPort}`;
    labels.push(label);
    if (!from || !to) continue;
    const path = graphEdgePath(from, to);
    edges.push({ id: edge.id, kind: "rules", label, ...path });
  }
  const width = Math.max(600, ...nodes.map((node) => node.x + GRAPH_NODE_WIDTH + 52));
  const height = Math.max(260, ...nodes.map((node) => node.y + GRAPH_NODE_HEIGHT + 44));
  return { edges, labels, height, nodes, width };
}

export function StoryGraphCanvas({ graph }: { graph: StoryGraphProjection }) {
  const { t } = useI18n();
  const { edges, height, labels, nodes, width } = useMemo(() => layoutGraphCanvas(graph), [graph]);
  return (
    <div className="story-editor-graph-scroll">
      <div className="story-editor-graph" style={{ height, width }}>
        <svg aria-hidden="true" className="story-editor-graph-lines" height={height} width={width}>
          <defs>
            <marker id="story-graph-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="7" refY="4">
              <path d="M0,0 L8,4 L0,8 Z" fill="currentColor" />
            </marker>
          </defs>
          {edges.map((edge) => (
            <g key={`${edge.kind}-${edge.id}`}>
              <path d={edge.d} markerEnd="url(#story-graph-arrow)" />
              {edge.label ? (
                <text x={edge.midX} y={edge.midY}>
                  {edge.label}
                </text>
              ) : null}
            </g>
          ))}
        </svg>
        {nodes.map((node) => (
          <div
            className={`story-editor-graph-node story-editor-graph-node-${node.kind}`}
            key={`${node.kind}-${node.id}`}
            style={{ left: node.x, top: node.y }}
          >
            <strong>{node.title}</strong>
            <small>{node.type}</small>
          </div>
        ))}
        {labels.length ? (
          <ul aria-label={t("story.editor.graphEdges")} className="story-editor-graph-edges">
            {labels.map((edge) => (
              <li key={edge}>{edge}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
