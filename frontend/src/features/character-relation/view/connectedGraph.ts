import type { Character, CharacterRelationGraph } from "../../../shared/platform/types";
import { normalizeRelationName as keyOf } from "../model/relationUitl";

export function connectedGraph(
  root: CharacterRelationGraph,
  characters: ReadonlyArray<Pick<Character, "name" | "relation_graph">>,
) {
  const names = new Map(characters.map((c) => [keyOf(c.name), c.name]));
  names.set(keyOf(root.owner), root.owner);
  const neighbors = new Map<string, Set<string>>();
  const graphs = new Map(characters.map((c) => [keyOf(c.name), c.relation_graph]));
  graphs.set(keyOf(root.owner), root);
  for (const [owner, graph] of graphs) {
    for (const node of graph?.nodes ?? []) {
      const nodeKey = keyOf(node.key);
      if (!names.has(nodeKey)) names.set(nodeKey, node.key);
      if (!neighbors.has(owner)) neighbors.set(owner, new Set());
      if (!neighbors.has(nodeKey)) neighbors.set(nodeKey, new Set());
      neighbors.get(owner)!.add(nodeKey);
      neighbors.get(nodeKey)!.add(owner);
    }
  }
  const visited = new Set([keyOf(root.owner)]),
    queue = [...visited];
  for (const key of queue)
    for (const other of neighbors.get(key) ?? []) {
      if (!visited.has(other)) {
        visited.add(other);
        queue.push(other);
      }
    }
  const grouped = queue.flatMap((key): CharacterRelationGraph[] => {
    const graph = graphs.get(key);
    return graph
      ? [
          {
            owner: names.get(key)!,
            nodes: graph.nodes,
            edges: graph.edges.map((edge) => ({
              ...edge,
              source: names.get(keyOf(edge.source)) ?? edge.source,
              target: names.get(keyOf(edge.target)) ?? edge.target,
            })),
          },
        ]
      : [];
  });
  const edges: CharacterRelationGraph["edges"] = [];
  for (const group of grouped) {
    for (const edge of group.edges) {
      edges.push(edge);
    }
  }
  return { nodes: queue.map((key) => ({ key: names.get(key)! })), graphs: grouped, edges };
}
