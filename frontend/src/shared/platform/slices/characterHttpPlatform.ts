import type { HttpTransport } from "../httpTransport";
import type {
  AutoGroupSpritesResult,
  AvatarRuntimesPlatform,
  AvatarRuntimeStatus,
  Character,
  CharacterBriefBatchResult,
  CharacterBriefResult,
  CharacterMemory,
  CharacterMemoryClarity,
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

const VALID_CLARITY_TIERS = new Set<CharacterMemoryClarity>(["canon", "clear", "faded", "dormant"]);

function normalizeCharacterMemoryRow(row: unknown): CharacterMemory {
  if (row && typeof row === "object") {
    const record = row as Record<string, unknown>;
    const normalized: CharacterMemory = {
      id: String(record.id ?? ""),
      memory: String(record.memory ?? record.content ?? record.text ?? record.gist ?? record.detail ?? ""),
    };
    if (typeof record.detail === "string") normalized.detail = record.detail;
    if (typeof record.gist === "string") normalized.gist = record.gist;
    if (typeof record.clarity === "string" && VALID_CLARITY_TIERS.has(record.clarity as CharacterMemoryClarity)) {
      normalized.clarity = record.clarity as CharacterMemoryClarity;
    }
    if (typeof record.retention === "number" && Number.isFinite(record.retention)) {
      normalized.retention = record.retention;
    }
    if (typeof record.kind === "string") normalized.kind = record.kind;
    if (typeof record.pinned === "boolean") normalized.pinned = record.pinned;
    if (typeof record.scope === "string") normalized.scope = record.scope;
    const slotKey = record.slotKey ?? record.slot_key;
    if (typeof slotKey === "string") normalized.slotKey = slotKey;
    const topicTags = record.topicTags ?? record.topic_tags;
    if (Array.isArray(topicTags)) {
      normalized.topicTags = topicTags.map((item) => String(item ?? "")).filter(Boolean);
    }
    if (Array.isArray(record.entities)) {
      normalized.entities = record.entities.map((item) => String(item ?? "")).filter(Boolean);
    }
    if (typeof record.importance === "number" && Number.isFinite(record.importance)) {
      normalized.importance = record.importance;
    }
    const createdAt = record.createdAt ?? record.created_at;
    if (typeof createdAt === "number" && Number.isFinite(createdAt)) normalized.createdAt = createdAt;
    const eventAt = record.eventAt ?? record.event_at;
    if (eventAt === null || (typeof eventAt === "number" && Number.isFinite(eventAt))) {
      normalized.eventAt = eventAt;
    }
    const lastRecalledAt = record.lastRecalledAt ?? record.last_recalled_at;
    if (typeof lastRecalledAt === "number" && Number.isFinite(lastRecalledAt)) {
      normalized.lastRecalledAt = lastRecalledAt;
    }
    const recallCount = record.recallCount ?? record.recall_count;
    if (typeof recallCount === "number" && Number.isFinite(recallCount)) {
      normalized.recallCount = recallCount;
    }
    const sourceSessionId = record.sourceSessionId ?? record.source_session_id;
    if (typeof sourceSessionId === "string") normalized.sourceSessionId = sourceSessionId;
    return normalized;
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
  const result: CharacterMemoryList = {
    agentId: String(record.agentId ?? record.agent_id ?? (fallbackAgentId || "user")),
    count: typeof record.count === "number" ? record.count : memories.length,
    memories,
  };
  if (typeof record.total === "number" && Number.isFinite(record.total)) result.total = record.total;
  if (typeof record.offset === "number" && Number.isFinite(record.offset)) result.offset = record.offset;
  return result;
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
    deleteMemory: async (name, memoryId, options) => {
      const payload: Record<string, unknown> = { memoryId, name };
      if (options?.sessionId !== undefined) payload.sessionId = options.sessionId;
      const result = await requestJson<unknown>("/api/characters/memories/delete", {
        body: JSON.stringify(payload),
        method: "POST",
      });
      return normalizeCharacterMemoryList(result, name);
    },
    deleteMemories: async (name, memoryIds, options) => {
      const payload: Record<string, unknown> = { memoryIds, name };
      if (options?.sessionId !== undefined) payload.sessionId = options.sessionId;
      const result = await requestJson<unknown>("/api/characters/memories/delete-batch", {
        body: JSON.stringify(payload),
        method: "POST",
      });
      return normalizeCharacterMemoryList(result, name);
    },
    pinMemory: async ({ memoryId, name, pinned, sessionId }) => {
      const payload: Record<string, unknown> = { memoryId, name, pinned };
      if (sessionId !== undefined) payload.sessionId = sessionId;
      const result = await requestJson<unknown>("/api/characters/memories/pin", {
        body: JSON.stringify(payload),
        method: "POST",
      });
      return normalizeCharacterMemoryList(result, name);
    },
    awakenMemory: async ({ memoryId, name, sessionId }) => {
      const payload: Record<string, unknown> = { memoryId, name };
      if (sessionId !== undefined) payload.sessionId = sessionId;
      const result = await requestJson<unknown>("/api/characters/memories/awaken", {
        body: JSON.stringify(payload),
        method: "POST",
      });
      return normalizeCharacterMemoryList(result, name);
    },
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
    listMemories: async (name, options) => {
      const payload: Record<string, unknown> = { name };
      if (options?.sessionId !== undefined) payload.sessionId = options.sessionId;
      if (options?.offset !== undefined) payload.offset = options.offset;
      if (options?.limit !== undefined) payload.limit = options.limit;
      const result = await requestJson<unknown>("/api/characters/memories/list", {
        body: JSON.stringify(payload),
        method: "POST",
      });
      return normalizeCharacterMemoryList(result, name);
    },
    exportMemories: async ({ labels, memoryIds, name, sessionId }) => {
      const payload: Record<string, unknown> = { name };
      if (memoryIds?.length) payload.memoryIds = memoryIds;
      if (labels) payload.labels = labels;
      if (sessionId !== undefined) payload.sessionId = sessionId;
      const result = await requestJson<Record<string, unknown>>("/api/characters/memories/export", {
        body: JSON.stringify(payload),
        method: "POST",
      });
      return {
        agentId: String(result?.agentId ?? name),
        count: typeof result?.count === "number" ? result.count : 0,
        text: typeof result?.text === "string" ? result.text : "",
      };
    },
    previewMemoryImport: (name, items) => {
      return uploadFiles<CharacterMemoryImportPreview>(
        `/api/characters/memories/import-preview-upload?name=${encodeURIComponent(name)}`,
        items,
      );
    },
    searchMemories: async ({ limit = 200, memoryMode, name, query, sessionId }) => {
      const payload: Record<string, unknown> = { characterName: name, limit, query };
      if (sessionId !== undefined) payload.sessionId = sessionId;
      if (memoryMode !== undefined) payload.memoryMode = memoryMode;
      const result = await requestJson<unknown>("/api/memory/search", {
        body: JSON.stringify(payload),
        method: "POST",
      });
      return normalizeCharacterMemoryList(result, name);
    },
    remember: async (name, content, options) => {
      const payload: Record<string, unknown> = { content, name };
      if (options?.pinned !== undefined) payload.pinned = options.pinned;
      if (options?.gistText !== undefined) payload.gistText = options.gistText;
      if (options?.slotKey !== undefined) payload.slotKey = options.slotKey;
      if (options?.kind !== undefined) payload.kind = options.kind;
      if (options?.sessionId !== undefined) payload.sessionId = options.sessionId;
      const result = await requestJson<unknown>("/api/characters/memories/add", {
        body: JSON.stringify(payload),
        method: "POST",
      });
      return normalizeCharacterMemoryList(result, name);
    },
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
    saveSpriteGroups: (input) =>
      requestJson<Character>("/api/characters/sprites/groups", {
        body: JSON.stringify(input),
        method: "POST",
      }),
    autoGroupSprites: (input) =>
      requestJson<AutoGroupSpritesResult>("/api/characters/sprites/auto-group", {
        body: JSON.stringify(input),
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
