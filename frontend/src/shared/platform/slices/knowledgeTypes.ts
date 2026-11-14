import type {
  CharacterMemory,
  CharacterMemoryImportPreview,
  CharacterMemoryImportResult,
  Mem0Status,
} from "./characterTypes";
import type { TaskProgressOptions } from "./taskTypes";

export interface KnowledgeInstanceList {
  count: number;
  page: number;
  pageSize: number;
  knowledge: Array<{ knowledge_id: string; entryCount: number; characterCount: number }>;
}

export interface KnowledgeBindingList {
  characterName: string;
  count: number;
  page: number;
  pageSize: number;
  bindings: Array<{ knowledge_id: string; createdAt: string }>;
}

export interface KnowledgeBindingResult {
  ok: true;
  characterName: string;
  knowledge_id?: string;
  deleted?: boolean;
  deletedBindingCount?: number;
}

export interface KnowledgeBindingNames {
  knowledge_id: string;
  characterNames: string[];
}

export interface KnowledgeDeleteResult {
  ok: boolean;
  knowledge_id: string;
  deletedEntryCount: number;
  deletedBindingCount: number;
  error?: string;
  failedStage?: "validate" | "initialize" | "collect" | "entries" | "bindings";
}

export interface KnowledgeEntryPage {
  knowledge_id: string;
  memories: CharacterMemory[];
  count: number;
}

export interface KnowledgeEntrySearch {
  knowledge_id: string;
  query: string;
  count: number;
  memories: CharacterMemory[];
}

export type KnowledgeImportPreview = CharacterMemoryImportPreview;

export interface KnowledgeImportResult extends CharacterMemoryImportResult {
  knowledge_id: string;
}

export interface KnowledgePlatform {
  getKnowledgeStatus: (options?: { startLoading?: boolean; retry?: boolean }) => Promise<Mem0Status>;
  importKnowledge: (
    knowledgeId: string,
    items: File[],
    options?: TaskProgressOptions<KnowledgeImportResult>,
  ) => Promise<KnowledgeImportResult>;
  listKnowledgeInstances: (input: {
    query: string;
    page: number;
    refresh?: boolean;
  }) => Promise<KnowledgeInstanceList | Mem0Status>;
  listKnowledgeBindings: (characterName: string, page?: number) => Promise<KnowledgeBindingList>;
  listKnowledgeBindingNames: (knowledgeId: string) => Promise<KnowledgeBindingNames>;
  batchKnowledgeBindings: (
    knowledgeId: string,
    add: string[],
    remove: string[],
  ) => Promise<KnowledgeBindingNames & { ok: true }>;
  addKnowledgeBinding: (characterName: string, knowledgeId: string) => Promise<KnowledgeBindingResult>;
  removeKnowledgeBinding: (characterName: string, knowledgeId: string) => Promise<KnowledgeBindingResult>;
  addKnowledgeEntry: (knowledgeId: string, content: string) => Promise<KnowledgeEntryPage | Mem0Status>;
  deleteKnowledgeEntry: (knowledgeId: string, memoryId: string) => Promise<KnowledgeEntryPage | Mem0Status>;
  deleteKnowledge: (knowledgeId: string) => Promise<KnowledgeDeleteResult | Mem0Status>;
  listKnowledgeEntries: (knowledgeId: string) => Promise<KnowledgeEntryPage | Mem0Status>;
  searchKnowledgeEntries: (knowledgeId: string, query: string) => Promise<KnowledgeEntrySearch | Mem0Status>;
  previewKnowledgeImport: (knowledgeId: string, items: File[]) => Promise<KnowledgeImportPreview>;
}
