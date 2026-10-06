import { getPlatform } from "../../shared/platform/platform";
import type { KnowledgeImportResult, TaskProgressOptions } from "../../shared/platform/types";

export function getKnowledgeStatus(options?: { startLoading?: boolean; retry?: boolean }) {
  const operation = getPlatform().knowledge.getKnowledgeStatus;
  if (!operation) throw new Error("Knowledge status checks are not supported by this platform.");
  return operation(options);
}

export function previewKnowledgeImport(knowledgeId: string, items: File[]) {
  const operation = getPlatform().knowledge.previewKnowledgeImport;
  if (!operation) {
    throw new Error("Knowledge knowledge import is not supported by this platform.");
  }
  return operation(knowledgeId, items);
}

export function importKnowledge(
  knowledgeId: string,
  items: File[],
  options?: TaskProgressOptions<KnowledgeImportResult>,
) {
  const operation = getPlatform().knowledge.importKnowledge;
  if (!operation) {
    throw new Error("Knowledge knowledge import is not supported by this platform.");
  }
  return operation(knowledgeId, items, options);
}

export class KnowledgeBrowseError extends Error {
  constructor(
    public status: string,
    message: string,
  ) {
    super(message);
  }
}

async function knowledgeResult<T>(result: Promise<T | import("../../shared/platform/types").Mem0Status>): Promise<T> {
  const data = await result;
  if (data && typeof data === "object" && "status" in data) {
    const state = data as import("../../shared/platform/types").Mem0Status;
    throw new KnowledgeBrowseError(state.status, state.message || state.moduleName || state.status);
  }
  if (data && typeof data === "object" && "error" in data) {
    throw new Error(String(data.error));
  }
  return data as T;
}

export function listKnowledgeInstances(input: { query: string; page: number; refresh?: boolean }) {
  const operation = getPlatform().knowledge.listKnowledgeInstances;
  if (!operation) throw new Error("Knowledge browsing is not supported by this platform.");
  return knowledgeResult(operation(input));
}

export function listKnowledgeEntries(knowledgeId: string) {
  const operation = getPlatform().knowledge.listKnowledgeEntries;
  if (!operation) throw new Error("Knowledge browsing is not supported by this platform.");
  return knowledgeResult(operation(knowledgeId));
}

export function searchKnowledgeEntries(knowledgeId: string, query: string) {
  const operation = getPlatform().knowledge.searchKnowledgeEntries;
  if (!operation) throw new Error("Knowledge browsing is not supported by this platform.");
  return knowledgeResult(operation(knowledgeId, query));
}

export function listKnowledgeBindings(characterName: string, page = 1) {
  const operation = getPlatform().knowledge.listKnowledgeBindings;
  if (!operation) throw new Error("Knowledge management is not supported by this platform.");
  return knowledgeResult(operation(characterName, page));
}

export function addKnowledgeBinding(characterName: string, knowledgeId: string) {
  const operation = getPlatform().knowledge.addKnowledgeBinding;
  if (!operation) throw new Error("Knowledge management is not supported by this platform.");
  return knowledgeResult(operation(characterName, knowledgeId));
}

export function listKnowledgeBindingNames(knowledgeId: string) {
  return knowledgeResult(getPlatform().knowledge.listKnowledgeBindingNames(knowledgeId));
}

export function batchKnowledgeBindings(knowledgeId: string, add: string[], remove: string[]) {
  return knowledgeResult(getPlatform().knowledge.batchKnowledgeBindings(knowledgeId, add, remove));
}

export function removeKnowledgeBinding(characterName: string, knowledgeId: string) {
  const operation = getPlatform().knowledge.removeKnowledgeBinding;
  if (!operation) throw new Error("Knowledge management is not supported by this platform.");
  return knowledgeResult(operation(characterName, knowledgeId));
}

export function addKnowledgeEntry(knowledgeId: string, content: string) {
  const operation = getPlatform().knowledge.addKnowledgeEntry;
  if (!operation) throw new Error("Knowledge management is not supported by this platform.");
  return knowledgeResult(operation(knowledgeId, content));
}

export function deleteKnowledgeEntry(knowledgeId: string, memoryId: string) {
  const operation = getPlatform().knowledge.deleteKnowledgeEntry;
  if (!operation) throw new Error("Knowledge management is not supported by this platform.");
  return knowledgeResult(operation(knowledgeId, memoryId));
}

export function deleteKnowledge(knowledgeId: string) {
  const operation = getPlatform().knowledge.deleteKnowledge;
  if (!operation) throw new Error("Knowledge management is not supported by this platform.");
  return knowledgeResult(operation(knowledgeId));
}
