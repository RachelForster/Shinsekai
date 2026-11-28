import { agentZhCNMessages } from "./zh_CN/agent";
import { characterZhCNMessages } from "./zh_CN/character";
import { chatZhCNMessages } from "./zh_CN/chat";
import { knowledgeZhCNMessages } from "./zh_CN/knowledge";
import { onboardingZhCNMessages } from "./zh_CN/onboarding";
import { operationsZhCNMessages } from "./zh_CN/operations";
import { perceptionZhCNMessages } from "./zh_CN/perception";
import { platformZhCNMessages } from "./zh_CN/platform";
import { pluginsZhCNMessages } from "./zh_CN/plugins";
import { relationZhCNMessages } from "./zh_CN/relation";
import { settingsZhCNMessages } from "./zh_CN/settings";
import { shellZhCNMessages } from "./zh_CN/shell";
import { spritesZhCNMessages } from "./zh_CN/sprites";
import { novelZhCNMessages } from "./zh_CN/novel";
import { storyZhCNMessages } from "./zh_CN/story";
import { workspaceZhCNMessages } from "./zh_CN/workspace";

export const zhCNMessageSlices = {
  shell: shellZhCNMessages,
  settings: settingsZhCNMessages,
  chat: chatZhCNMessages,
  perception: perceptionZhCNMessages,
  character: characterZhCNMessages,
  relation: relationZhCNMessages,
  sprites: spritesZhCNMessages,
  novel: novelZhCNMessages,
  story: storyZhCNMessages,
  knowledge: knowledgeZhCNMessages,
  agent: agentZhCNMessages,
  plugins: pluginsZhCNMessages,
  workspace: workspaceZhCNMessages,
  onboarding: onboardingZhCNMessages,
  operations: operationsZhCNMessages,
  platform: platformZhCNMessages,
};

type DuplicateSliceKeys<Slices extends Record<string, Record<string, string>>> = {
  [A in keyof Slices]: {
    [B in Exclude<keyof Slices, A>]: keyof Slices[A] & keyof Slices[B];
  }[Exclude<keyof Slices, A>];
}[keyof Slices];

type AssertTrue<T extends true> = T;

export type NoDuplicateMessageSliceKeys = AssertTrue<
  [DuplicateSliceKeys<typeof zhCNMessageSlices>] extends [never] ? true : false
>;

export const zhCNMessages = {
  ...shellZhCNMessages,
  ...settingsZhCNMessages,
  ...chatZhCNMessages,
  ...perceptionZhCNMessages,
  ...characterZhCNMessages,
  ...relationZhCNMessages,
  ...spritesZhCNMessages,
  ...novelZhCNMessages,
  ...storyZhCNMessages,
  ...knowledgeZhCNMessages,
  ...agentZhCNMessages,
  ...pluginsZhCNMessages,
  ...workspaceZhCNMessages,
  ...onboardingZhCNMessages,
  ...operationsZhCNMessages,
  ...platformZhCNMessages,
};
