import { createAgentPreviewPlatform } from "./agentPreviewPlatform";
import {
  createAvatarRuntimesPreviewPlatform,
  createCharacterRelationPreviewPlatform,
  createCharactersPreviewPlatform,
} from "./slices/characterPreviewPlatform";
import { createChatPreviewPlatform } from "./slices/chatPreviewPlatform";
import {
  createConfigPreviewPlatform,
  createModelAssetsPreviewPlatform,
  createMusicCoverPreviewPlatform,
  createRuntimePreviewPlatform,
} from "./slices/configPreviewPlatform";
import { createKnowledgePreviewPlatform } from "./slices/knowledgePreviewPlatform";
import { createPerceptionPreviewPlatform } from "./slices/perceptionPreviewPlatform";
import { createMcpPreviewPlatform, createPluginsPreviewPlatform } from "./slices/pluginPreviewPlatform";
import { clone, createBrowserPreviewContext } from "./slices/previewContext";
import {
  createBackgroundsPreviewPlatform,
  createEffectsPreviewPlatform,
  createFilesPreviewPlatform,
  createLogsPreviewPlatform,
  createTasksPreviewPlatform,
  createTemplatesPreviewPlatform,
  createToolsPreviewPlatform,
} from "./slices/workspacePreviewPlatform";
import { createStoryPreviewPlatform } from "./storyPreviewPlatform";
import type { ShinsekaiPlatform } from "./types";

export function createBrowserPreviewPlatform(): ShinsekaiPlatform {
  const ctx = createBrowserPreviewContext();

  return {
    agent: createAgentPreviewPlatform(),
    backgrounds: createBackgroundsPreviewPlatform(ctx),
    effects: createEffectsPreviewPlatform(ctx),
    chat: createChatPreviewPlatform(ctx),
    knowledge: createKnowledgePreviewPlatform(ctx),
    characters: createCharactersPreviewPlatform(ctx),
    characterRelation: createCharacterRelationPreviewPlatform(ctx),
    config: createConfigPreviewPlatform(ctx),
    avatarRuntimes: createAvatarRuntimesPreviewPlatform(),
    modelAssets: createModelAssetsPreviewPlatform(ctx),
    files: createFilesPreviewPlatform(ctx),
    logs: createLogsPreviewPlatform(),
    runtime: createRuntimePreviewPlatform(),
    musicCover: createMusicCoverPreviewPlatform(ctx),
    plugins: createPluginsPreviewPlatform(),
    mcp: createMcpPreviewPlatform(),
    tasks: createTasksPreviewPlatform(),
    perception: createPerceptionPreviewPlatform(ctx),
    story: createStoryPreviewPlatform(
      () => clone(ctx.getChat()),
      (snapshot) => {
        ctx.setChat(snapshot);
      },
      (storyPath) => {
        const chat = ctx.getChat();
        const selected = [...ctx.conversations].filter(([, item]) => item.summary.storyPath === storyPath);
        if (
          (chat.chatProcessRunning || chat.chatRuntimeClosing) &&
          selected.some(([, item]) => item.summary.historyPath === chat.historyPath)
        ) {
          throw new Error("请先关闭该剧本版本的聊天，再删除剧本及关联对话。");
        }
        for (const [id] of selected) ctx.conversations.delete(id);
      },
    ),
    templates: createTemplatesPreviewPlatform(ctx),
    tools: createToolsPreviewPlatform(),
  };
}
