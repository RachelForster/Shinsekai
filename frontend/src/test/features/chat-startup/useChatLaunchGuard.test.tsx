import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { chatRuntimeStatusQueryKey } from "../../../entities/chat/repository";
import { closeChatRuntime } from "../../../features/chat-startup/runtimeState";
import { useChatLaunchGuard } from "../../../features/chat-startup/useChatLaunchGuard";
import type { ChatSnapshot } from "../../../shared/platform/types";

const mocks = vi.hoisted(() => ({
  closeChat: vi.fn(),
  getChatRuntimeStatus: vi.fn(),
}));

vi.mock("../../../entities/chat/repository", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../entities/chat/repository")>();
  return {
    ...actual,
    closeChat: mocks.closeChat,
    getChatRuntimeStatus: mocks.getChatRuntimeStatus,
  };
});

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }

  return { client, Wrapper };
}

describe("useChatLaunchGuard", () => {
  beforeEach(() => {
    mocks.closeChat.mockReset();
    mocks.getChatRuntimeStatus.mockReset();
    mocks.getChatRuntimeStatus.mockResolvedValue({
      chatProcessRunning: false,
      chatRuntimeClosing: false,
      state: "idle",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("queries once while idle and does not keep polling", async () => {
    vi.useFakeTimers();
    const { Wrapper } = createWrapper();
    renderHook(() => useChatLaunchGuard(), { wrapper: Wrapper });

    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(1);

    await act(() => vi.advanceTimersByTimeAsync(3_600));
    expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(1);
  });

  it("polls while the backend reports running", async () => {
    vi.useFakeTimers();
    mocks.getChatRuntimeStatus.mockResolvedValue({
      chatProcessRunning: true,
      chatRuntimeClosing: false,
      state: "running",
    });
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useChatLaunchGuard(), { wrapper: Wrapper });

    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(result.current.runtimeLaunchDisabled).toBe(true);

    await act(() => vi.advanceTimersByTimeAsync(1_200));
    expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(2);
  });

  it("stops polling after the runtime becomes idle", async () => {
    vi.useFakeTimers();
    mocks.getChatRuntimeStatus
      .mockResolvedValueOnce({
        chatProcessRunning: true,
        chatRuntimeClosing: false,
        state: "running",
      })
      .mockResolvedValue({
        chatProcessRunning: false,
        chatRuntimeClosing: false,
        state: "idle",
      });
    const { client, Wrapper } = createWrapper();
    const { result } = renderHook(() => useChatLaunchGuard(), { wrapper: Wrapper });

    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(result.current.runtimeLaunchDisabled).toBe(true);

    await act(() => vi.advanceTimersByTimeAsync(1_200));
    expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(2);
    expect(client.getQueryData(chatRuntimeStatusQueryKey)).toMatchObject({ state: "idle" });

    await act(() => vi.advanceTimersByTimeAsync(2_400));
    expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(2);
  });

  it("updates the lightweight cache from launch snapshots", async () => {
    const { client, Wrapper } = createWrapper();
    const { result } = renderHook(() => useChatLaunchGuard(), { wrapper: Wrapper });
    await waitFor(() => expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(1));

    await act(async () => {
      await result.current.updateRuntimeStatusFromSnapshot({
        chatProcessRunning: true,
        chatRuntimeClosing: true,
        dialogText: "",
        inputDraft: "",
        options: [],
        sprites: [],
        status: "idle",
      });
    });

    expect(client.getQueryData(chatRuntimeStatusQueryKey)).toEqual({
      chatProcessRunning: true,
      chatRuntimeClosing: true,
      state: "closing",
    });
    await waitFor(() => expect(result.current.runtimeLaunchDisabled).toBe(true));
  });

  it("starts polling after a launch snapshot reports running", async () => {
    vi.useFakeTimers();
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useChatLaunchGuard(), { wrapper: Wrapper });

    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.updateRuntimeStatusFromSnapshot({
        chatProcessRunning: true,
        chatRuntimeClosing: false,
        dialogText: "",
        inputDraft: "",
        options: [],
        sprites: [],
        status: "idle",
      });
    });

    await act(() => vi.advanceTimersByTimeAsync(1_200));
    expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(2);
  });

  it("does not let an older idle request overwrite a successful launch", async () => {
    let resolveInitialStatus: (value: {
      chatProcessRunning: boolean;
      chatRuntimeClosing: boolean;
      state: "idle";
    }) => void = () => undefined;
    mocks.getChatRuntimeStatus.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveInitialStatus = resolve;
      }),
    );
    const { client, Wrapper } = createWrapper();
    const { result } = renderHook(() => useChatLaunchGuard(), { wrapper: Wrapper });
    await waitFor(() => expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(1));

    await act(async () => {
      await result.current.updateRuntimeStatusFromSnapshot({
        chatProcessRunning: true,
        chatRuntimeClosing: false,
        dialogText: "",
        inputDraft: "",
        options: [],
        sprites: [],
        status: "idle",
      });
    });

    await act(async () => {
      resolveInitialStatus({
        chatProcessRunning: false,
        chatRuntimeClosing: false,
        state: "idle",
      });
      await Promise.resolve();
    });

    expect(client.getQueryData(chatRuntimeStatusQueryKey)).toMatchObject({ state: "running" });
    await waitFor(() => expect(result.current.runtimeLaunchDisabled).toBe(true));
  });

  it("disables launching while the feature-level close operation is running", async () => {
    let resolveClose: (snapshot: ChatSnapshot) => void = () => undefined;
    mocks.closeChat.mockReturnValue(
      new Promise<ChatSnapshot>((resolve) => {
        resolveClose = resolve;
      }),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useChatLaunchGuard(), { wrapper: Wrapper });
    await waitFor(() => expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(1));

    let closePromise!: Promise<ChatSnapshot>;
    act(() => {
      closePromise = closeChatRuntime();
    });
    expect(result.current.runtimeLaunchDisabled).toBe(true);

    const closedSnapshot: ChatSnapshot = {
      dialogText: "",
      inputDraft: "",
      options: [],
      sprites: [],
      status: "idle",
    };
    await act(async () => {
      resolveClose(closedSnapshot);
      await expect(closePromise).resolves.toBe(closedSnapshot);
    });
    expect(result.current.runtimeLaunchDisabled).toBe(false);
  });

  it("releases the local closing state when the close operation fails", async () => {
    let rejectClose: (error: Error) => void = () => undefined;
    mocks.closeChat.mockReturnValue(
      new Promise<ChatSnapshot>((_resolve, reject) => {
        rejectClose = reject;
      }),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useChatLaunchGuard(), { wrapper: Wrapper });
    await waitFor(() => expect(mocks.getChatRuntimeStatus).toHaveBeenCalledTimes(1));

    let closePromise!: Promise<ChatSnapshot>;
    act(() => {
      closePromise = closeChatRuntime();
    });
    expect(result.current.runtimeLaunchDisabled).toBe(true);

    await act(async () => {
      rejectClose(new Error("close failed"));
      await expect(closePromise).rejects.toThrow("close failed");
    });
    expect(result.current.runtimeLaunchDisabled).toBe(false);
  });
});
