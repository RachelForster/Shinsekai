import { describe, expect, it } from "vitest";

import { buildChatStageViewModel, chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";
import {
  buildBehaviorAdvanceCommand,
  buildBehaviorOptionCommand,
  chatOptionKey,
  isBehaviorChoiceOption,
} from "../../../features/chat-stage/state/behaviorCommands";

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

  it("exposes behavior options when show_options settles and maps them to versioned commands", () => {
    const speakingState = chatStageReducer(emptyChatState, {
      type: "hydrate",
      snapshot: {
        ...emptyChatState,
        effectImage: null,
        eventSeq: 1,
        status: "speaking",
        dialogText: "Still talking...",
        characterName: "Alice",
        behavior: {
          behaviorId: "galgame_tutor",
          stateVersion: 7,
          stagePolicy: {
            hideInputLayer: false,
            playbackEndAction: "show_options",
            allowFreeTextInterject: false,
            allowUnboundSpeakers: true,
          },
          options: [
            { id: "opt-a", label: "Answer A", action: "answer", payload: { choice: "A" } },
            { id: "opt-b", label: "Answer B", action: "answer", payload: { choice: "B" } },
          ],
        },
      },
    });

    // While speaking, dialog remains visible and input is blocked by allowFreeTextInterject=false
    expect(speakingState.layers.input).toBe(false);
    expect(speakingState.layers.options).toBe(false);
    expect(buildChatStageViewModel(speakingState).inputDisabled).toBe(true);
    expect(buildChatStageViewModel(speakingState).options).toEqual([]);

    // Once idle, behavior options appear and map to versioned behavior-command payloads
    const idleState = chatStageReducer(speakingState, { status: "idle", type: "setStatus" });
    const idleVm = buildChatStageViewModel(idleState);
    expect(idleState.layers.options).toBe(true);
    expect(idleVm.options).toHaveLength(2);
    const first = idleVm.options[0];
    expect(isBehaviorChoiceOption(first)).toBe(true);
    expect(chatOptionKey(first)).toBe("behavior:7:opt-a");
    if (isBehaviorChoiceOption(first)) {
      const cmd = buildBehaviorOptionCommand(first);
      expect(cmd.commandId.length).toBeGreaterThan(0);
      expect(cmd.action).toBe("answer");
      expect(cmd.expectedStateVersion).toBe(7);
      expect(cmd.payload).toEqual({ choice: "A", optionId: "opt-a" });
    }
  });

  it("builds versioned advance commands only when playbackEndAction is auto_advance", () => {
    const autoCmd = buildBehaviorAdvanceCommand({
      behaviorId: "novel_theater",
      stateVersion: 9,
      stagePolicy: {
        hideInputLayer: true,
        playbackEndAction: "auto_advance",
        allowFreeTextInterject: true,
        allowUnboundSpeakers: true,
      },
    });
    expect(autoCmd).not.toBeNull();
    expect(autoCmd?.action).toBe("advance");
    expect(autoCmd?.expectedStateVersion).toBe(9);
    expect(autoCmd?.commandId.length).toBeGreaterThan(0);

    const idleCmd = buildBehaviorAdvanceCommand({
      behaviorId: "novel_theater",
      stateVersion: 9,
      stagePolicy: {
        hideInputLayer: true,
        playbackEndAction: "idle",
        allowFreeTextInterject: true,
        allowUnboundSpeakers: true,
      },
    });
    expect(idleCmd).toBeNull();
  });
});
