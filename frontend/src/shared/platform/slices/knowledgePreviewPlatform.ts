import type { KnowledgeImportPreview, KnowledgeImportResult, KnowledgePlatform } from "./knowledgeTypes";
import { type BrowserPreviewContext, clone, delay, previewMemoryImport, previewTask } from "./previewContext";

export function createKnowledgePreviewPlatform(ctx: BrowserPreviewContext): KnowledgePlatform {
  const { knowledgeData } = ctx;

  function requiredKnowledgeValue(value: string, field: string) {
    const text = value.trim();
    if (!text) throw new Error(`${field} is required`);
    return text;
  }

  function removePreviewBinding(name: string, knowledgeId: string) {
    const data = knowledgeData.get(knowledgeId);
    if (!data) return false;
    const before = data.characters.length;
    data.characters = data.characters.filter((character) => character.name !== name);
    if (!data.characters.length && !data.memories.length) knowledgeData.delete(knowledgeId);
    return before !== data.characters.length;
  }

  function addPreviewBinding(name: string, knowledgeId: string) {
    const data = knowledgeData.get(knowledgeId) ?? { memories: [], characters: [] };
    if (!data.characters.some((character) => character.name === name)) {
      data.characters.push({ name, createdAt: new Date().toISOString() });
    }
    knowledgeData.set(knowledgeId, data);
  }

  return {
    getKnowledgeStatus: () => delay({ status: "ready" as const }),
    async importKnowledge(knowledgeId, items, options) {
      const preview = await previewMemoryImport(items);
      const taskId = `knowledge-import-${Date.now()}`;
      previewTask<KnowledgeImportResult>(
        taskId,
        {
          kind: "knowledge-import",
          message: "Importing material",
          phase: "extracting",
          progress: 0.5,
          status: "running",
          title: "Import material",
        },
        options,
      );
      await delay(undefined, 120);
      const result: KnowledgeImportResult = {
        chunkCount: preview.chunkCount,
        duplicateCount: 0,
        estimatedTotalTokens: preview.estimatedTotalTokens,
        extractedCount: items.length,
        fileCount: preview.fileCount,
        memories: items.map((item) => `Knowledge imported from ${item.name}`),
        savedCount: items.length,
        knowledge_id: knowledgeId,
      };
      const currentKnowledge = knowledgeData.get(knowledgeId) ?? { memories: [], characters: [] };
      currentKnowledge.memories.push(
        ...(result.memories ?? []).map((memory, index) => ({ id: `${taskId}-${index}`, memory })),
      );
      knowledgeData.set(knowledgeId, currentKnowledge);
      previewTask(
        taskId,
        {
          kind: "knowledge-import",
          message: "Material import complete",
          phase: "completed",
          progress: 1,
          result,
          status: "succeeded",
          title: "Import material",
        },
        options,
      );
      return clone(result);
    },
    async listKnowledgeInstances({ query, page }) {
      const term = query.trim().toLowerCase();
      const knowledge = [...knowledgeData]
        .filter(([id]) => id.toLowerCase().includes(term))
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([knowledgeId, data]) => ({
          knowledge_id: knowledgeId,
          entryCount: data.memories.length,
          characterCount: data.characters.length,
        }));
      return delay({
        count: knowledge.length,
        page,
        pageSize: 20,
        knowledge: knowledge.slice((page - 1) * 20, page * 20),
      });
    },
    async listKnowledgeBindings(characterName, page = 1) {
      const name = requiredKnowledgeValue(characterName, "character name");
      page = Math.max(1, Math.trunc(page));
      const bindings = [...knowledgeData]
        .flatMap(([knowledgeId, data]) =>
          data.characters
            .filter((character) => character.name === name)
            .map((character) => ({ knowledge_id: knowledgeId, createdAt: character.createdAt })),
        )
        .sort((a, b) => (a.knowledge_id < b.knowledge_id ? -1 : a.knowledge_id > b.knowledge_id ? 1 : 0));
      return delay({
        characterName: name,
        count: bindings.length,
        page,
        pageSize: 20,
        bindings: bindings.slice((page - 1) * 20, page * 20),
      });
    },
    async addKnowledgeBinding(characterName, knowledgeId) {
      const name = requiredKnowledgeValue(characterName, "character name");
      const wid = requiredKnowledgeValue(knowledgeId, "knowledge id");
      addPreviewBinding(name, wid);
      return delay({ ok: true as const, characterName: name, knowledge_id: wid });
    },
    async listKnowledgeBindingNames(knowledgeId) {
      const wid = requiredKnowledgeValue(knowledgeId, "knowledge id");
      return delay({
        knowledge_id: wid,
        characterNames: (knowledgeData.get(wid)?.characters ?? []).map((c) => c.name).sort(),
      });
    },
    async batchKnowledgeBindings(knowledgeId, add, remove) {
      const wid = requiredKnowledgeValue(knowledgeId, "knowledge id");
      const added = [...new Set(add.map((name) => requiredKnowledgeValue(name, "character name")))];
      const removed = [...new Set(remove.map((name) => requiredKnowledgeValue(name, "character name")))];
      if (added.some((name) => removed.includes(name)))
        throw new Error("a character cannot be added and removed in the same request");
      removed.forEach((name) => removePreviewBinding(name, wid));
      added.forEach((name) => addPreviewBinding(name, wid));
      return delay({
        ok: true as const,
        knowledge_id: wid,
        characterNames: (knowledgeData.get(wid)?.characters ?? []).map((c) => c.name).sort(),
      });
    },
    async removeKnowledgeBinding(characterName, knowledgeId) {
      const name = requiredKnowledgeValue(characterName, "character name");
      const wid = requiredKnowledgeValue(knowledgeId, "knowledge id");
      const deleted = removePreviewBinding(name, wid);
      return delay({ ok: true as const, characterName: name, knowledge_id: wid, deleted });
    },
    async addKnowledgeEntry(knowledgeId, content) {
      const wid = requiredKnowledgeValue(knowledgeId, "knowledge id");
      const text = requiredKnowledgeValue(content, "content");
      const data = knowledgeData.get(wid) ?? { memories: [], characters: [] };
      if (!data.memories.some((entry) => entry.memory === text)) {
        data.memories.push({ id: crypto.randomUUID(), memory: text });
      }
      knowledgeData.set(wid, data);
      const memories = data.memories.slice(0, 200);
      return delay({ knowledge_id: wid, count: memories.length, memories });
    },
    async deleteKnowledgeEntry(knowledgeId, memoryId) {
      const wid = requiredKnowledgeValue(knowledgeId, "knowledge id");
      const id = requiredKnowledgeValue(memoryId, "memory id");
      const data = knowledgeData.get(wid);
      if (data) {
        data.memories = data.memories.filter((entry) => entry.id !== id);
        if (!data.memories.length && !data.characters.length) knowledgeData.delete(wid);
      }
      const memories = (data?.memories ?? []).slice(0, 200);
      return delay({ knowledge_id: wid, count: memories.length, memories });
    },
    async deleteKnowledge(knowledgeId) {
      const wid = requiredKnowledgeValue(knowledgeId, "knowledge id");
      const data = knowledgeData.get(wid);
      const result = {
        ok: true,
        knowledge_id: wid,
        deletedEntryCount: data?.memories.length ?? 0,
        deletedBindingCount: data?.characters.length ?? 0,
      };
      knowledgeData.delete(wid);
      return delay(result);
    },
    async listKnowledgeEntries(knowledgeId) {
      const memories = (knowledgeData.get(knowledgeId)?.memories ?? []).slice(0, 200);
      return delay({ knowledge_id: knowledgeId, count: memories.length, memories });
    },
    async searchKnowledgeEntries(knowledgeId, query) {
      const memories = (knowledgeData.get(knowledgeId)?.memories ?? [])
        .filter((row) => row.memory.toLowerCase().includes(query.trim().toLowerCase()))
        .slice(0, 200);
      return delay({ knowledge_id: knowledgeId, query, count: memories.length, memories });
    },
    previewKnowledgeImport: (_knowledgeId, items): Promise<KnowledgeImportPreview> => previewMemoryImport(items),
  };
}
