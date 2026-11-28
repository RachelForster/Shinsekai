export interface RelationNode {
  key: string;
}

export interface RelationEdge {
  source: string;
  target: string;
  temperature: number;
  content: string;
}

export interface RelationGraph {
  nodes: RelationNode[];
  edges: RelationEdge[];
}

export interface CharacterRelationGraph extends RelationGraph {
  owner: string;
}

export type RelationRequest =
  | { op: "add_node"; node: RelationNode }
  | { op: "delete_node"; key: string }
  | { op: "upsert_edge"; edge: RelationEdge }
  | { op: "delete_edge"; source: string; target: string };
