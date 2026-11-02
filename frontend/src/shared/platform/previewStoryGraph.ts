import type { StoryGenerationPreview } from "./storyPreviewTypes";

export const previewStoryGraph: StoryGenerationPreview = {
  title: "旧校舍的来信",
  artifacts: {
    foundation: {
      title: "旧校舍的来信",
      premise: "一封旧信让你和同伴再次来到废弃校舍。",
      themes: ["信任", "记忆"],
      secrets: ["寄信人其实一直在身边。"],
    },
    characters: { characters: [{ name: "绫", responsibility: "陪伴玩家调查，逐渐说出往事" }] },
    narrative: { startNodeId: "opening", nodes: [] },
  },
  graph: {
    startNodeId: "opening",
    nodes: [
      {
        id: "opening",
        title: "校门前的邀约",
        type: "limited_turn_node",
        instruction: "绫展示一封旧信，邀请玩家进入校舍。",
        maxRounds: 3,
        transitions: [
          { to: "clue", when: "玩家愿意进入" },
          { to: "leave-ending", when: "玩家决定离开" },
        ],
        defaultTo: "clue",
      },
      {
        id: "clue",
        title: "寻找旧日线索",
        type: "free_chat_node",
        instruction: "在旧教室自由调查，讨论信中的秘密。",
        transitions: [
          { to: "truth-ending", when: "玩家发现寄信人的身份" },
          { to: "opening", when: "玩家想回到校门" },
        ],
      },
      { id: "truth-ending", title: "重逢的约定", type: "ending_node" },
      { id: "leave-ending", title: "未拆开的信", type: "ending_node" },
    ],
  },
};
previewStoryGraph.artifacts.narrative = { ...previewStoryGraph.graph };
