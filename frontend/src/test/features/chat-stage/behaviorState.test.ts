import { describe, expect, it } from "vitest";

import { buildChatStageViewModel, chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";

describe("behaviorState plumbing", () => {
  it("hydrates snapshot behavior state and hides InputLayer when hideInputLayer is true", () => {
    const state = chatStageReducer(emptyChatState, {
      type: "hydrate",
      snapshot: {
        ...emptyChatState,
        effectImage: null,
        eventSeq: 1,
        behavior: {
          behaviorId: "novel_theater",
          stateVersion: 3,
          stagePolicy: {
            hideInputLayer: true,
            playbackEndAction: "auto_advance",
            allowFreeTextInterject: true,
            allowUnboundSpeakers: true,
          },
          hud: { chapterTitle: "Chapter 1" },
          options: [{ id: "opt-1", label: "Continue", action: "advance" }],
        },
      },
    });

    expect(state.layers.input).toBe(false);
    const vm = buildChatStageViewModel(state);
    expect(vm.layers.input).toBe(false);
    expect(vm.behavior?.behaviorId).toBe("novel_theater");
    expect(vm.behavior?.stateVersion).toBe(3);
  });

  it("applies behavior.state.replace events and restores input when cleared", () => {
    const hiddenState = chatStageReducer(emptyChatState, {
      type: "event",
      event: {
        type: "behavior.state.replace",
        seq: 2,
        ts: 10,
        v: 1,
        behavior: {
          behaviorId: "novel_theater",
          stateVersion: 4,
          stagePolicy: {
            hideInputLayer: true,
            playbackEndAction: "show_options",
            allowFreeTextInterject: false,
            allowUnboundSpeakers: true,
          },
        },
      },
    });
    expect(hiddenState.layers.input).toBe(false);

    const clearedState = chatStageReducer(hiddenState, {
      type: "event",
      event: {
        type: "behavior.state.replace",
        seq: 3,
        ts: 20,
        v: 1,
        behavior: null,
      },
    });
    expect(clearedState.layers.input).toBe(true);
    expect(buildChatStageViewModel(clearedState).layers.input).toBe(true);
  });
});
