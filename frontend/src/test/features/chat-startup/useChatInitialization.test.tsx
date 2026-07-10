import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useChatInitialization } from "../../../features/chat-startup/useChatInitialization";
import type { ChatSnapshot, TaskProgressOptions } from "../../../shared/platform/types";

const snapshot: ChatSnapshot = {
  dialogText: "Ready",
  historyPath: "data/chat_history/default.json",
  inputDraft: "",
  options: [],
  sprites: [],
  status: "idle",
};

describe("useChatInitialization", () => {
  it("opens immediately, publishes task updates, and closes after success", async () => {
    let resolveOperation!: (value: ChatSnapshot) => void;
    const operation = vi.fn((options: TaskProgressOptions<ChatSnapshot>) => {
      options.onTaskUpdate?.({
        createdAt: 1,
        id: "chat-init-1",
        kind: "chat-initialization",
        logs: [],
        message: "Loading memory",
        phase: "memory",
        progress: 0.6,
        result: null,
        status: "running",
        title: "Initialize chat",
        updatedAt: 2,
      });
      return new Promise<ChatSnapshot>((resolve) => {
        resolveOperation = resolve;
      });
    });
    const { result } = renderHook(() => useChatInitialization());
    let initializationPromise!: Promise<ChatSnapshot>;

    act(() => {
      initializationPromise = result.current.runChatInitialization(operation);
    });

    expect(result.current.initializationOpen).toBe(true);
    expect(result.current.initializationPending).toBe(true);
    expect(result.current.initializationTask).toMatchObject({ phase: "memory", progress: 0.6 });

    act(() => result.current.closeInitialization());
    expect(result.current.initializationOpen).toBe(true);

    await act(async () => {
      resolveOperation(snapshot);
      await expect(initializationPromise).resolves.toBe(snapshot);
    });

    expect(result.current.initializationOpen).toBe(false);
    expect(result.current.initializationPending).toBe(false);
    expect(result.current.initializationError).toBeNull();
  });

  it("keeps the dialog open with the failure until it is dismissed", async () => {
    const { result } = renderHook(() => useChatInitialization());

    await act(async () => {
      await expect(
        result.current.runChatInitialization(async () => {
          throw new Error("TTS server did not start");
        }),
      ).rejects.toThrow("TTS server did not start");
    });

    expect(result.current.initializationOpen).toBe(true);
    expect(result.current.initializationPending).toBe(false);
    expect(result.current.initializationError).toBe("TTS server did not start");

    act(() => result.current.closeInitialization());
    expect(result.current.initializationOpen).toBe(false);
  });
});
