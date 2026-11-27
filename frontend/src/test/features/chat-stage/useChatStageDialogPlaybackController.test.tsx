import { useMemo, useReducer } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getChatSnapshot: vi.fn(),
  subscribeChatEvents: vi.fn(),
}));

vi.mock("../../../entities/chat/repository", () => ({
  getChatSnapshot: (...args: unknown[]) => mocks.getChatSnapshot(...args),
  subscribeChatEvents: (...args: unknown[]) => mocks.subscribeChatEvents(...args),
}));

import {
  buildChatStageViewModel,
  chatStageReducer,
  emptyChatState,
  type ChatStageState,
} from "../../../features/chat-stage/chatState";
import { useChatStageDialogPlaybackController } from "../../../features/chat-stage/controllers/useChatStageDialogPlaybackController";
import type { ChatStageEvent } from "../../../shared/platform/types";

describe("useChatStageDialogPlaybackController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("finishes typing on first advanceDialog, then dispatches dialog-advance or behavior auto_advance", async () => {
    const listeners: Array<(event: ChatStageEvent) => void> = [];
    const initialSnapshot = {
      ...emptyChatState,
      characterName: "Mio",
      dialogHtml: "<p>Initial line</p>",
      dialogText: "Initial line",
      effectImage: null,
      eventSeq: 1,
      layers: { ...emptyChatState.layers, dialog: true },
      sessionId: "session-1",
    };
    mocks.getChatSnapshot.mockResolvedValue(initialSnapshot);
    mocks.subscribeChatEvents.mockImplementation((callback: (event: ChatStageEvent) => void) => {
      listeners.push(callback);
      return () => undefined;
    });

    const sendCommand = vi.fn().mockResolvedValue(undefined);
    const exitCg = vi.fn();
    const toggleAuto = vi.fn();

    const { result } = renderHook(() => {
      const [state, dispatch] = useReducer(chatStageReducer, {
        ...emptyChatState,
        effectImage: null,
        eventSeq: 1,
        sessionId: "session-1",
      } as ChatStageState);
      const viewModel = useMemo(() => buildChatStageViewModel(state), [state]);
      const controller = useChatStageDialogPlaybackController({
        activeReplay: null,
        auto: false,
        dialogTextDirection: "ltr",
        dispatch,
        exitCg,
        historyDialogOpen: false,
        longPressTalk: false,
        miniAvatarActive: false,
        modalOpen: false,
        sendCommand,
        state,
        t: (key) => key,
        toggleAuto,
        typewriterCps: 20,
        viewModel,
      });
      return { controller, state };
    });

    await waitFor(() => expect(result.current.state.dialogText).toBe("Initial line"));
    expect(listeners).toHaveLength(1);

    act(() => {
      listeners[0]!({
        animate: true,
        color: "#ffffff",
        fullHtml: "<p>Animated reply line</p>",
        isSystem: false,
        seq: 2,
        speaker: "Mio",
        ts: 100,
        type: "dialog.end",
        v: 1,
      });
    });

    expect(result.current.controller.typingDialog).toBe(true);

    act(() => result.current.controller.advanceDialog());
    expect(result.current.controller.typingDialog).toBe(false);
    expect(sendCommand).not.toHaveBeenCalled();

    act(() => result.current.controller.advanceDialog());
    expect(sendCommand).toHaveBeenCalledWith({ type: "dialog-advance" });

    act(() => {
      listeners[0]!({
        behavior: {
          behaviorId: "novel-theater",
          stagePolicy: {
            allowFreeTextInterject: false,
            allowUnboundSpeakers: false,
            hideInputLayer: true,
            playbackEndAction: "auto_advance",
          },
          stateVersion: 4,
        },
        seq: 3,
        ts: 200,
        type: "behavior.state.replace",
        v: 1,
      });
    });

    act(() => result.current.controller.advanceDialog());
    expect(sendCommand).toHaveBeenLastCalledWith({
      payload: expect.objectContaining({
        action: "advance",
        expectedStateVersion: 4,
        payload: { trigger: "playback_end" },
      }),
      type: "behavior-command",
    });

    act(() => result.current.controller.handlePlaybackSignal({ playbackId: "pb-1", state: "finished" }));
    expect(sendCommand).toHaveBeenLastCalledWith({
      payload: { playbackId: "pb-1", state: "finished" },
      type: "audio-playback-signal",
    });
  });
});
