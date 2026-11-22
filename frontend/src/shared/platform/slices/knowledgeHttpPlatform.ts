import type { HttpTransport } from "../httpTransport";
import type { Mem0Status } from "./characterTypes";
import type {
  KnowledgeBindingList,
  KnowledgeBindingNames,
  KnowledgeBindingResult,
  KnowledgeDeleteResult,
  KnowledgeEntryPage,
  KnowledgeEntrySearch,
  KnowledgeImportPreview,
  KnowledgeImportResult,
  KnowledgeInstanceList,
  KnowledgePlatform,
} from "./knowledgeTypes";
import type { TaskSnapshot } from "./taskTypes";

export function createKnowledgeHttpPlatform(transport: HttpTransport): KnowledgePlatform {
  const { requestJson, uploadFiles, waitForTask } = transport;

  return {
    getKnowledgeStatus: (options) =>
      requestJson<Mem0Status>("/api/knowledge/status", {
        body: JSON.stringify({ startLoading: options?.startLoading ?? false, retry: options?.retry ?? false }),
        method: "POST",
      }),
    importKnowledge: async (knowledgeId, items, options) => {
      const task = await uploadFiles<TaskSnapshot<KnowledgeImportResult>>(
        `/api/knowledge/import-upload?knowledge_id=${encodeURIComponent(knowledgeId)}`,
        items,
      );
      return waitForTask(task, options);
    },
    listKnowledgeInstances: ({ query, page, refresh = false }) =>
      requestJson<KnowledgeInstanceList | Mem0Status>(
        `/api/knowledge/instances?${new URLSearchParams({ query, page: String(page), refresh: String(refresh) })}`,
      ),
    listKnowledgeBindings: (characterName, page = 1) =>
      requestJson<KnowledgeBindingList>(
        `/api/knowledge/bindings?${new URLSearchParams({ character_name: characterName, page: String(page) })}`,
      ),
    addKnowledgeBinding: (characterName, knowledgeId) =>
      requestJson<KnowledgeBindingResult>("/api/knowledge/bindings/add", {
        method: "POST",
        body: JSON.stringify({ character_name: characterName, knowledge_id: knowledgeId }),
      }),
    listKnowledgeBindingNames: (knowledgeId) =>
      requestJson<KnowledgeBindingNames>(
        `/api/knowledge/bindings/knowledge?knowledge_id=${encodeURIComponent(knowledgeId)}`,
      ),
    batchKnowledgeBindings: (knowledgeId, add, remove) =>
      requestJson<KnowledgeBindingNames & { ok: true }>("/api/knowledge/bindings/batch", {
        method: "POST",
        body: JSON.stringify({ knowledge_id: knowledgeId, add, remove }),
      }),
    removeKnowledgeBinding: (characterName, knowledgeId) =>
      requestJson<KnowledgeBindingResult>("/api/knowledge/bindings/remove", {
        method: "POST",
        body: JSON.stringify({ character_name: characterName, knowledge_id: knowledgeId }),
      }),
    addKnowledgeEntry: (knowledgeId, content) =>
      requestJson<KnowledgeEntryPage | Mem0Status>("/api/knowledge/remember-and-list", {
        method: "POST",
        body: JSON.stringify({ knowledge_id: knowledgeId, content }),
      }),
    deleteKnowledgeEntry: (knowledgeId, memoryId) =>
      requestJson<KnowledgeEntryPage | Mem0Status>("/api/knowledge/forget-and-list", {
        method: "POST",
        body: JSON.stringify({ knowledge_id: knowledgeId, memory_id: memoryId }),
      }),
    deleteKnowledge: (knowledgeId) =>
      requestJson<KnowledgeDeleteResult | Mem0Status>("/api/knowledge/delete", {
        method: "POST",
        body: JSON.stringify({ knowledge_id: knowledgeId }),
      }),
    listKnowledgeEntries: (knowledgeId) =>
      requestJson<KnowledgeEntryPage | Mem0Status>(
        `/api/knowledge/entries?${new URLSearchParams({ knowledge_id: knowledgeId })}`,
      ),
    searchKnowledgeEntries: (knowledgeId, query) =>
      requestJson<KnowledgeEntrySearch | Mem0Status>("/api/knowledge/entries/search", {
        method: "POST",
        body: JSON.stringify({ knowledge_id: knowledgeId, query, limit: 200 }),
      }),
    previewKnowledgeImport: (knowledgeId, items) => {
      return uploadFiles<KnowledgeImportPreview>(
        `/api/knowledge/import-preview-upload?knowledge_id=${encodeURIComponent(knowledgeId)}`,
        items,
      );
    },
  };
}
