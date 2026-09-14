import { useReducer } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useChatStageEvents } from "../../../features/chat-stage/hooks/useChatStageEvents";
import { chatStageReducer, emptyChatState } from "../../../features/chat-stage/chatState";
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
