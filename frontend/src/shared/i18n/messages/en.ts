import type { MessageKey } from "../messages";
import { agentEnMessages } from "./en/agent";
import { characterEnMessages } from "./en/character";
import { chatEnMessages } from "./en/chat";
import { knowledgeEnMessages } from "./en/knowledge";
import { perceptionEnMessages } from "./en/perception";
import { pluginsEnMessages } from "./en/plugins";
import { relationEnMessages } from "./en/relation";
import { settingsEnMessages } from "./en/settings";
import { shellEnMessages } from "./en/shell";
import { spritesEnMessages } from "./en/sprites";
import { storyEnMessages } from "./en/story";
import { workspaceEnMessages } from "./en/workspace";

export const enMessageSlices = {
  shell: shellEnMessages,
  settings: settingsEnMessages,
  chat: chatEnMessages,
  perception: perceptionEnMessages,
  character: characterEnMessages,
  relation: relationEnMessages,
  sprites: spritesEnMessages,
  story: storyEnMessages,
  knowledge: knowledgeEnMessages,
  agent: agentEnMessages,
  plugins: pluginsEnMessages,
  workspace: workspaceEnMessages,
};

export const enMessages: Record<MessageKey, string> = {
  ...shellEnMessages,
  ...settingsEnMessages,
  ...chatEnMessages,
  ...perceptionEnMessages,
  ...characterEnMessages,
  ...relationEnMessages,
  ...spritesEnMessages,
  ...storyEnMessages,
  ...knowledgeEnMessages,
  ...agentEnMessages,
  ...pluginsEnMessages,
  ...workspaceEnMessages,
};
