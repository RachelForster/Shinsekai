import type { HttpTransport } from "../httpTransport";
import type {
  AvatarRuntimesPlatform,
  AvatarRuntimeStatus,
  Character,
  CharacterBriefBatchResult,
  CharacterBriefResult,
  CharacterMemory,
  CharacterMemoryImportPreview,
  CharacterMemoryImportResult,
  CharacterMemoryList,
  CharacterRelationGraph,
  CharacterRelationPlatform,
  CharacterSettingResult,
  CharactersPlatform,
  CharacterTranslateResult,
  GeneratedCharacterSprite,
  GeneratedSpriteMouth,
  GeneratedSpriteTransition,
  Mem0Status,
  SpriteMouthSetup,
  SpritePromptPair,
  SpriteTransitionAnalysis,
} from "./characterTypes";
import type { ImageAutoLabelResult, TaskSnapshot } from "./taskTypes";

function normalizeCharacterMemoryRow(row: unknown): CharacterMemory {
  if (row && typeof row === "object") {
    const record = row as Record<string, unknown>;
    return {
      id: String(record.id ?? ""),
      memory: String(record.memory ?? record.content ?? record.text ?? ""),
    };
  }
  return { id: "", memory: String(row ?? "") };
}

function normalizeCharacterMemoryList(payload: unknown, fallbackAgentId: string): CharacterMemoryList {
  const record = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const rawMemories = Array.isArray(record.memories)
    ? record.memories
    : Array.isArray(record.results)
      ? record.results
      : [];
  const memories = rawMemories.map(normalizeCharacterMemoryRow);
  return {
    agentId: String(record.agentId ?? record.agent_id ?? (fallbackAgentId || "user")),
    count: typeof record.count === "number" ? record.count : memories.length,
    memories,
  };
}

export function createCharacterRelationHttpPlatform(transport: HttpTransport): CharacterRelationPlatform {
  const { requestJson } = transport;

  return {
    getRelationGraph: (owner) =>
      requestJson<CharacterRelationGraph>(`/api/character-relations/graphs/${encodeURIComponent(owner)}`),
    applyRelationChanges: (owner, operations) =>
      requestJson<CharacterRelationGraph>(`/api/character-relations/graphs/${encodeURIComponent(owner)}/changes`, {
        method: "POST",
        body: JSON.stringify({ operations }),
      }),
  };
}

export function createAvatarRuntimesHttpPlatform(transport: HttpTransport): AvatarRuntimesPlatform {
  const { requestJson, waitForTask } = transport;

  return {
    status: (format) =>
      requestJson<AvatarRuntimeStatus>(`/api/avatar/runtime/${encodeURIComponent(format)}/status`, {
        method: "POST",
        body: "{}",
      }),
    async prepare(format, input) {
      const task = await requestJson<TaskSnapshot<unknown>>(
        `/api/avatar/runtime/${encodeURIComponent(format)}/prepare`,
        { method: "POST", body: JSON.stringify(input) },
      );
      return waitForTask(task);
    },
    async install(format, input) {
      const task = await requestJson<TaskSnapshot<AvatarRuntimeStatus>>(
        `/api/avatar/runtime/${encodeURIComponent(format)}/install`,
        { method: "POST", body: JSON.stringify(input) },
      );
      return waitForTask(task);
    },
  };
}

export function createCharactersHttpPlatform(transport: HttpTransport): CharactersPlatform {
  const { encodePath, exportPackage, isFileList, requestJson, uploadFiles, waitForTask } = transport;

  return {
    getSpriteMouthSetup: () => requestJson("/api/characters/sprites/mouth/status", { method: "POST", body: "{}" }),
    configureSpriteMouth: (input) =>
      requestJson("/api/characters/sprites/mouth/configure", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    importSpriteMouthModels: (input) =>
      requestJson("/api/characters/sprites/mouth/models/import", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    async downloadSpriteMouthModels(options) {
      const task = await requestJson<TaskSnapshot<SpriteMouthSetup>>("/api/characters/sprites/mouth/models/download", {
        method: "POST",
        body: "{}",
      });
      return waitForTask(task, options);
    },
    async installSpriteMouthRuntime(options) {
      const task = await requestJson<TaskSnapshot<SpriteMouthSetup>>("/api/characters/sprites/mouth/runtime/install", {
        method: "POST",
        body: "{}",
      });
      return waitForTask(task, options);
    },
    async generateSpriteMouth(input, options) {
      const task = await requestJson<TaskSnapshot<GeneratedSpriteMouth>>("/api/characters/sprites/mouth/generate", {
        method: "POST",
        body: JSON.stringify(input),
      });
      return waitForTask(task, options);
    },
    readSpriteMouth: (path) =>
      requestJson("/api/characters/sprites/mouth/read", { method: "POST", body: JSON.stringify({ path }) }),
    saveSpriteMouths: (input) =>
      requestJson("/api/characters/sprites/mouth/save", { method: "POST", body: JSON.stringify(input) }),
    removeSpriteMouth: (input) =>
      requestJson("/api/characters/sprites/mouth/remove", { method: "POST", body: JSON.stringify(input) }),
    async planSprites(input, options) {
      const task = await requestJson<TaskSnapshot<{ items: SpritePromptPair[] }>>("/api/characters/sprites/plan", {
        method: "POST",
        body: JSON.stringify(input),
      });
      return waitForTask(task, options);
    },
    async renderSprite(input, options) {
      const task = await requestJson<TaskSnapshot<GeneratedCharacterSprite>>("/api/characters/sprites/render", {
        method: "POST",
        body: JSON.stringify(input),
      });
      return waitForTask(task, options);
    },
    async animateSprite(input, options) {
      const task = await requestJson<TaskSnapshot<GeneratedCharacterSprite>>("/api/characters/sprites/animate", {
        method: "POST",
        body: JSON.stringify(input),
      });
      return waitForTask(task, options);
    },
    async analyzeSpriteTransitions(input, options) {
      const task = await requestJson<TaskSnapshot<SpriteTransitionAnalysis>>(
        "/api/characters/sprites/transitions/analyze",
        { method: "POST", body: JSON.stringify(input) },
      );
      return waitForTask(task, options);
    },
    async generateSpriteTransition(input, options) {
      const task = await requestJson<TaskSnapshot<GeneratedSpriteTransition>>(
        "/api/characters/sprites/transitions/generate",
        { method: "POST", body: JSON.stringify(input) },
      );
      return waitForTask(task, options);
    },
    saveSpriteTransitions: (input) =>
      requestJson<Character>("/api/characters/sprites/transitions/save", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    async captureSpriteFrame(input, options) {
      const task = await requestJson<TaskSnapshot<GeneratedCharacterSprite>>("/api/characters/sprites/frame", {
        method: "POST",
        body: JSON.stringify(input),
      });
      return waitForTask(task, options);
    },
    async removeSpriteBackground(input, options) {
      const task = await requestJson<TaskSnapshot<GeneratedCharacterSprite>>(
        "/api/characters/sprites/remove-background",
        { method: "POST", body: JSON.stringify(input) },
      );
      return waitForTask(task, options);
    },
    importGeneratedSprites: (input) =>
      requestJson<Character>("/api/characters/sprites/import-generated", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    importModelStates: async (input) => {
      const task = await requestJson<TaskSnapshot<Character>>("/api/characters/model/states/import", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task);
    },
    importModel: async (input) => {
      const task = await requestJson<TaskSnapshot<Character>>("/api/characters/model/import", {
        body: JSON.stringify(input),
        method: "POST",
      });
      return waitForTask(task);
    },
    saveModelState: (input) =>
      requestJson<Character>("/api/characters/model/state", { body: JSON.stringify(input), method: "POST" }),
    autoLabelSprites: async (name, options) => {
      const task = await requestJson<TaskSnapshot<ImageAutoLabelResult>>("/api/characters/sprites/auto-label", {
        body: JSON.stringify({ name }),
        method: "POST",
      });
      return waitForTask(task, options);
    },
    delete: async (name) => {
      await requestJson(`/api/characters/${encodePath(name)}`, { method: "DELETE" });
    },
    deleteMemory: (name, memoryId) =>
      requestJson<CharacterMemoryList>("/api/characters/memories/delete", {
        body: JSON.stringify({ memoryId, name }),
        method: "POST",
      }),
    deleteSpriteVoice: (name, spriteIndex) =>
      requestJson<Character>("/api/characters/sprite-voice/delete", {
        body: JSON.stringify({ name, spriteIndex }),
        method: "POST",
      }),
    deleteAllSprites: (name) =>
      requestJson<Character>("/api/characters/sprites/delete-all", {
        body: JSON.stringify({ name }),
        method: "POST",
      }),
    deleteSprite: (name, spriteIndex) =>
      requestJson<Character>("/api/characters/sprites/delete", {
        body: JSON.stringify({ name, spriteIndex }),
        method: "POST",
      }),
    export: (name) => exportPackage("characters", name),
    ensureBriefs: (names) =>
      requestJson<CharacterBriefBatchResult>("/api/characters/ensure-briefs", {
        body: JSON.stringify({ names }),
        method: "POST",
      }),
    generateBrief: (input) =>
      requestJson<CharacterBriefResult>("/api/characters/ai-brief", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    generateSetting: (input) =>
      requestJson<CharacterSettingResult>("/api/characters/ai-setting", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    import: (items) => {
      if (isFileList(items)) {
        return uploadFiles<Character[]>("/api/characters/import-upload", items);
      }
      return requestJson<Character[]>("/api/characters/import", {
        body: JSON.stringify({ paths: items }),
        method: "POST",
      });
    },
    getMem0Status: () =>
      requestJson<Mem0Status>("/api/characters/memories/status", {
        body: "{}",
        method: "POST",
      }),
    importMemories: async (name, items, options) => {
      const task = await uploadFiles<TaskSnapshot<CharacterMemoryImportResult>>(
        `/api/characters/memories/import-upload?name=${encodeURIComponent(name)}`,
        items,
      );
      return waitForTask(task, options);
    },
    list: () => requestJson<Character[]>("/api/characters"),
    revision: () => requestJson<string>("/api/characters?view=revision"),
    listMemories: (name) =>
      requestJson<CharacterMemoryList>("/api/characters/memories/list", {
        body: JSON.stringify({ name }),
        method: "POST",
      }),
    previewMemoryImport: (name, items) => {
      return uploadFiles<CharacterMemoryImportPreview>(
        `/api/characters/memories/import-preview-upload?name=${encodeURIComponent(name)}`,
        items,
      );
    },
    searchMemories: async ({ limit = 200, name, query }) => {
      const result = await requestJson<unknown>("/api/memory/search", {
        body: JSON.stringify({ characterName: name, limit, query }),
        method: "POST",
      });
      return normalizeCharacterMemoryList(result, name);
    },
    remember: (name, content) =>
      requestJson<CharacterMemoryList>("/api/characters/memories/add", {
        body: JSON.stringify({ content, name }),
        method: "POST",
      }),
    save: (character, originalName) =>
      requestJson<Character>("/api/characters", {
        body: JSON.stringify({ character, originalName }),
        method: "POST",
      }),
    saveEmotionTags: (name, emotionTags) =>
      requestJson<Character>("/api/characters/emotion-tags", {
        body: JSON.stringify({ emotionTags, name }),
        method: "POST",
      }),
    saveSpriteScale: (name, scale) =>
      requestJson<Character>("/api/characters/sprite-scale", {
        body: JSON.stringify({ name, scale }),
        method: "POST",
      }),
    saveSpriteVoiceText: (name, spriteIndex, voiceText) =>
      requestJson<Character>("/api/characters/sprite-voice/text", {
        body: JSON.stringify({ name, spriteIndex, voiceText }),
        method: "POST",
      }),
    saveSpriteVoiceType: (name, spriteIndex, voiceType) =>
      requestJson<Character>("/api/characters/sprite-voice/voice-type", {
        body: JSON.stringify({ name, spriteIndex, voiceType }),
        method: "POST",
      }),
    translateFields: (input) =>
      requestJson<CharacterTranslateResult>("/api/characters/translate", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    uploadSprites: (input) =>
      requestJson<Character>("/api/characters/sprites/upload", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    uploadSpriteVoice: (input) =>
      requestJson<Character>("/api/characters/sprite-voice/upload", {
        body: JSON.stringify(input),
        method: "POST",
      }),
  };
}
