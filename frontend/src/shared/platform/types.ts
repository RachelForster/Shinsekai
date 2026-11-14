import type { AgentPlatform } from "./agentTypes";
import type { AvatarRuntimesPlatform, CharacterRelationPlatform, CharactersPlatform } from "./slices/characterTypes";
import type { ChatPlatform, StoryPlatform } from "./slices/chatTypes";
import type { ConfigPlatform, ModelAssetsPlatform, MusicCoverPlatform } from "./slices/configTypes";
import type { KnowledgePlatform } from "./slices/knowledgeTypes";
import type { PerceptionPlatform } from "./slices/perceptionTypes";
import type { McpPlatform, PluginsPlatform } from "./slices/pluginTypes";
import type { FilesPlatform, LogsPlatform, RuntimePlatform, TasksPlatform } from "./slices/taskTypes";
import type { BackgroundsPlatform, EffectsPlatform, TemplatesPlatform, ToolsPlatform } from "./slices/workspaceTypes";

export type * from "./slices/storyTypes";
export type * from "./slices/taskTypes";
export type * from "./slices/characterTypes";
export type * from "./slices/knowledgeTypes";
export type * from "./slices/perceptionTypes";
export type * from "./slices/pluginTypes";
export type * from "./slices/workspaceTypes";
export type * from "./slices/configTypes";
export type * from "./slices/chatTypes";

export interface ShinsekaiPlatform {
  agent: AgentPlatform;
  backgrounds: BackgroundsPlatform;
  effects: EffectsPlatform;
  chat: ChatPlatform;
  story: StoryPlatform;
  knowledge: KnowledgePlatform;
  characterRelation: CharacterRelationPlatform;
  characters: CharactersPlatform;
  config: ConfigPlatform;
  avatarRuntimes: AvatarRuntimesPlatform;
  modelAssets: ModelAssetsPlatform;
  files: FilesPlatform;
  logs: LogsPlatform;
  runtime: RuntimePlatform;
  musicCover: MusicCoverPlatform;
  plugins: PluginsPlatform;
  mcp: McpPlatform;
  perception: PerceptionPlatform;
  tasks: TasksPlatform;
  templates: TemplatesPlatform;
  tools: ToolsPlatform;
}
