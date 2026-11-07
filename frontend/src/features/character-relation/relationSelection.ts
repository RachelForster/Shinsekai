import type { CharacterRelationGraph } from "../../shared/platform/types";

export const normalizeRelationName = (name: string): string => name.trim().toLowerCase();

export function relationOwnerKey(graph: CharacterRelationGraph): string {
  return (
    graph.nodes.find((node) => node.key === graph.owner)?.key ??
    graph.nodes.find((node) => normalizeRelationName(node.key) === normalizeRelationName(graph.owner))?.key ??
    graph.owner
  );
}
