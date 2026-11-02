import type { StoryGraph } from "../../../shared/platform/storyPreviewTypes";

export const NODE_WIDTH = 190;
export const NODE_HEIGHT = 90;

/** Breadth-first columns keep branches readable; visited nodes bound cycles. */
export function layoutStoryGraph(graph: StoryGraph) {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const ranks = new Map<string, number>();
  const queue = nodes.has(graph.startNodeId) ? [graph.startNodeId] : [];
  if (queue.length) ranks.set(graph.startNodeId, 0);
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index];
    const node = nodes.get(id)!;
    for (const target of [...(node.transitions ?? []).map((item) => item.to), node.defaultTo]) {
      if (!target || !nodes.has(target) || ranks.has(target)) continue;
      ranks.set(target, ranks.get(id)! + 1);
      queue.push(target);
    }
  }
  const orphanRank = Math.max(0, ...ranks.values()) + 1;
  const rows = new Map<number, number>();
  const positioned = graph.nodes.map((node) => {
    const column = ranks.get(node.id) ?? orphanRank;
    const row = rows.get(column) ?? 0;
    rows.set(column, row + 1);
    return { ...node, x: column * 250 + 30, y: row * 140 + 45 };
  });
  return {
    nodes: positioned,
    width: Math.max(500, ...positioned.map((node) => node.x + NODE_WIDTH + 50)),
    height: Math.max(220, ...positioned.map((node) => node.y + NODE_HEIGHT + 60)),
  };
}
