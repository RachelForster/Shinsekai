import type { ChatSnapshot, ShinsekaiPlatform, StoryGenerationTask, TaskProgressOptions } from "./types";
import { previewStoryGraph } from "./previewStoryGraph";
import { TRANSPARENT_BACKGROUND_NAME } from "../constants";
import { translateRuntimeMessage } from "../i18n/runtimeLanguage";
import type { StoryDocument } from "./storyEditorTypes";

function previewStoryGeneration(id: string, status: StoryGenerationTask["status"]): StoryGenerationTask {
  const now = Date.now();
  return {
    artifactHashes: {},
    assumptions: ["Browser preview uses a compact three-scene mystery."],
    cancelRequested: status === "cancelled",
    completedStages: status === "succeeded" ? ["foundation", "characters", "narrative"] : [],
    cost: { estimatedTokens: 2100, inputChars: 5600, outputChars: 2800, requests: 3 },
    createdAt: now,
    currentStage: status === "succeeded" ? "complete" : "foundation",
    draftPath: status === "succeeded" ? `data/stories/.generation/${id}/draft.json` : "",
    error: null,
    id,
    options: {},
    repairAttempts: 0,
    resourceCatalog: {},
    status,
    synopsis: "A compact preview story.",
    updatedAt: now,
    validation:
      status === "succeeded"
        ? {
            castFailureNodeIds: [],
            endingCoverage: 1,
            endingNodeIds: ["truth-ending", "leave-ending"],
            exploredStates: 12,
            issues: [],
            reachableEndingIds: ["truth-ending", "leave-ending"],
            reachableNodeIds: ["opening", "clue", "truth-ending", "leave-ending"],
            sourceHash: "preview",
            valid: true,
          }
        : null,
  };
}

export function createStoryPreviewPlatform(
  getChat: () => ChatSnapshot,
  setChat: (snapshot: ChatSnapshot) => void,
  deleteConversations: (storyPath: string) => void,
): ShinsekaiPlatform["story"] {
  const tasks = new Map<string, StoryGenerationTask>();
  const saves = new Map<string, ChatSnapshot>();
  const documents = new Map<string, StoryDocument>();
  const documentFor = (storyPath: string): StoryDocument => {
    const existing = documents.get(storyPath);
    if (existing) return structuredClone(existing);
    const task = [...tasks.values()].find((item) => item.draftPath === storyPath);
    if (!task || !previewStoryGraph.graph) throw new Error(translateRuntimeMessage("plat.preview.story.notFound"));
    const document = {
      storyPath,
      title: previewStoryGraph.title,
      version: 1,
      sourceHash: task.id,
      graph: structuredClone(previewStoryGraph.graph),
      authoringBrief: task.synopsis,
    };
    documents.set(storyPath, document);
    return structuredClone(document);
  };
  let activeStoryPath = "";
  const read = (id: string) => {
    const task = tasks.get(id);
    if (!task) throw new Error(translateRuntimeMessage("plat.preview.story.expired"));
    return task;
  };
  const finish = async (task: StoryGenerationTask, options?: TaskProgressOptions<StoryGenerationTask>) => {
    tasks.set(task.id, task);
    options?.onTaskUpdate?.({
      id: task.id,
      kind: "story-generation",
      title: translateRuntimeMessage("plat.preview.story.generateTitle"),
      message: translateRuntimeMessage("plat.preview.story.done"),
      createdAt: task.createdAt,
      updatedAt: task.updatedAt,
      logs: [],
      error: "",
      phase: "complete",
      progress: 1,
      result: task,
      status: "succeeded",
    });
    return task;
  };
  return {
    delete: async (storyPath) => {
      documentFor(storyPath);
      const chat = getChat();
      if (activeStoryPath === storyPath && (chat.chatProcessRunning || chat.chatRuntimeClosing)) {
        throw new Error(translateRuntimeMessage("plat.preview.story.closeChatBeforeDelete"));
      }
      deleteConversations(storyPath);
      for (const [id, task] of tasks) {
        if (task.draftPath === storyPath) tasks.delete(id);
      }
      documents.delete(storyPath);
      saves.delete(storyPath);
      if (activeStoryPath === storyPath) {
        activeStoryPath = "";
        setChat({ ...chat, story: undefined });
      }
    },
    readDocument: async (storyPath) => documentFor(storyPath),
    saveDocument: async (input) => {
      const base = documentFor(input.storyPath);
      if (base.sourceHash !== input.sourceHash) throw new Error(translateRuntimeMessage("plat.preview.story.changed"));
      const task = [...tasks.values()].find((item) => item.draftPath === input.storyPath)!;
      const id = crypto.randomUUID();
      const storyPath = `data/stories/edited-${id}.json`;
      const result = { ...base, ...structuredClone(input), storyPath, sourceHash: id, version: base.version + 1 };
      documents.set(storyPath, result);
      tasks.set(id, { ...task, id, draftPath: storyPath, updatedAt: Date.now() });
      return structuredClone(result);
    },
    suggestGraph: async () => {
      throw new Error(translateRuntimeMessage("plat.preview.story.suggestRequiresBackend"));
    },
    list: async () => {
      if (activeStoryPath && getChat().story) saves.set(activeStoryPath, getChat());
      return [...tasks.values()]
        .filter((task) => task.status === "succeeded")
        .map((task) => {
          const save = saves.get(task.draftPath);
          return {
            id: task.id,
            title: documentFor(task.draftPath).title,
            version: documentFor(task.draftPath).version,
            storyPath: task.draftPath,
            canEditGraph: true,
            characters: (task.options.characters as string[]) ?? [],
            backgrounds: [String(task.options.backgroundName || TRANSPARENT_BACKGROUND_NAME)],
            historyPath: save?.historyPath || "",
            currentNodeTitle: save?.story?.currentNodeTitle || "",
            updatedAt: task.updatedAt,
          };
        });
    },
    prepareLaunch: async (storyPath, historyPath = "") => {
      const task = [...tasks.values()].find((item) => item.draftPath === storyPath);
      if (!task) throw new Error(translateRuntimeMessage("plat.preview.story.notFound"));
      const title = documentFor(storyPath).title;
      return {
        templateId: "",
        storyPath,
        templateName: title,
        scenario: translateRuntimeMessage("plat.preview.story.launchScenario", { title }),
        system: translateRuntimeMessage("plat.preview.story.launchSystem"),
        characters: (task.options.characters as string[]) ?? [],
        backgroundName: String(task.options.backgroundName || TRANSPARENT_BACKGROUND_NAME),
        characterPromptMode: task.options.characterPromptMode === "compact" ? "compact" : "full",
        primaryCharacters: (task.options.primaryCharacters as string[]) ?? [],
        historyPath,
        resetHistory: !historyPath,
      };
    },
    getGeneration: async (id) => read(id),
    getPreview: async (id) => {
      read(id);
      return structuredClone(previewStoryGraph);
    },
    cancelGeneration: async (id) => finish({ ...read(id), status: "cancelled", cancelRequested: true }),
    regenerateGeneration: async (id, _stage, options) => finish({ ...read(id), updatedAt: Date.now() }, options),
    resumeGeneration: async (id, options) =>
      finish({ ...read(id), status: "succeeded", cancelRequested: false }, options),
    startGeneration: async (input, options) =>
      finish(
        {
          ...previewStoryGeneration(`story-preview-${Date.now()}`, "succeeded"),
          synopsis: input.synopsis,
          options: input.options ?? {},
          resourceCatalog: input.resourceCatalog ?? {},
        },
        options,
      ),
    startSession: async (storyPath) => {
      const document = documentFor(storyPath);
      const opening = document.graph.nodes.find((node) => node.id === document.graph.startNodeId)!;
      activeStoryPath = storyPath;
      const saved = saves.get(storyPath);
      if (saved && saved.historyPath === getChat().historyPath) {
        const recovered = { ...getChat(), story: saved.story, historyEntries: saved.historyEntries };
        setChat(recovered);
        return recovered;
      }
      const snapshot = {
        ...getChat(),
        story: {
          activeCast: [],
          castRevision: 0,
          currentNodeId: opening.id,
          currentNodeTitle: opening.title,
          currentNodeType: opening.type,
          maxRounds: opening.maxRounds,
          nodeTurnCount: 0,
          objectives: [],
          options: [],
          revision: 1,
          storyId: "preview-story",
          storyVersion: document.version,
          unlockedNotifications: [],
          visibleVariables: [],
        },
      };
      setChat(snapshot);
      saves.set(storyPath, snapshot);
      return snapshot;
    },
  };
}
