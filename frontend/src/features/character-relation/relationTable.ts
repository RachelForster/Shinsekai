import type {
  CharacterRelationGraph,
  RelationEdge,
  RelationNode,
  RelationRequest,
} from "../../shared/platform/types";

export interface RelationRow {
  edge?: RelationEdge;
  source: string;
  target: string;
  relation: string;
  temperature: string;
}

export const emptyRelationRow = (): RelationRow => ({
  source: "",
  target: "",
  relation: "",
  temperature: "0",
});

export function convertGraphToRows(graph: CharacterRelationGraph): RelationRow[] {
  return Array.from({ length: graph.edges.length + 1 }, (_, i) => {
    const edge = graph.edges[i];
    return {
      ...emptyRelationRow(),
      edge,
      source: edge?.source ?? "",
      target: edge?.target ?? "",
      relation: edge?.content ?? "",
      temperature: String(edge?.temperature ?? 0),
    };
  });
}

function isEmptyRelationshipRow(row: RelationRow): boolean {
  return !row.source.trim() && !row.target.trim() && !row.relation.trim() && row.temperature === "0";
}

function convertRowToEdge(row: RelationRow, nodeKeys: ReadonlySet<string>, seenPairs: Set<string>): RelationEdge {
  const source = row.source.trim();
  const target = row.target.trim();
  const temperature = Number(row.temperature);
  if (!nodeKeys.has(source) || !nodeKeys.has(target) || source === target) throw new Error("invalidEndpoints");
  if (!row.temperature.trim() || !Number.isInteger(temperature) || Math.abs(temperature) > 10) {
    throw new Error("invalidTemperature");
  }

  const pair = JSON.stringify([source, target]);
  if (seenPairs.has(pair)) throw new Error("duplicateEdge");
  seenPairs.add(pair);
  if (Array.from(row.relation).length > 100) throw new Error("invalidRelation");

  return { source, target, temperature, content: row.relation.trim() };
}

function relationshipHasChanged(previous: RelationEdge | undefined, next: RelationEdge): boolean {
  return (
    !previous ||
    previous.source !== next.source ||
    previous.target !== next.target ||
    previous.temperature !== next.temperature ||
    previous.content !== next.content
  );
}

export function tableOperations(rows: RelationRow[], nodes: readonly RelationNode[]): RelationRequest[] {
  const edgeRemovals: RelationRequest[] = [];
  const edgeUpdates: RelationRequest[] = [];
  const nodeKeys = new Set(nodes.map((node) => node.key));
  const seenPairs = new Set<string>();

  for (const row of rows) {
    if (isEmptyRelationshipRow(row)) {
      if (row.edge) edgeRemovals.push({ op: "delete_edge", source: row.edge.source, target: row.edge.target });
      continue;
    }

    const edge = convertRowToEdge(row, nodeKeys, seenPairs);
    if (row.edge && (row.edge.source !== edge.source || row.edge.target !== edge.target)) {
      edgeRemovals.push({ op: "delete_edge", source: row.edge.source, target: row.edge.target });
    }
    if (relationshipHasChanged(row.edge, edge)) edgeUpdates.push({ op: "upsert_edge", edge });
  }

  const operations = [...edgeRemovals, ...edgeUpdates];
  if (operations.length > 1000) throw new Error("tooManyChanges");
  return operations;
}
