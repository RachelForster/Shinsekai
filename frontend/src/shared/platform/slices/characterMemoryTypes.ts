import type { TaskSnapshot } from "./taskTypes";

export type CharacterMemoryClarity = "canon" | "clear" | "faded" | "dormant";

export interface CharacterMemory {
  id: string;
  memory: string;
  detail?: string;
  gist?: string;
  clarity?: CharacterMemoryClarity;
  retention?: number;
  kind?: string;
  pinned?: boolean;
  scope?: string;
  slotKey?: string;
  topicTags?: string[];
  entities?: string[];
  importance?: number;
  createdAt?: number;
  eventAt?: number | null;
  lastRecalledAt?: number;
  recallCount?: number;
  sourceSessionId?: string;
}

export interface CharacterMemoryRememberOptions {
  pinned?: boolean;
  gistText?: string;
  slotKey?: string;
  kind?: string;
  sessionId?: string;
}

export interface CharacterMemoryList {
  agentId: string;
  count: number;
  memories: CharacterMemory[];
}

export interface CharacterMemoryImportFilePreview {
  chunkCount: number;
  dialogueCharacters: number;
  dialogueLineCount: number;
  kind: string;
  name: string;
  sourceTokens: number;
}

export interface CharacterMemoryImportPreview {
  chunkCount: number;
  dialogueCharacters: number;
  dialogueLineCount: number;
  estimatedInputTokens: number;
  estimatedOutputTokens: number;
  estimatedTotalTokens: number;
  fileCount: number;
  files: CharacterMemoryImportFilePreview[];
  sourceTokens: number;
  warnings: string[];
}

export interface CharacterMemoryImportResult {
  chunkCount: number;
  duplicateCount: number;
  estimatedTotalTokens: number;
  extractedCount: number;
  fileCount: number;
  memories?: string[];
  savedCount: number;
}

export interface CharacterMemorySearchInput {
  limit?: number;
  name: string;
  query: string;
  sessionId?: string;
  memoryMode?: string;
}

export interface Mem0Status {
  status: "ready" | "loading" | "not_started" | "error" | "missing_dependency";
  engine?: string;
  message?: string;
  modelCached?: boolean;
  moduleName?: string;
  packageName?: string;
  task?: TaskSnapshot;
}
