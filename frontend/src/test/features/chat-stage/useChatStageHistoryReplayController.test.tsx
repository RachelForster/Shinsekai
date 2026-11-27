import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getChatHistoryVoice: vi.fn(),
  getChatReplay: vi.fn(),
  saveCgAsset: vi.fn(),
  saveHistoryExport: vi.fn(),
  useReplayCapture: vi.fn((..._args: unknown[]) => false),
}));

vi.mock("../../../entities/chat/repository", () => ({
  getChatHistoryVoice: (...args: unknown[]) => mocks.getChatHistoryVoice(...args),
  getChatReplay: (...args: unknown[]) => mocks.getChatReplay(...args),
}));

vi.mock("../../../features/chat-stage/replay/historyExport", () => ({
  saveCgAsset: (...args: unknown[]) => mocks.saveCgAsset(...args),
  saveHistoryExport: (...args: unknown[]) => mocks.saveHistoryExport(...args),
}));

vi.mock("../../../features/chat-stage/replay/useReplayCapture", () => ({
  useReplayCapture: (...args: unknown[]) => mocks.useReplayCapture(...args),
}));

import { buildChatStageViewModel, emptyChatState, type ChatStageState } from "../../../features/chat-stage/chatState";
import { useChatStageHistoryReplayController } from "../../../features/chat-stage/controllers/useChatStageHistoryReplayController";
import type { ActiveReplay } from "../../../features/chat-stage/replay/ReplayControls";

function makeReplay(id: string, sessionId = "session-1"): ActiveReplay {
  return {
    generate: false,
    snapshot: {
      entries: [],
      id,
      sessionId,
      title: "Replay",
    } as unknown as ActiveReplay["snapshot"],
  };
}

function createBaseOptions(overrides?: Partial<Parameters<typeof useChatStageHistoryReplayController>[0]>) {
  const state: ChatStageState = {
    ...emptyChatState,
    sessionId: "session-1",
    ...(overrides?.state ?? {}),
  };
  return {
    dispatch: vi.fn(),
    refreshHistory: vi.fn().mockResolvedValue(undefined),
    sendCommand: vi.fn().mockResolvedValue(undefined),
    setAuto: vi.fn(),
    showToast: vi.fn(),
    state,
    t: (key: string) => key,
    viewModel: buildChatStageViewModel(state),
    ...overrides,
  };
}

describe("useChatStageHistoryReplayController", () => {
  const originalAudio = globalThis.Audio;
  const originalRevokeObjectUrl = URL.revokeObjectURL;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    globalThis.Audio = originalAudio;
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectUrl,
      writable: true,
    });
    vi.restoreAllMocks();
  });

  it("handles history dialog, replay start/exit, auto-fetch, and session invalidation", async () => {
    const replaySnapshot = makeReplay("replay-1");
    mocks.getChatReplay.mockResolvedValue(replaySnapshot);
    const options = createBaseOptions();

    const { result, rerender } = renderHook((props) => useChatStageHistoryReplayController(props), {
      initialProps: options,
    });

    act(() => result.current.openHistoryDialog());
    expect(result.current.historyDialogOpen).toBe(true);
    expect(options.refreshHistory).toHaveBeenCalledTimes(1);

    act(() => result.current.startReplay(replaySnapshot));
    expect(result.current.historyDialogOpen).toBe(false);
    expect(result.current.activeReplay).toEqual(replaySnapshot);
    expect(result.current.replaying).toBe(true);

    act(() => result.current.exitReplay(true));
    expect(result.current.activeReplay).toBeNull();
    expect(options.setAuto).toHaveBeenCalledWith(false);
    expect(result.current.historyDialogOpen).toBe(true);

    const stateWithReplay: ChatStageState = {
      ...options.state,
      replay: { id: "replay-1", index: 0, paused: false, ended: false } as ChatStageState["replay"],
    };
    rerender({ ...options, state: stateWithReplay, viewModel: buildChatStageViewModel(stateWithReplay) });

    await waitFor(() => expect(mocks.getChatReplay).toHaveBeenCalledWith("replay-1"));
    await waitFor(() => expect(result.current.activeReplay).toEqual(replaySnapshot));

    const closedState: ChatStageState = { ...stateWithReplay, sessionClosedReason: "closed" };
    rerender({ ...options, state: closedState, viewModel: buildChatStageViewModel(closedState) });

    await waitFor(() => expect(result.current.activeReplay).toBeNull());
    expect(result.current.historyDialogOpen).toBe(false);
  });

  it("replays voice segments sequentially, stops superseded audio, and toasts on failure", async () => {
    const audioInstances: Array<{
      onended: (() => void) | null;
      onerror: (() => void) | null;
      pause: ReturnType<typeof vi.fn>;
      play: ReturnType<typeof vi.fn>;
      src: string;
    }> = [];
    globalThis.Audio = vi.fn((src: string) => {
      const instance = {
        onended: null as (() => void) | null,
        onerror: null as (() => void) | null,
        pause: vi.fn(),
        play: vi.fn().mockResolvedValue(undefined),
        src,
      };
      audioInstances.push(instance);
      return instance as unknown as HTMLAudioElement;
    }) as unknown as typeof Audio;

    mocks.getChatHistoryVoice.mockResolvedValueOnce(["/v1.wav", "/v2.wav"]).mockResolvedValueOnce([]);
    const options = createBaseOptions();
    const { result } = renderHook(() => useChatStageHistoryReplayController(options));

    let playPromise!: Promise<void>;
    await act(async () => {
      playPromise = result.current.replayHistoryVoice("voice-1");
      await Promise.resolve();
    });

    await waitFor(() => expect(audioInstances).toHaveLength(1));
    expect(audioInstances[0]?.src).toBe("/v1.wav");

    await act(async () => {
      audioInstances[0]?.onended?.();
      await Promise.resolve();
    });
    await waitFor(() => expect(audioInstances).toHaveLength(2));
    expect(audioInstances[1]?.src).toBe("/v2.wav");

    await act(async () => {
      audioInstances[1]?.onended?.();
      await playPromise;
    });
    expect(options.showToast).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.replayHistoryVoice("empty-voice");
    });
    expect(options.showToast).toHaveBeenCalledWith({
      kind: "error",
      title: "chat.history.voiceExpired",
    });
  });

  it("exits CG, saves CG with duplicate protection, and confirms revert", async () => {
    let resolveSave!: (value: { name: string; path?: string }) => void;
    mocks.saveCgAsset.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSave = resolve;
        }),
    );

    const cgState: ChatStageState = { ...emptyChatState, cgPath: "https://example.com/cg.png", sessionId: "s1" };
    const options = createBaseOptions({ state: cgState });
    const { result } = renderHook(() => useChatStageHistoryReplayController(options));

    act(() => result.current.exitCg());
    expect(options.dispatch).toHaveBeenCalledWith({ type: "dismissCg" });
    expect(options.sendCommand).toHaveBeenCalledWith({ type: "dismiss-cg" });

    let firstSave!: Promise<void>;
    act(() => {
      firstSave = result.current.saveCg();
    });
    expect(result.current.savingCg).toBe(true);

    await act(async () => {
      await result.current.saveCg();
    });
    expect(mocks.saveCgAsset).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveSave({ name: "cg.png", path: "/saved/cg.png" });
      await firstSave;
    });
    expect(result.current.savingCg).toBe(false);
    expect(options.showToast).toHaveBeenCalledWith({
      kind: "success",
      message: "/saved/cg.png",
      title: "chat.cg.saved",
    });

    act(() => result.current.setConfirmRevertUserIndex(3));
    act(() => result.current.confirmRevertHistory());
    expect(result.current.confirmRevertUserIndex).toBeNull();
    expect(options.sendCommand).toHaveBeenCalledWith({ payload: 3, type: "revert-history" });

    expect(() => result.current.recordReplayAudio()).toThrow("Stage audio is unavailable");
  });

  it("revokes previous history export previewUrl when replaced or unmounted", async () => {
    const revokeSpy = vi.fn();
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeSpy,
      writable: true,
    });
    mocks.saveHistoryExport
      .mockResolvedValueOnce({ format: "png", name: "a.png", previewUrl: "blob:preview-1" })
      .mockResolvedValueOnce({ format: "png", name: "b.png", previewUrl: "blob:preview-2" });

    const options = createBaseOptions();
    const { result, unmount } = renderHook(() => useChatStageHistoryReplayController(options));

    await act(async () => {
      await result.current.exportHistory(new Blob(["1"]), "png");
    });
    expect(result.current.historyExport?.previewUrl).toBe("blob:preview-1");

    await act(async () => {
      await result.current.exportHistory(new Blob(["2"]), "png");
    });
    expect(revokeSpy).toHaveBeenCalledWith("blob:preview-1");

    unmount();
    expect(revokeSpy).toHaveBeenCalledWith("blob:preview-2");
  });
});
