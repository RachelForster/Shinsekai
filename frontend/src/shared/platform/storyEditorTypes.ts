import type { StoryGraph } from "./storyPreviewTypes";
import type { StoryGenerationValidation } from "./types";

export interface StoryDocument {
  storyPath: string;
  title: string;
  version: number;
  sourceHash: string;
  graph: StoryGraph;
  authoringBrief: string;
}

export type StoryEditInput = Pick<StoryDocument, "storyPath" | "sourceHash" | "title" | "graph">;

export interface StorySuggestionInput extends StoryEditInput {
  instructions: string;
  scope: "node" | "graph";
  nodeId?: string;
}

export interface StorySuggestion {
  graph: StoryGraph;
  summary: string;
  validation: StoryGenerationValidation;
}
