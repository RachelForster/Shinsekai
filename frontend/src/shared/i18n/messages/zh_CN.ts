import { agentZhCNMessages } from "./zh_CN/agent";
import { characterZhCNMessages } from "./zh_CN/character";
import { chatZhCNMessages } from "./zh_CN/chat";
import { knowledgeZhCNMessages } from "./zh_CN/knowledge";
import { perceptionZhCNMessages } from "./zh_CN/perception";
import { pluginsZhCNMessages } from "./zh_CN/plugins";
import { relationZhCNMessages } from "./zh_CN/relation";
import { settingsZhCNMessages } from "./zh_CN/settings";
import { shellZhCNMessages } from "./zh_CN/shell";
import { spritesZhCNMessages } from "./zh_CN/sprites";
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
  story: storyZhCNMessages,
  knowledge: knowledgeZhCNMessages,
  agent: agentZhCNMessages,
  plugins: pluginsZhCNMessages,
  workspace: workspaceZhCNMessages,
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
  ...storyZhCNMessages,
  ...knowledgeZhCNMessages,
  ...agentZhCNMessages,
  ...pluginsZhCNMessages,
  ...workspaceZhCNMessages,
};
