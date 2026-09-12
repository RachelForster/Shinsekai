import type { StoryGenerationStage } from "./types";

export interface StoryGraphNode {
  id: string;
  title: string;
  type: "limited_turn_node" | "free_chat_node" | "ending_node";
  instruction?: string;
  background?: string;
  maxRounds?: number;
  defaultTo?: string;
  transitions?: Array<{ to: string; when: string }>;
}

export interface StoryGraph {
  startNodeId: string;
  nodes: StoryGraphNode[];
}

export interface StoryGenerationPreview {
  artifacts: Partial<Record<StoryGenerationStage, Record<string, unknown>>>;
  graph: StoryGraph | null;
  title: string;
}
