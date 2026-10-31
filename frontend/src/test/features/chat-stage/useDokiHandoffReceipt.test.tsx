import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useDokiHandoffReceipt } from "../../../features/chat-stage/hooks/useDokiHandoffReceipt";
const mocks = vi.hoisted(() => ({ ack: vi.fn() }));
vi.mock("../../../shared/platform/platform", () => ({ getPlatform: () => ({ chat: { ackDokiHandoff: mocks.ack } }) }));
afterEach(() => {
  vi.useRealTimers();
  vi.resetAllMocks();
});
it("acknowledges only connected renderers and stops the heartbeat on disconnect", async () => {
  vi.useFakeTimers();
  mocks.ack.mockResolvedValue({ doki: true, status: "entered" });
  const { rerender, unmount } = renderHook(({ connected }) => useDokiHandoffReceipt("history", "session", connected), {
    initialProps: { connected: false },
  });
  expect(mocks.ack).not.toHaveBeenCalled();
  rerender({ connected: true });
  expect(mocks.ack).toHaveBeenCalledWith({ historyPath: "history", sessionId: "session" });
  await act(async () => {
    vi.advanceTimersByTime(5000);
  });
  expect(mocks.ack).toHaveBeenCalledTimes(2);
  rerender({ connected: false });
  await act(async () => {
    vi.advanceTimersByTime(10000);
  });
  expect(mocks.ack).toHaveBeenCalledTimes(2);
  unmount();
});
it("does not invent an entered receipt when the session identity is missing", () => {
  renderHook(() => useDokiHandoffReceipt("history", "", true));
  expect(mocks.ack).not.toHaveBeenCalled();
});
