import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCharacterMemoryController } from "../../../features/character-editor/useCharacterMemoryController";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mockDeleteCharacterMemory = vi.fn();
const mockGetMem0Status = vi.fn();
const mockInstallMissingRuntimeDependency = vi.fn();
const mockListCharacterMemories = vi.fn();
const mockRememberCharacterMemory = vi.fn();
const mockSearchCharacterMemories = vi.fn();

vi.mock("../../../entities/chat/repository", () => ({
  installMissingRuntimeDependency: (...args: unknown[]) => mockInstallMissingRuntimeDependency(...args),
}));

vi.mock("../../../entities/character/repository", () => ({
  deleteCharacterMemory: (name: string, memoryId: string) => mockDeleteCharacterMemory(name, memoryId),
  getMem0Status: () => mockGetMem0Status(),
  listCharacterMemories: (name: string) => mockListCharacterMemories(name),
  rememberCharacterMemory: (name: string, memory: string) => mockRememberCharacterMemory(name, memory),
  searchCharacterMemories: (input: { limit?: number; name: string; query: string }) =>
    mockSearchCharacterMemories(input),
}));

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });

  function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={client}>
        <ToastProvider>
          <I18nProvider language="en">{children}</I18nProvider>
        </ToastProvider>
      </QueryClientProvider>
    );
  }

  return { client, Wrapper };
}

describe("useCharacterMemoryController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMem0Status.mockResolvedValue({ status: "ready" });
    mockListCharacterMemories.mockResolvedValue({ agentId: "Mika", count: 0, memories: [] });
    mockSearchCharacterMemories.mockResolvedValue({ agentId: "Mika", count: 0, memories: [] });
  });

  it("adds and deletes memories after confirming mem0 is ready", async () => {
    mockRememberCharacterMemory.mockResolvedValue({
      agentId: "Mika",
      count: 1,
      memories: [{ id: "memory-1", memory: "Likes tea" }],
    });
    mockDeleteCharacterMemory.mockResolvedValue({ agentId: "Mika", count: 0, memories: [] });
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useCharacterMemoryController({ memoryName: "Mika" }), { wrapper: Wrapper });

    act(() => result.current.setMemoryInput("Likes tea"));
    await act(async () => {
      await result.current.add();
    });

    await waitFor(() => expect(mockRememberCharacterMemory).toHaveBeenCalledWith("Mika", "Likes tea"));
    expect(mockGetMem0Status).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.deleteMemory({ memoryId: "memory-1", name: "Mika" });
    });

    await waitFor(() => expect(mockDeleteCharacterMemory).toHaveBeenCalledWith("Mika", "memory-1"));
    expect(mockGetMem0Status).toHaveBeenCalledTimes(2);
  });

  it("does not add memory when mem0 status check fails", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    mockGetMem0Status.mockRejectedValue(new Error("bridge unavailable"));
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useCharacterMemoryController({ memoryName: "Mika" }), { wrapper: Wrapper });

    act(() => result.current.setMemoryInput("Likes tea"));
    await act(async () => {
      await result.current.add();
    });

    expect(mockGetMem0Status).toHaveBeenCalledWith();
    expect(mockRememberCharacterMemory).not.toHaveBeenCalled();
    expect(result.current.isChecking).toBe(false);
    expect(consoleError).toHaveBeenCalledWith("Failed to get mem0 status", expect.any(Error));
    consoleError.mockRestore();
  });

  it("searches memories and exposes paged results", async () => {
    mockSearchCharacterMemories.mockResolvedValue({
      agentId: "Mika",
      count: 9,
      memories: Array.from({ length: 9 }, (_, index) => ({
        id: `memory-${index + 1}`,
        memory: `Memory ${index + 1}`,
      })),
    });
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useCharacterMemoryController({ memoryName: "Mika" }), { wrapper: Wrapper });

    act(() => result.current.setSearchInput("tea"));
    await act(async () => {
      await result.current.search();
    });

    expect(mockSearchCharacterMemories).toHaveBeenCalledWith({ limit: 200, name: "Mika", query: "tea" });
    expect(result.current.activeSearchQuery).toBe("tea");
    expect(result.current.data?.memories).toHaveLength(8);
    expect(result.current.memoryTotalPages).toBe(2);

    act(() => result.current.setMemoryPage(() => 2));

    expect(result.current.data?.memories).toEqual([{ id: "memory-9", memory: "Memory 9" }]);
  });

  it("installs missing memory dependency from cached dependency error", async () => {
    mockInstallMissingRuntimeDependency.mockResolvedValue({
      message: "installed",
      moduleName: "mem0",
      packageName: "mem0ai",
    });
    const { client, Wrapper } = createWrapper();
    client.setQueryData(["character-memories", "Mika"], {
      kind: "missing_dependency",
      moduleName: "mem0",
      packageName: "mem0ai",
    });
    const { result } = renderHook(() => useCharacterMemoryController({ memoryName: "Mika" }), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.depError?.moduleName).toBe("mem0"));

    await act(async () => {
      await result.current.installDependency();
    });

    expect(mockInstallMissingRuntimeDependency).toHaveBeenCalledWith(
      { moduleName: "mem0" },
      { onTaskUpdate: expect.any(Function) },
    );
    expect(mockGetMem0Status).toHaveBeenCalledWith();
  });
});
