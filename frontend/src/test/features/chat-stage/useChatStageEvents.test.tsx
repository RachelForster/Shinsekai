import { useReducer } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useChatStageEvents } from "../../../features/chat-stage/hooks/useChatStageEvents";
import { chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";
import { resetPlatformForModeSwitch } from "../../../shared/platform/platform";
import type { ChatSnapshot, ChatStageEvent } from "../../../shared/platform/types";

const mocks = vi.hoisted(() => ({ snapshot: vi.fn(), subscribe: vi.fn() }));
vi.mock("../../../entities/chat/repository", () => ({
  getChatSnapshot: mocks.snapshot,
  subscribeChatEvents: mocks.subscribe,
}));

it("replaces the subscription and rejects late events and hydration from the old session", async () => {
  let resolveOld!: (snapshot: ChatSnapshot) => void;
  mocks.snapshot.mockReturnValueOnce(
    new Promise<ChatSnapshot>((resolve) => {
      resolveOld = resolve;
    }),
  );
  const replacement = { ...emptyChatState, effectImage: null, sessionId: "new", eventSeq: 1 };
  mocks.snapshot.mockResolvedValue(replacement);
  const listeners: Array<(event: ChatStageEvent) => void> = [];
  const stops: Array<ReturnType<typeof vi.fn>> = [];
  mocks.subscribe.mockImplementation((callback) => {
    listeners.push(callback);
    const stop = vi.fn();
    stops.push(stop);
    return stop;
  });
  const queue = vi.fn();
  const { result } = renderHook(() => {
    const [state, dispatch] = useReducer(chatStageReducer, { ...emptyChatState, sessionId: "old", eventSeq: 100 });
    const events = useChatStageEvents({
      dispatch,
      eventSeq: state.eventSeq,
      sessionId: state.sessionId,
      loadFallbackMessage: "failed",
      queueAnimatedDialog: queue,
    });
    return { state, ...events };
  });
  act(() => result.current.replaceSession(replacement));
  expect(stops[0]).toHaveBeenCalledOnce();
  await waitFor(() => expect(listeners).toHaveLength(2));
  await act(async () => {
    listeners[0]({ type: "notification.change", seq: 999, ts: 0, v: 1, text: "stale" });
    resolveOld({ ...emptyChatState, effectImage: null, sessionId: "old", eventSeq: 1000 });
  });
  expect(result.current.state.sessionId).toBe("new");
  act(() => listeners[1]({ type: "notification.change", seq: 2, ts: 0, v: 1, text: "new reply" }));
  expect(result.current.state.notificationText).toBe("new reply");
  expect(result.current.state.eventSeq).toBe(2);
});

it("rebinds chat snapshot and event subscription when runtime platform mode switches", async () => {
  mocks.snapshot.mockReset();
  mocks.subscribe.mockReset();

  let activeSnapshot: ChatSnapshot = {
    ...emptyChatState,
    effectImage: null,
    sessionId: "standalone-s1",
    eventSeq: 50,
  };
  mocks.snapshot.mockImplementation(() => Promise.resolve(activeSnapshot));

  const listeners: Array<(event: ChatStageEvent) => void> = [];
  const stops: Array<ReturnType<typeof vi.fn>> = [];
  mocks.subscribe.mockImplementation((callback) => {
    listeners.push(callback);
    const stop = vi.fn();
    stops.push(stop);
    return stop;
  });

  const queue = vi.fn();
  const { result } = renderHook(() => {
    const [state, dispatch] = useReducer(chatStageReducer, emptyChatState);
    const events = useChatStageEvents({
      dispatch,
      eventSeq: state.eventSeq,
      sessionId: state.sessionId,
      loadFallbackMessage: "failed",
      queueAnimatedDialog: queue,
    });
    return { state, ...events };
  });

  await waitFor(() => expect(result.current.state.sessionId).toBe("standalone-s1"));
  const standaloneCount = listeners.length;
  const activeStandaloneListener = listeners[standaloneCount - 1];
  act(() => activeStandaloneListener({ type: "notification.change", seq: 80, ts: 0, v: 1, text: "standalone" }));
  expect(result.current.state.eventSeq).toBe(80);

  activeSnapshot = {
    ...emptyChatState,
    effectImage: null,
    sessionId: "remote-s1",
    eventSeq: 2,
  };
  await act(async () => {
    resetPlatformForModeSwitch();
  });

  expect(stops[standaloneCount - 1]).toHaveBeenCalledOnce();
  await waitFor(() => expect(listeners.length).toBeGreaterThan(standaloneCount));
  await waitFor(() => expect(result.current.state.sessionId).toBe("remote-s1"));

  act(() =>
    activeStandaloneListener({ type: "notification.change", seq: 99, ts: 0, v: 1, text: "stale-old-platform" }),
  );
  expect(result.current.state.notificationText).not.toBe("stale-old-platform");

  const activeRemoteListener = listeners[listeners.length - 1];
  act(() => activeRemoteListener({ type: "notification.change", seq: 3, ts: 0, v: 1, text: "remote-pc-ready" }));
  expect(result.current.state.notificationText).toBe("remote-pc-ready");
  expect(result.current.state.eventSeq).toBe(3);
});
