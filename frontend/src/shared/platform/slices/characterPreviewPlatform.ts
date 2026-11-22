import { numberedTags, tagContents } from "../../assets/assetText";
import { DEFAULT_CHARACTER_COLOR } from "../../constants";
import { PlatformRequestError } from "../errors";
import type {
  AvatarRuntimesPlatform,
  Character,
  CharacterMemoryImportResult,
  CharacterMemoryList,
  CharacterRelationGraph,
  CharacterRelationPlatform,
  CharactersPlatform,
  GeneratedCharacterSprite,
  RelationEdge,
  RelationNode,
  RelationRequest,
} from "./characterTypes";
import { type BrowserPreviewContext, clone, delay, previewMemoryImport, previewTask } from "./previewContext";

const identity = (name: string) => name.trim().toLowerCase();

const addNode = (graph: CharacterRelationGraph, node: RelationNode) => {
  if (graph.nodes.some((n) => n.key === node.key)) throw new Error("Invalid node operation");
  graph.nodes.push(node);
};

const deleteNode = (graph: CharacterRelationGraph, key: string) => {
  if (key === graph.owner) throw new Error("Cannot delete the owner node");
  if (!graph.nodes.some((n) => n.key === key)) throw new Error("Node does not exist");
  graph.nodes = graph.nodes.filter((n) => n.key !== key);
  graph.edges = graph.edges.filter((e) => e.source !== key && e.target !== key);
};

const upsertEdge = (graph: CharacterRelationGraph, edge: RelationEdge) => {
  graph.edges = graph.edges.filter((e) => e.source !== edge.source || e.target !== edge.target);
  graph.edges.push(edge);
};

const deleteEdge = (graph: CharacterRelationGraph, source: string, target: string) => {
  if (!graph.edges.some((e) => e.source === source && e.target === target)) throw new Error("Edge does not exist");
  graph.edges = graph.edges.filter((e) => e.source !== source || e.target !== target);
};

function applyRelationRequest(graph: CharacterRelationGraph, request: RelationRequest) {
  switch (request.op) {
    case "add_node":
      return addNode(graph, request.node);
    case "delete_node":
      return deleteNode(graph, request.key);
    case "upsert_edge":
      return upsertEdge(graph, request.edge);
    case "delete_edge":
      return deleteEdge(graph, request.source, request.target);
    default:
      throw new Error("Unknown graph operation");
  }
}

export function createAvatarRuntimesPreviewPlatform(): AvatarRuntimesPlatform {
  return {
    async status() {
      throw new Error("SDK installation requires a running Shinsekai bridge");
    },
    async prepare() {
      throw new Error("SDK installation requires a running Shinsekai bridge");
    },
    async install() {
      throw new Error("SDK installation requires a running Shinsekai bridge");
    },
  };
}

export function createCharacterRelationPreviewPlatform(ctx: BrowserPreviewContext): CharacterRelationPlatform {
  const { config } = ctx;
  const findCharacter = (name: string) => config.characters.find((c) => identity(c.name) === identity(name));
  const read = (owner: string) => {
    const c = findCharacter(owner);
    if (!c) throw new Error(`Character not found: ${owner}`);
    const graph = structuredClone(c.relation_graph ?? { nodes: [], edges: [] });
    graph.nodes = graph.nodes.map((node) => ({ key: node.key }));
    if (!graph.nodes.length) graph.nodes = [{ key: c.name }];
    return { ...graph, owner: c.name };
  };

  return {
    async getRelationGraph(owner) {
      return read(owner);
    },
    async applyRelationChanges(owner, operations) {
      const graph = read(owner);
      if (!operations.length || operations.length > 1000) throw new Error("Invalid graph operations");
      for (const request of operations) {
        applyRelationRequest(graph, request);
      }
      const keys = new Set(graph.nodes.map((n) => n.key));
      if (graph.nodes.length > 100) throw new Error("Too many nodes");
      if (new Set(graph.nodes.map((n) => identity(n.key))).size !== graph.nodes.length)
        throw new Error("Node keys must be unique");
      for (const node of graph.nodes) {
        if (!node.key.trim() || node.key !== node.key.trim() || node.key.length > 200) throw new Error("Invalid node");
      }
      if (graph.edges.length > 156) throw new Error("Too many edges");
      for (const e of graph.edges) {
        if (
          !keys.has(e.source) ||
          !keys.has(e.target) ||
          e.source === e.target ||
          !Number.isInteger(e.temperature) ||
          Math.abs(e.temperature) > 10 ||
          typeof e.content !== "string" ||
          Array.from(e.content).length > 100 ||
          (e.content !== "" && !e.content.trim())
        )
          throw new Error("Invalid relationship");
      }
      findCharacter(graph.owner)!.relation_graph = {
        nodes: graph.nodes.map((node) => ({ key: node.key })),
        edges: structuredClone(graph.edges),
      };
      return structuredClone(graph);
    },
  };
}

export function createCharactersPreviewPlatform(ctx: BrowserPreviewContext): CharactersPlatform {
  const { config, getTemplateSession, knowledgeData, setTemplateSession } = ctx;
  const generatedSprites = new Map<string, GeneratedCharacterSprite & { imported?: boolean }>();
  const characterMemories = new Map<string, CharacterMemoryList>();

  return {
    importModelStates: async () => {
      throw new Error("Preset import requires the local bridge");
    },
    importModel: async () => {
      throw new Error("Model import requires the local bridge");
    },
    saveModelState: async () => {
      throw new Error("Model state saving requires the local bridge");
    },
    async planSprites(input) {
      const framing = input.referenceImage
        ? ", preserve the reference image's exact framing, crop, camera angle, character scale and screen position throughout, keep all pose changes within the original frame"
        : ", full body, full scene";
      return delay({
        items: Array.from({ length: input.count }, (_, i) => ({
          prompt: `make the character stand and ${["smile warmly with relaxed eyebrows, wave the open right hand beside the head, and rest the relaxed left hand at the side", "furrow the eyebrows slightly, press the lips together thoughtfully, rest the right fingertips on the chin, and place the left hand loosely at the waist", "raise the eyebrows, open the mouth slightly in surprise, and hold both open hands at shoulder height with palms facing forward", "give a confident small smile with slightly narrowed eyes and cross both arms at chest height, with the left hand resting on the right upper arm and the right hand resting on the left upper arm"][i % 4]}${framing}, locked-off static camera, fixed viewpoint and focal length throughout, plain light, sprite`,
          tagging: ["微笑，放松，日常对话", "思考，托腮，分析", "惊讶，张开双手，意外", "自信，抱臂，坚定"][i % 4],
        })),
      });
    },
    async renderSprite(input) {
      const character = config.characters.find((item) => item.name === input.name);
      if (!character) throw new Error("Character not found");
      const result = {
        ...input,
        taskId: crypto.randomUUID(),
        path: input.referenceImage || character.sprites[0]?.path || "data/sprite/mika/normal.png",
        backgroundRemoved: input.removeBackground !== false,
      };
      generatedSprites.set(result.taskId, result);
      return delay(result);
    },
    async getSpriteMouthSetup() {
      return {
        pythonPath: "",
        version: [],
        missing: [],
        compatible: false,
        runtimeReady: false,
        device: "auto",
        modelDirectory: "",
        modelsReady: false,
        models: [
          { id: "yolov3", ready: false, size: 246354512 },
          { id: "hrnetv2", ready: false, size: 38917560 },
        ],
      };
    },
    async configureSpriteMouth() {
      throw new Error("请连接本机新世界以配置口型识别环境。");
    },
    async importSpriteMouthModels() {
      throw new Error("请连接本机新世界以导入口型模型。");
    },
    async downloadSpriteMouthModels() {
      throw new Error("请连接本机新世界以下载口型模型。");
    },
    async installSpriteMouthRuntime() {
      throw new Error("请连接本机新世界以安装口型识别依赖。");
    },
    async generateSpriteMouth() {
      throw new Error("口型同步需要连接本机新世界与 H3 服务；浏览器预览不会伪造识别结果。");
    },
    async readSpriteMouth() {
      throw new Error("请连接本机新世界以读取口型配置。");
    },
    async saveSpriteMouths() {
      throw new Error("请连接本机新世界以保存口型配置。");
    },
    async removeSpriteMouth() {
      throw new Error("请连接本机新世界以移除口型配置。");
    },
    async animateSprite() {
      throw new PlatformRequestError(
        "动态立绘需要连接本机新世界与 H3 服务；浏览器预览不会生成或伪造透明视频。",
        501,
        "local_app_required",
      );
    },
    async analyzeSpriteTransitions() {
      throw new PlatformRequestError("聊天过渡分析需要连接本机新世界。", 501, "local_app_required");
    },
    async generateSpriteTransition() {
      throw new PlatformRequestError("过渡生成需要连接本机新世界与 H3 服务。", 501, "local_app_required");
    },
    async saveSpriteTransitions() {
      throw new PlatformRequestError("请在本机新世界中保存过渡。", 501, "local_app_required");
    },
    async captureSpriteFrame(input) {
      const source = generatedSprites.get(input.taskId);
      if (!source || source.name !== input.name || !source.videoPath) throw new Error("Invalid generated video");
      const result = { ...source, taskId: crypto.randomUUID(), frameTime: input.seconds, imported: false };
      generatedSprites.set(result.taskId, result);
      return delay(result);
    },
    async removeSpriteBackground(input) {
      const source = generatedSprites.get(input.taskId);
      if (!source || source.name !== input.name) throw new Error("Invalid generated sprite");
      const result = { ...source, taskId: crypto.randomUUID(), backgroundRemoved: true, imported: false };
      generatedSprites.set(result.taskId, result);
      return delay(result);
    },
    async importGeneratedSprites(input) {
      const character = config.characters.find((item) => item.name === input.name);
      if (!character) throw new Error("Character not found");
      const tags = tagContents(character.emotion_tags, character.sprites.length);
      for (const item of input.items) {
        const result = generatedSprites.get(item.taskId);
        if (!result || result.name !== input.name) throw new Error("Invalid generated sprite");
        if (result.imported) continue;
        if (input.replace) {
          const target = character.sprites[input.replace.index];
          if (input.items.length !== 1 || !target || target.path !== input.replace.path)
            throw new Error("Original sprite changed");
          character.sprites[input.replace.index] = { ...target, path: result.path };
          tags[input.replace.index] = item.tagging;
        } else {
          character.sprites.push({ path: result.path });
          tags.push(item.tagging);
        }
        result.imported = true;
      }
      character.emotion_tags = numberedTags("立绘", tags);
      return delay(character);
    },
    async autoLabelSprites(name) {
      const character = config.characters.find((item) => item.name === name);
      if (!character) {
        throw new Error(`Character not found: ${name}`);
      }
      const tags = tagContents(character.emotion_tags, character.sprites.length);
      let annotatedCount = 0;
      tags.forEach((tag, index) => {
        if (!tag.trim()) {
          tags[index] = "平静，微笑，站立";
          annotatedCount += 1;
        }
      });
      character.emotion_tags = numberedTags("立绘", tags);
      return delay({
        annotatedCount,
        failedCount: 0,
        failures: [],
        name,
        scope: "character" as const,
        skippedCount: character.sprites.length - annotatedCount,
        tags: character.emotion_tags,
        totalCount: character.sprites.length,
      });
    },
    async delete(name) {
      const target = config.characters.find((character) => character.name === name);
      if (target?.undeletable || target?.is_builtin || name.trim() === "自设") {
        throw new Error(`角色「${name}」为内置角色，不可删除。`);
      }
      config.characters = config.characters.filter((character) => character.name !== name);
      for (const [knowledgeId, data] of knowledgeData) {
        data.characters = data.characters.filter((character) => character.name !== name);
        if (!data.memories.length && !data.characters.length) knowledgeData.delete(knowledgeId);
      }
      const templateSession = getTemplateSession();
      if (templateSession) {
        setTemplateSession({
          ...templateSession,
          selectedCharacters: templateSession.selectedCharacters.filter((selectedName) => selectedName !== name),
        });
      }
    },
    async deleteMemory(name, memoryId) {
      const agentId = name || "user";
      const current = characterMemories.get(agentId) ?? { agentId, count: 0, memories: [] };
      const memories = current.memories.filter((memory) => memory.id !== memoryId);
      const next = { agentId, count: memories.length, memories };
      characterMemories.set(agentId, next);
      return delay(next);
    },
    async pinMemory({ memoryId, name, pinned }) {
      const agentId = name || "user";
      const current = await this.listMemories(agentId);
      const memories = current.memories.map((memory) =>
        memory.id === memoryId
          ? {
              ...memory,
              pinned,
              clarity: (pinned ? "canon" : "clear") as "canon" | "clear",
              retention: 1,
            }
          : memory,
      );
      const next = { agentId, count: memories.length, memories };
      characterMemories.set(agentId, next);
      return delay(next);
    },
    async awakenMemory({ memoryId, name }) {
      const agentId = name || "user";
      const current = await this.listMemories(agentId);
      const memories = current.memories.map((memory) =>
        memory.id === memoryId
          ? {
              ...memory,
              clarity: (memory.pinned ? "canon" : "clear") as "canon" | "clear",
              retention: 1,
              recallCount: (memory.recallCount ?? 0) + 1,
            }
          : memory,
      );
      const next = { agentId, count: memories.length, memories };
      characterMemories.set(agentId, next);
      return delay(next);
    },
    async deleteSpriteVoice(name, spriteIndex) {
      const character = config.characters.find((item) => item.name === name);
      if (!character || !character.sprites[spriteIndex]) {
        throw new Error("立绘不存在。");
      }
      character.sprites[spriteIndex] = {
        ...character.sprites[spriteIndex],
        voice_path: "",
        voice_text: "",
      };
      return delay(character);
    },
    async deleteAllSprites(name) {
      const character = config.characters.find((item) => item.name === name);
      if (!character) {
        throw new Error(`角色不存在：${name}`);
      }
      character.sprites = [];
      character.emotion_tags = "";
      return delay(character);
    },
    async deleteSprite(name, spriteIndex) {
      const character = config.characters.find((item) => item.name === name);
      if (!character || !character.sprites[spriteIndex]) {
        throw new Error("立绘不存在。");
      }
      character.sprites = character.sprites.filter((_, index) => index !== spriteIndex);
      const tags = character.emotion_tags
        .split(/\r?\n/)
        .filter(Boolean)
        .filter((_, index) => index !== spriteIndex)
        .map((line, index) => `立绘 ${index + 1}：${line.split(/：|:/).slice(1).join("：")}`)
        .join("\n");
      character.emotion_tags = tags ? `${tags}\n` : "";
      return delay(character);
    },
    export: (name) => delay(`./data/export/${name}.char`),
    async ensureBriefs(names) {
      const wanted = new Set(names);
      const selected = config.characters.filter((character) => wanted.has(character.name));
      const generatedNames: string[] = [];
      for (const character of selected) {
        if (!character.character_brief?.trim()) {
          character.character_brief = `${character.name}的精简人物简介。`;
          generatedNames.push(character.name);
        }
      }
      return delay({ characters: selected, generatedNames });
    },
    async generateBrief(input) {
      return delay({
        characterBrief: `${input.name || "角色"}的精简人物简介。`,
        message: "输出成功",
      });
    },
    async generateSetting(input) {
      return delay({
        characterBrief: `${input.name || "角色"}的精简人物简介。`,
        characterSetting: `${input.name || "角色"}的背景信息：\n1. 浏览器预览生成的设定。\n\n语言习惯：\n1. 温和且简洁。`,
        message: "输出成功",
      });
    },
    import: async (items) => {
      const imported = items.map<Character>((item, index) => {
        const label = item instanceof File ? item.name : item.split("/").pop() || `character-${index + 1}`;
        return {
          avatar_type: "static",
          avatars: {},
          character_brief: "",
          relation_graph: { nodes: [], edges: [] },
          character_setting: "导入预览角色",
          color: DEFAULT_CHARACTER_COLOR,
          emotion_tags: "",
          name: `Imported ${index + 1}`,
          pronunciation_map: {},
          speech_speed: 1,
          speech_volume: 1,
          sprite_prefix: label.replace(/\W+/g, "_") || "imported",
          sprite_scale: 1,
          sprites: [],
        };
      });
      config.characters.push(...imported);
      return delay(imported);
    },
    getMem0Status: () => delay({ status: "ready" as const }),
    async importMemories(name, items, options) {
      const preview = await previewMemoryImport(items);
      const taskId = `memory-import-${Date.now()}`;
      previewTask<CharacterMemoryImportResult>(
        taskId,
        {
          kind: "character-memory-import",
          message: "Preparing dialogue chunks",
          phase: "preparing",
          title: "Import long-term memories",
        },
        options,
      );
      await delay(undefined, 80);
      previewTask<CharacterMemoryImportResult>(
        taskId,
        {
          kind: "character-memory-import",
          message: "Extracting long-term memories",
          phase: "extracting",
          progress: 0.55,
          status: "running",
          title: "Import long-term memories",
        },
        options,
      );
      await delay(undefined, 120);
      const memories = items.map((item, index) => {
        return `Imported memory ${index + 1} from ${item.name}`;
      });
      const agentId = name || "user";
      const current = characterMemories.get(agentId) ?? { agentId, count: 0, memories: [] };
      const nextMemories = [
        ...current.memories,
        ...memories.map((memory, index) => ({ id: `${agentId}-import-${Date.now()}-${index}`, memory })),
      ];
      characterMemories.set(agentId, { agentId, count: nextMemories.length, memories: nextMemories });
      const result: CharacterMemoryImportResult = {
        chunkCount: preview.chunkCount,
        duplicateCount: 0,
        estimatedTotalTokens: preview.estimatedTotalTokens,
        extractedCount: memories.length,
        fileCount: preview.fileCount,
        memories,
        savedCount: memories.length,
      };
      previewTask(
        taskId,
        {
          kind: "character-memory-import",
          message: "Memory import complete",
          phase: "completed",
          progress: 1,
          result,
          status: "succeeded",
          title: "Import long-term memories",
        },
        options,
      );
      return clone(result);
    },
    list: () => delay(config.characters),
    revision: () => delay(JSON.stringify(config.characters)),
    async listMemories(name) {
      const agentId = name || "user";
      const existing = characterMemories.get(agentId) ?? {
        agentId,
        count: 1,
        memories: [{ id: `${agentId}-preview`, memory: "浏览器预览记忆。" }],
      };
      characterMemories.set(agentId, existing);
      return delay(existing);
    },
    previewMemoryImport: (_name, items) => previewMemoryImport(items),
    async searchMemories({ limit = 200, name, query }) {
      const agentId = name || "user";
      const existing = await this.listMemories(agentId);
      const normalizedQuery = query.trim().toLowerCase();
      const memories = normalizedQuery
        ? existing.memories.filter((memory) => memory.memory.toLowerCase().includes(normalizedQuery))
        : existing.memories;
      const limitedMemories = memories.slice(0, limit);
      return delay({ agentId, count: limitedMemories.length, memories: limitedMemories });
    },
    async remember(name, content, options) {
      const agentId = name || "user";
      const current = characterMemories.get(agentId) ?? { agentId, count: 0, memories: [] };
      const memoryItem = options?.pinned
        ? {
            id: `${agentId}-${Date.now()}`,
            memory: content,
            detail: content,
            gist: options.gistText?.trim() || content,
            pinned: true,
            clarity: "canon" as const,
            retention: 1,
          }
        : { id: `${agentId}-${Date.now()}`, memory: content };
      const memories = [...current.memories, memoryItem];
      const next = { agentId, count: memories.length, memories };
      characterMemories.set(agentId, next);
      return delay(next);
    },
    async save(character, originalName) {
      const idIndex = character.id ? config.characters.findIndex((item) => item.id === character.id) : -1;
      const index =
        idIndex >= 0
          ? idIndex
          : originalName
            ? config.characters.findIndex((item) => item.name === originalName)
            : config.characters.findIndex((item) => item.name === character.name);
      const effectiveOriginalName = index >= 0 ? config.characters[index].name : originalName;
      const duplicateIndex = config.characters.findIndex(
        (item, itemIndex) => item.name === character.name && itemIndex !== index,
      );
      if (duplicateIndex >= 0) {
        throw new Error(`名称「${character.name}」已与其他角色重复！`);
      }
      const relationGraph = clone(
        (index >= 0 ? config.characters[index].relation_graph : character.relation_graph) ?? {
          nodes: [],
          edges: [],
        },
      );
      const migratedGraphs = new Map<number, NonNullable<Character["relation_graph"]>>();
      if (index >= 0 && effectiveOriginalName && effectiveOriginalName !== character.name) {
        for (const [characterIndex, existing] of config.characters.entries()) {
          const graph = clone(existing.relation_graph ?? { nodes: [], edges: [] });
          graph.nodes = graph.nodes.map((node) => ({
            ...node,
            key: identity(node.key) === identity(effectiveOriginalName) ? character.name : node.key,
          }));
          if (new Set(graph.nodes.map((node) => identity(node.key))).size !== graph.nodes.length) {
            throw new Error("Node keys must be unique");
          }
          graph.edges = graph.edges.map((edge) => ({
            ...edge,
            source: identity(edge.source) === identity(effectiveOriginalName) ? character.name : edge.source,
            target: identity(edge.target) === identity(effectiveOriginalName) ? character.name : edge.target,
          }));
          migratedGraphs.set(characterIndex, graph);
        }
      }
      const existing = index >= 0 ? clone(config.characters[index]) : undefined;
      const savedCharacter = {
        ...existing,
        ...clone(character),
        ...(existing?.id ? { id: existing.id } : {}),
        color: character.color.trim() || DEFAULT_CHARACTER_COLOR,
        emotion_tags: character.emotion_tags ?? (index >= 0 ? config.characters[index].emotion_tags : ""),
        gpt_model_path: character.gpt_model_path?.trim() || "",
        prompt_lang: character.prompt_lang?.trim() || "",
        prompt_text: character.prompt_text?.trim() || "",
        refer_audio_path: character.refer_audio_path?.trim() || "",
        sovits_model_path: character.sovits_model_path?.trim() || "",
        sprite_prefix: character.sprite_prefix.trim() || "temp",
        sprite_scale: character.sprite_scale ?? (index >= 0 ? config.characters[index].sprite_scale : 1),
        sprites:
          index >= 0
            ? config.characters[index].sprites.map((sprite, spriteIndex) => ({
                ...sprite,
                group:
                  character.sprites[spriteIndex]?.group !== undefined
                    ? character.sprites[spriteIndex]?.group
                    : sprite.group,
                portrait_crop:
                  character.sprites[spriteIndex]?.portrait_crop === null
                    ? null
                    : (character.sprites[spriteIndex]?.portrait_crop ?? sprite.portrait_crop),
              }))
            : [],
        character_setting: character.character_setting.trim(),
        relation_graph: migratedGraphs.get(index) ?? relationGraph,
      };
      for (const [characterIndex, graph] of migratedGraphs) {
        if (characterIndex !== index) config.characters[characterIndex].relation_graph = graph;
      }
      if (index >= 0) {
        config.characters[index] = savedCharacter;
      } else {
        config.characters.push(savedCharacter);
      }
      if (effectiveOriginalName && effectiveOriginalName !== savedCharacter.name) {
        for (const data of knowledgeData.values()) {
          const oldBinding = data.characters.find((item) => item.name === effectiveOriginalName);
          if (!oldBinding) continue;
          const targetBinding = data.characters.find((item) => item.name === savedCharacter.name);
          if (targetBinding) {
            targetBinding.createdAt = [targetBinding.createdAt, oldBinding.createdAt].sort()[0];
            data.characters = data.characters.filter((item) => item.name !== effectiveOriginalName);
          } else {
            oldBinding.name = savedCharacter.name;
          }
        }
      }
      const templateSession = getTemplateSession();
      if (templateSession && effectiveOriginalName && effectiveOriginalName !== savedCharacter.name) {
        setTemplateSession({
          ...templateSession,
          selectedCharacters: templateSession.selectedCharacters.map((name) =>
            name === effectiveOriginalName ? savedCharacter.name : name,
          ),
        });
      }
      return delay(savedCharacter);
    },
    async saveEmotionTags(name, emotionTags) {
      if (!name) {
        throw new Error("请先选择或创建角色！");
      }
      if (!emotionTags) {
        throw new Error("请输入情绪标注！");
      }
      const character = config.characters.find((item) => item.name === name);
      if (!character) {
        throw new Error(`找不到角色: ${name}`);
      }
      character.emotion_tags = emotionTags;
      return delay(character);
    },
    async saveSpriteScale(name, scale) {
      const character = config.characters.find((item) => item.name === name);
      if (!character) {
        throw new Error(`角色不存在：${name}`);
      }
      character.sprite_scale = scale;
      return delay(character);
    },
    async saveSpriteGroups(input) {
      const character = config.characters.find((item) => item.name === input.name);
      if (!character) {
        throw new Error(`角色不存在：${input.name}`);
      }
      let groups = [...(input.spriteGroups ?? character.sprite_groups ?? ["默认"])];
      if (!groups.includes("默认")) groups.unshift("默认");
      if (input.renameFrom && input.renameTo && input.renameFrom !== "默认") {
        const nextName = input.renameTo.trim();
        if (nextName) {
          groups = groups.map((g) => (g === input.renameFrom ? nextName : g));
          character.sprites = character.sprites.map((s) =>
            (s.group || "默认") === input.renameFrom ? { ...s, group: nextName === "默认" ? null : nextName } : s,
          );
          if (character.default_sprite_group === input.renameFrom) {
            character.default_sprite_group = nextName;
          }
        }
      }
      if (input.deleteGroup && input.deleteGroup !== "默认") {
        groups = groups.filter((g) => g !== input.deleteGroup);
        character.sprites = character.sprites.map((s) =>
          (s.group || "默认") === input.deleteGroup ? { ...s, group: null } : s,
        );
        if (character.default_sprite_group === input.deleteGroup) {
          character.default_sprite_group = "默认";
        }
      }
      if (input.assignments) {
        for (const [rawIndex, rawGroup] of Object.entries(input.assignments)) {
          const idx = Number(rawIndex);
          if (!Number.isInteger(idx) || !character.sprites[idx]) continue;
          const clean = (rawGroup ?? "").trim();
          const targetGroup = !clean || clean === "默认" ? null : clean;
          if (targetGroup && !groups.includes(targetGroup)) groups.push(targetGroup);
          character.sprites[idx] = { ...character.sprites[idx], group: targetGroup };
        }
      }
      character.sprite_groups = [...new Set(["默认", ...groups.filter((g) => g && g !== "默认")])];
      if (input.defaultSpriteGroup !== undefined) {
        const def = input.defaultSpriteGroup.trim() || "默认";
        character.default_sprite_group = def;
        if (!character.sprite_groups.includes(def)) character.sprite_groups.push(def);
      }
      if (input.fallbackToDefaultGroup !== undefined) {
        character.fallback_to_default_group = input.fallbackToDefaultGroup;
      }
      return delay(character);
    },
    async autoGroupSprites(input) {
      const character = config.characters.find((item) => item.name === input.name);
      if (!character) {
        throw new Error(`角色不存在：${input.name}`);
      }
      const assignments: Record<string, string> = {};
      const byGroup = new Map<string, number[]>();
      character.sprites.forEach((sprite, idx) => {
        const current = (sprite.group || "").trim();
        if (current && current !== "默认" && !input.overwriteExisting) {
          assignments[String(idx)] = current;
          byGroup.set(current, [...(byGroup.get(current) ?? []), idx]);
          return;
        }
        const filename = (sprite.path.split(/[\\/]/).pop() ?? "").replace(/\.[^.]+$/, "");
        const prefixMatch = filename.match(/^([a-zA-Z\u4e00-\u9fa5]+)[_-]/);
        const group = prefixMatch ? prefixMatch[1] : "默认";
        assignments[String(idx)] = group;
        byGroup.set(group, [...(byGroup.get(group) ?? []), idx]);
      });
      const spriteGroups = ["默认", ...[...byGroup.keys()].filter((g) => g !== "默认")];
      const groups = spriteGroups
        .filter((g) => byGroup.has(g))
        .map((group) => ({
          group,
          count: (byGroup.get(group) ?? []).length,
          spriteIndices: byGroup.get(group) ?? [],
        }));
      const changedCount = character.sprites.reduce((acc, sprite, idx) => {
        const prev = (sprite.group || "").trim() || "默认";
        const next = assignments[String(idx)] || "默认";
        return prev !== next ? acc + 1 : acc;
      }, 0);
      let updatedCharacter: Character | null = null;
      if (input.apply) {
        updatedCharacter = await this.saveSpriteGroups({
          name: character.name,
          spriteGroups,
          assignments,
        });
      }
      return delay({
        characterName: character.name,
        avatarType: input.avatarType || character.avatar_type || "static",
        groups,
        spriteGroups,
        assignments,
        changedCount,
        applied: Boolean(input.apply),
        character: updatedCharacter,
      });
    },
    async saveSpriteVoiceText(name, spriteIndex, voiceText) {
      const character = config.characters.find((item) => item.name === name);
      if (!character || !character.sprites[spriteIndex]) {
        throw new Error("立绘不存在。");
      }
      character.sprites[spriteIndex] = { ...character.sprites[spriteIndex], voice_text: voiceText };
      return delay(character);
    },
    async saveSpriteVoiceType(name, spriteIndex, voiceType) {
      const character = config.characters.find((item) => item.name === name);
      if (!character || !character.sprites[spriteIndex]) {
        throw new Error("立绘不存在。");
      }
      character.sprites[spriteIndex] = {
        ...character.sprites[spriteIndex],
        voice_type: voiceType,
      };
      return delay(character);
    },
    async translateFields(input) {
      return delay({
        characterSetting: input.characterSetting,
        emotionTags: input.emotionTags,
        name: input.name,
      });
    },
    async uploadSprites(input) {
      const character = config.characters.find((item) => item.name === input.name);
      if (!character) {
        throw new Error(`角色不存在：${input.name}`);
      }
      const start = character.sprites.length;
      const groupName = input.group?.trim();
      const targetGroup = !groupName || groupName === "默认" ? undefined : groupName;
      const nextSprites = input.paths.map((path) => ({
        path: `data/sprite/${character.sprite_prefix}/${path.split(/[\\/]/).pop() ?? path}`,
        ...(targetGroup ? { group: targetGroup } : {}),
      }));
      character.sprites = [...character.sprites, ...nextSprites];
      if (targetGroup) {
        const currentGroups = character.sprite_groups ?? ["默认"];
        if (!currentGroups.includes(targetGroup)) {
          character.sprite_groups = [...currentGroups, targetGroup];
        }
      }
      const extraTags = input.paths.map((_, index) => `立绘 ${start + index + 1}：`).join("\n");
      character.emotion_tags = `${input.emotionTags || character.emotion_tags || ""}${extraTags ? `${extraTags}\n` : ""}`;
      return delay(character);
    },
    async uploadSpriteVoice(input) {
      const character = config.characters.find((item) => item.name === input.name);
      if (!character || !character.sprites[input.spriteIndex]) {
        throw new Error("立绘不存在。");
      }
      character.sprites[input.spriteIndex] = {
        ...character.sprites[input.spriteIndex],
        voice_path: input.voicePath,
        voice_text: input.voiceText,
        voice_type: input.voiceType,
      };
      return delay(character);
    },
  };
}
