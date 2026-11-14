import { createAgentHttpPlatform } from "./agentHttpPlatform";
import { createHttpTransport } from "./httpTransport";
import {
  createAvatarRuntimesHttpPlatform,
  createCharacterRelationHttpPlatform,
  createCharactersHttpPlatform,
} from "./slices/characterHttpPlatform";
import { createChatHttpPlatform, createStoryHttpPlatform } from "./slices/chatHttpPlatform";
import {
  createConfigHttpPlatform,
  createModelAssetsHttpPlatform,
  createMusicCoverHttpPlatform,
  createRuntimeHttpPlatform,
} from "./slices/configHttpPlatform";
import { createKnowledgeHttpPlatform } from "./slices/knowledgeHttpPlatform";
import { createPerceptionHttpPlatform } from "./slices/perceptionHttpPlatform";
import { createMcpHttpPlatform, createPluginsHttpPlatform } from "./slices/pluginHttpPlatform";
import {
  createBackgroundsHttpPlatform,
  createEffectsHttpPlatform,
  createFilesHttpPlatform,
  createLogsHttpPlatform,
  createTasksHttpPlatform,
  createTemplatesHttpPlatform,
  createToolsHttpPlatform,
} from "./slices/workspaceHttpPlatform";
import type { ShinsekaiPlatform } from "./types";

export function createHttpPlatform(baseUrl: string, authToken = ""): ShinsekaiPlatform {
  const transport = createHttpTransport(baseUrl, authToken);

  return {
    agent: createAgentHttpPlatform(transport.requestJson),
    backgrounds: createBackgroundsHttpPlatform(transport),
    effects: createEffectsHttpPlatform(transport),
    chat: createChatHttpPlatform(transport),
    story: createStoryHttpPlatform(transport),
    knowledge: createKnowledgeHttpPlatform(transport),
    characterRelation: createCharacterRelationHttpPlatform(transport),
    characters: createCharactersHttpPlatform(transport),
    config: createConfigHttpPlatform(transport),
    avatarRuntimes: createAvatarRuntimesHttpPlatform(transport),
    modelAssets: createModelAssetsHttpPlatform(transport),
    files: createFilesHttpPlatform(transport),
    logs: createLogsHttpPlatform(transport),
    runtime: createRuntimeHttpPlatform(transport),
    musicCover: createMusicCoverHttpPlatform(transport),
    plugins: createPluginsHttpPlatform(transport),
    mcp: createMcpHttpPlatform(transport),
    perception: createPerceptionHttpPlatform(transport),
    tasks: createTasksHttpPlatform(transport),
    templates: createTemplatesHttpPlatform(transport),
    tools: createToolsHttpPlatform(transport),
  };
}
