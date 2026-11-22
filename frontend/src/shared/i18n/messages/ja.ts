import type { MessageKey } from "../messages";
import { agentJaMessages } from "./ja/agent";
import { characterJaMessages } from "./ja/character";
import { chatJaMessages } from "./ja/chat";
import { knowledgeJaMessages } from "./ja/knowledge";
import { perceptionJaMessages } from "./ja/perception";
import { pluginsJaMessages } from "./ja/plugins";
import { relationJaMessages } from "./ja/relation";
import { settingsJaMessages } from "./ja/settings";
import { shellJaMessages } from "./ja/shell";
import { spritesJaMessages } from "./ja/sprites";
import { storyJaMessages } from "./ja/story";
import { workspaceJaMessages } from "./ja/workspace";

export const jaMessageSlices = {
  shell: shellJaMessages,
  settings: settingsJaMessages,
  chat: chatJaMessages,
  perception: perceptionJaMessages,
  character: characterJaMessages,
  relation: relationJaMessages,
  sprites: spritesJaMessages,
  story: storyJaMessages,
  knowledge: knowledgeJaMessages,
  agent: agentJaMessages,
  plugins: pluginsJaMessages,
  workspace: workspaceJaMessages,
};

export const jaMessages: Record<MessageKey, string> = {
  ...shellJaMessages,
  ...settingsJaMessages,
  ...chatJaMessages,
  ...perceptionJaMessages,
  ...characterJaMessages,
  ...relationJaMessages,
  ...spritesJaMessages,
  ...storyJaMessages,
  ...knowledgeJaMessages,
  ...agentJaMessages,
  ...pluginsJaMessages,
  ...workspaceJaMessages,
};
