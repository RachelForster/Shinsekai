import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  sendChatCommand: vi.fn(),
}));

vi.mock("../../../entities/chat/repository", () => ({
  sendChatCommand: (...args: unknown[]) => mocks.sendChatCommand(...args),
}));

import { buildChatStageViewModel, emptyChatState, type ChatStageState } from "../../../features/chat-stage/chatState";
import { useChatStageComposerController } from "../../../features/chat-stage/controllers/useChatStageComposerController";
import type { ChatOption } from "../../../shared/platform/types";

function createOptions(overrides?: Partial<Parameters<typeof useChatStageComposerController>[0]>) {
  const state: ChatStageState = {
    ...emptyChatState,
    sessionId: "session-1",
    ...(overrides?.state ?? {}),
  };
  return {
    activeReplay: null,
    dispatch: vi.fn(),
    hasPendingUploads: () => false,
    modalOpen: false,
    sendCommand: vi.fn().mockResolvedValue(undefined),
    showDialogImmediately: vi.fn(),
    showToast: vi.fn(),
    state,
    t: (key: string) => key,
    typingDialog: false,
    viewModel: buildChatStageViewModel(state),
    ...overrides,
  };
}

describe("useChatStageComposerController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.sendChatCommand.mockResolvedValue(emptyChatState);
  });

  it("submits drafts and attachments while guarding blocked, pending, or replay states", async () => {
    const blockedOptions = createOptions({
      state: {
        ...emptyChatState,
        behavior: {
          behaviorId: "theater",
          stagePolicy: {
            allowFreeTextInterject: false,
            allowUnboundSpeakers: false,
            hideInputLayer: false,
            playbackEndAction: "idle",
          },
          stateVersion: 1,
        },
        inputDraft: "blocked",
      },
    });
    const blockedHook = renderHook(() => useChatStageComposerController(blockedOptions));
    await act(async () => {
      await blockedHook.result.current.submit();
    });
    expect(blockedOptions.sendCommand).not.toHaveBeenCalled();

    const pendingOptions = createOptions({
      hasPendingUploads: () => true,
      state: { ...emptyChatState, inputDraft: "waiting" },
    });
    const pendingHook = renderHook(() => useChatStageComposerController(pendingOptions));
    await act(async () => {
      await pendingHook.result.current.submit();
    });
    expect(pendingOptions.sendCommand).not.toHaveBeenCalled();

    const attachment = { kind: "image" as const, name: "cg.png", path: "/tmp/cg.png" };
    const activeOptions = createOptions({
      state: { ...emptyChatState, inputAttachments: [attachment], inputDraft: "Look at this" },
    });
    const { result } = renderHook(() => useChatStageComposerController(activeOptions));

    act(() => result.current.setDraft("next draft"));
    expect(activeOptions.dispatch).toHaveBeenCalledWith({ text: "next draft", type: "setDraft" });

    await act(async () => {
      await result.current.submit();
    });

    expect(activeOptions.showDialogImmediately).toHaveBeenCalledTimes(1);
    expect(result.current.recentInputs).toEqual(["Look at this"]);
    expect(activeOptions.dispatch).toHaveBeenCalledWith({
      queued: activeOptions.state.turnOptions.batchEnabled,
      source: "send-message",
      text: "Look at this\n[image: cg.png]",
      type: "submitUserMessage",
    });
    expect(activeOptions.sendCommand).toHaveBeenCalledWith({
      payload: { attachments: [attachment], text: "Look at this" },
      type: "send-message",
    });
  });

  it("submits behavior, story, and string options while ignoring disabled choices", () => {
    const options = createOptions();
    const { result } = renderHook(() => useChatStageComposerController(options));

    const disabledStoryOption: ChatOption = {
      enabled: false,
      expectedNodeId: "node-1",
      expectedRevision: 2,
      id: "choice-disabled",
      label: "Locked",
      source: "story",
    };
    act(() => result.current.submitOption(disabledStoryOption));
    expect(options.sendCommand).not.toHaveBeenCalled();

    const storyOption: ChatOption = {
      enabled: true,
      expectedNodeId: "node-1",
      expectedRevision: 2,
      id: "choice-1",
      label: "Open door",
      source: "story",
    };
    act(() => result.current.submitOption(storyOption));
    expect(options.dispatch).toHaveBeenCalledWith({
      queued: options.state.turnOptions.batchEnabled,
      source: "submit-option",
      text: "Open door",
      type: "submitUserMessage",
    });
    expect(options.sendCommand).toHaveBeenCalledWith({
      payload: {
        choiceId: "choice-1",
        expectedNodeId: "node-1",
        expectedRevision: 2,
        kind: "story-choice",
      },
      type: "submit-option",
    });

    const behaviorOption: ChatOption = {
      action: "choose",
      enabled: true,
      expectedStateVersion: 5,
      id: "opt-a",
      kind: "behavior-option",
      label: "Continue",
    };
    act(() => result.current.submitOption(behaviorOption));
    expect(options.sendCommand).toHaveBeenCalledWith({
      payload: expect.objectContaining({
        action: "choose",
        expectedStateVersion: 5,
        payload: { optionId: "opt-a" },
      }),
      type: "behavior-command",
    });
  });

  it("resolves tool confirmation, rolls back failed turn options updates, and reports input activity", async () => {
    mocks.sendChatCommand.mockRejectedValueOnce(new Error("save failed"));
    const options = createOptions({
      state: {
        ...emptyChatState,
        toolConfirmation: {
          confirmationId: "confirm-9",
          risk: "medium",
          toolName: "run_script",
        },
      },
    });
    const { result } = renderHook(() => useChatStageComposerController(options));

    act(() => result.current.resolveToolConfirmation("confirm"));
    expect(options.sendCommand).toHaveBeenCalledWith({
      payload: {
        action: "confirm",
        confirmationId: "confirm-9",
        kind: "tool-confirmation",
      },
      type: "submit-option",
    });

    const nextTurnOptions = { ...options.state.turnOptions, batchEnabled: true };
    await act(async () => {
      result.current.updateTurnOptions(nextTurnOptions);
      await Promise.resolve();
    });

    expect(options.dispatch).toHaveBeenNthCalledWith(1, { options: nextTurnOptions, type: "setTurnOptions" });
    expect(options.dispatch).toHaveBeenNthCalledWith(2, { options: options.state.turnOptions, type: "setTurnOptions" });
    expect(options.showToast).toHaveBeenCalledWith({
      kind: "error",
      message: "save failed",
      title: "common.operationFailed",
    });

    mocks.sendChatCommand.mockRejectedValueOnce(new Error("ignored"));
    act(() => result.current.updateInputActivity({ composing: false, hasText: true }));
    expect(mocks.sendChatCommand).toHaveBeenLastCalledWith({
      payload: { composing: false, hasText: true },
      type: "chat-input-state",
    });
  });
});
