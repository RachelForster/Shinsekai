export type StoryGenerationStage = "foundation" | "characters" | "narrative";

export interface StoryGenerationValidationIssue {
  code: string;
  message: string;
  path: string;
  severity: "error" | "info" | "warning";
}

export interface StoryGenerationValidation {
  castFailureNodeIds: string[];
  endingCoverage: number;
  endingNodeIds: string[];
  exploredStates: number;
  issues: StoryGenerationValidationIssue[];
  reachableEndingIds: string[];
  reachableNodeIds: string[];
  sourceHash: string;
  valid: boolean;
}

export interface StoryGenerationTask {
  artifactHashes: Partial<Record<StoryGenerationStage, string>>;
  assumptions: string[];
  cancelRequested: boolean;
  completedStages: StoryGenerationStage[];
  cost: {
    estimatedTokens: number;
    inputChars: number;
    outputChars: number;
    requests: number;
  };
  createdAt: number;
  currentStage: StoryGenerationStage | "complete" | "repair";
  draftPath: string;
  error: { code: string; message: string } | null;
  id: string;
  options: Record<string, unknown>;
  repairAttempts: number;
  recovery?: {
    state: "resuming" | "working" | "correcting" | "waiting";
    attempt?: number;
    message: string;
    nextRetryAt?: number | null;
    lastError?: { code: string; message: string };
  } | null;
  resourceCatalog: Record<string, unknown>;
  status: "cancelled" | "failed" | "queued" | "running" | "succeeded";
  synopsis: string;
  updatedAt: number;
  validation: StoryGenerationValidation | null;
}

export interface StoryGenerationInput {
  options?: Record<string, unknown>;
  resourceCatalog?: Record<string, unknown>;
  synopsis: string;
}

export interface StoryLibraryEntry {
  canEditGraph?: boolean;
  version?: number;
  id: string;
  title: string;
  storyPath: string;
  characters: string[];
  backgrounds: string[];
  historyPath: string;
  currentNodeTitle: string;
  updatedAt: number;
}
