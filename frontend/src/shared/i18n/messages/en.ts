import type { MessageKey } from "../messages";
import { agentEnMessages } from "./en/agent";
import { characterEnMessages } from "./en/character";
import { chatEnMessages } from "./en/chat";
import { knowledgeEnMessages } from "./en/knowledge";
import { onboardingEnMessages } from "./en/onboarding";
import { operationsEnMessages } from "./en/operations";
import { perceptionEnMessages } from "./en/perception";
import { platformEnMessages } from "./en/platform";
import { pluginsEnMessages } from "./en/plugins";
import { relationEnMessages } from "./en/relation";
import { settingsEnMessages } from "./en/settings";
import { shellEnMessages } from "./en/shell";
import { spritesEnMessages } from "./en/sprites";
import { novelEnMessages } from "./en/novel";
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
  novel: novelEnMessages,
  story: storyEnMessages,
  knowledge: knowledgeEnMessages,
  agent: agentEnMessages,
  plugins: pluginsEnMessages,
  workspace: workspaceEnMessages,
  onboarding: onboardingEnMessages,
  operations: operationsEnMessages,
  platform: platformEnMessages,
};

export const enMessages: Record<MessageKey, string> = {
  ...shellEnMessages,
  ...settingsEnMessages,
  ...chatEnMessages,
  ...perceptionEnMessages,
  ...characterEnMessages,
  ...relationEnMessages,
  ...spritesEnMessages,
  ...novelEnMessages,
  ...storyEnMessages,
  ...knowledgeEnMessages,
  ...agentEnMessages,
  ...pluginsEnMessages,
  ...workspaceEnMessages,
  ...onboardingEnMessages,
  ...operationsEnMessages,
  ...platformEnMessages,
};
