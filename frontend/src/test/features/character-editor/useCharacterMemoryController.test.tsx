import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCharacterMemoryController } from "../../../features/character-editor/useCharacterMemoryController";
import { I18nProvider } from "../../../shared/i18n/I18nProvider";
import { ToastProvider } from "../../../shared/ui";

const mockAwakenCharacterMemory = vi.fn();
const mockDeleteCharacterMemory = vi.fn();
const mockDeleteCharacterMemories = vi.fn();
const mockExportCharacterMemories = vi.fn();
const mockSaveMemoriesTextFile = vi.fn();

vi.mock("../../../features/character-editor/memoryExport", () => ({
  saveMemoriesTextFile: (name: string, text: string) => mockSaveMemoriesTextFile(name, text),
}));
const mockGetMem0Status = vi.fn();
const mockInstallMissingRuntimeDependency = vi.fn();
const mockListCharacterMemories = vi.fn();
const mockPinCharacterMemory = vi.fn();
const mockRememberCharacterMemory = vi.fn();
const mockSearchCharacterMemories = vi.fn();

vi.mock("../../../entities/chat/repository", () => ({
  installMissingRuntimeDependency: (...args: unknown[]) => mockInstallMissingRuntimeDependency(...args),
}));

vi.mock("../../../entities/character/repository", () => ({
  awakenCharacterMemory: (input: unknown) => mockAwakenCharacterMemory(input),
  deleteCharacterMemory: (name: string, memoryId: string) => mockDeleteCharacterMemory(name, memoryId),
  deleteCharacterMemories: (name: string, memoryIds: string[]) => mockDeleteCharacterMemories(name, memoryIds),
  exportCharacterMemories: (input: unknown) => mockExportCharacterMemories(input),
  getMem0Status: () => mockGetMem0Status(),
  listCharacterMemories: (name: string, options?: unknown) => mockListCharacterMemories(name, options),
  pinCharacterMemory: (input: unknown) => mockPinCharacterMemory(input),
  rememberCharacterMemory: (...args: unknown[]) => mockRememberCharacterMemory(...args),
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

  it("selects memories and deletes them in one batch", async () => {
    mockListCharacterMemories.mockResolvedValue({
      agentId: "Mika",
      count: 3,
      memories: [
        { id: "m1", memory: "One" },
        { id: "m2", memory: "Two" },
        { id: "m3", memory: "Three" },
      ],
    });
    mockDeleteCharacterMemories.mockResolvedValue({
      agentId: "Mika",
      count: 1,
      memories: [{ id: "m3", memory: "Three" }],
    });
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useCharacterMemoryController({ memoryName: "Mika" }), { wrapper: Wrapper });

    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.totalVisibleCount).toBe(3));

    act(() => result.current.selectAllVisible());
    expect(Array.from(result.current.selectedIds)).toEqual(["m1", "m2", "m3"]);
    act(() => result.current.toggleSelected("m3", false));
    expect(Array.from(result.current.selectedIds)).toEqual(["m1", "m2"]);

    await act(async () => {
      await result.current.deleteMemories({ memoryIds: Array.from(result.current.selectedIds), name: "Mika" });
    });

    expect(mockDeleteCharacterMemories).toHaveBeenCalledWith("Mika", ["m1", "m2"]);
    await waitFor(() => expect(result.current.totalVisibleCount).toBe(1));
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("keeps failed memories selected and visible in search results on partial batch delete", async () => {
    mockSearchCharacterMemories.mockResolvedValue({
      agentId: "Mika",
      count: 2,
      memories: [
        { id: "m1", memory: "One" },
        { id: "m2", memory: "Two" },
      ],
    });
    mockDeleteCharacterMemories.mockResolvedValue({
      agentId: "Mika",
      count: 1,
      deleted: ["m1"],
      failed: [{ error: "locked", memoryId: "m2" }],
      memories: [{ id: "m2", memory: "Two" }],
      offset: 0,
      total: 1,
    });
    mockListCharacterMemories.mockResolvedValue({
      agentId: "Mika",
      count: 1,
      memories: [{ id: "m2", memory: "Two" }],
      offset: 0,
      total: 1,
    });
    const { client, Wrapper } = createWrapper();
    const setQueryDataSpy = vi.spyOn(client, "setQueryData");
    const { result } = renderHook(() => useCharacterMemoryController({ memoryName: "Mika" }), { wrapper: Wrapper });

    act(() => result.current.setSearchInput("One"));
    await act(async () => {
      await result.current.search();
    });
    expect(result.current.data?.memories.map((memory) => memory.id)).toEqual(["m1", "m2"]);

    act(() => result.current.selectAllVisible());
    expect(Array.from(result.current.selectedIds)).toEqual(["m1", "m2"]);

    await act(async () => {
      await result.current.deleteMemories({ memoryIds: ["m1", "m2"], name: "Mika" });
    });

    expect(Array.from(result.current.selectedIds)).toEqual(["m2"]);
    expect(result.current.data?.memories).toEqual([{ id: "m2", memory: "Two" }]);
    const expectedCachedWindow = {
      agentId: "Mika",
      count: 1,
      memories: [{ id: "m2", memory: "Two" }],
      offset: 0,
      total: 1,
    };
    expect(setQueryDataSpy).toHaveBeenCalledWith(["character-memories", "Mika", 0], expectedCachedWindow);
    const cachedWindow = client.getQueryData<Record<string, unknown>>(["character-memories", "Mika", 0]);
    expect(cachedWindow).toEqual(expectedCachedWindow);
    expect(cachedWindow).not.toHaveProperty("deleted");
    expect(cachedWindow).not.toHaveProperty("failed");
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
      count: 11,
      memories: Array.from({ length: 11 }, (_, index) => ({
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
    expect(result.current.data?.memories).toHaveLength(10);
    expect(result.current.memoryTotalPages).toBe(2);

    act(() => result.current.setMemoryPage(() => 2));

    expect(result.current.data?.memories).toEqual([{ id: "memory-11", memory: "Memory 11" }]);
  });

  it("pages 10 rows at a time and fetches the next 200-row window after page 20", async () => {
    const makeWindow = (offset: number) => ({
      agentId: "Mika",
      count: offset === 0 ? 200 : 50,
      memories: Array.from({ length: offset === 0 ? 200 : 50 }, (_, index) => ({
        id: `m-${offset + index}`,
        memory: `Memory ${offset + index}`,
      })),
      offset,
      total: 250,
    });
    mockListCharacterMemories.mockImplementation((_name: string, options?: { offset?: number }) =>
      Promise.resolve(makeWindow(options?.offset ?? 0)),
    );
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useCharacterMemoryController({ memoryName: "Mika" }), { wrapper: Wrapper });

    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.data?.memories).toHaveLength(10));
    expect(mockListCharacterMemories).toHaveBeenLastCalledWith("Mika", { limit: 200, offset: 0 });
    expect(result.current.totalVisibleCount).toBe(250);
    expect(result.current.memoryTotalPages).toBe(25);
    expect(result.current.loadedCount).toBe(200);

    act(() => result.current.setMemoryPage(() => 20));
    expect(result.current.data?.memories[0]?.id).toBe("m-190");
    expect(mockListCharacterMemories).toHaveBeenCalledTimes(1);

    act(() => result.current.setMemoryPage(() => 21));
    await waitFor(() => expect(result.current.data?.memories[0]?.id).toBe("m-200"));
    expect(mockListCharacterMemories).toHaveBeenLastCalledWith("Mika", { limit: 200, offset: 200 });
    expect(result.current.loadedCount).toBe(50);

    act(() => result.current.setMemoryPage(() => 25));
    expect(result.current.data?.memories.map((memory) => memory.id)).toEqual(
      Array.from({ length: 10 }, (_, index) => `m-${240 + index}`),
    );
  });

  it("exports through the backend with selection or everything", async () => {
    mockExportCharacterMemories.mockResolvedValue({ agentId: "Mika", count: 2, text: "exported" });
    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useCharacterMemoryController({ memoryName: "Mika" }), { wrapper: Wrapper });

    await act(async () => {
      await result.current.exportMemories();
    });
    expect(mockExportCharacterMemories).toHaveBeenLastCalledWith(
      expect.objectContaining({ memoryIds: undefined, name: "Mika" }),
    );
    expect(mockSaveMemoriesTextFile).toHaveBeenLastCalledWith("Mika", "exported");

    act(() => result.current.toggleSelected("m-1", true));
    await act(async () => {
      await result.current.exportMemories();
    });
    expect(mockExportCharacterMemories).toHaveBeenLastCalledWith(
      expect.objectContaining({ memoryIds: ["m-1"], name: "Mika" }),
    );
  });

  it("installs missing memory dependency from cached dependency error", async () => {
    mockInstallMissingRuntimeDependency.mockResolvedValue({
      message: "installed",
      moduleName: "mem0",
      packageName: "mem0ai",
    });
    const { client, Wrapper } = createWrapper();
    client.setQueryData(["character-memories", "Mika", 0], {
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

  it("supports adding canon memories, pinning/unpinning, and awakening faded memories", async () => {
    mockRememberCharacterMemory.mockResolvedValue({
      agentId: "Mika",
      count: 1,
      memories: [{ clarity: "canon", id: "canon-1", memory: "Never eats spicy food", pinned: true }],
    });
    mockPinCharacterMemory.mockResolvedValue({
      agentId: "Mika",
      count: 1,
      memories: [{ clarity: "clear", id: "canon-1", memory: "Never eats spicy food", pinned: false, retention: 1 }],
    });
    mockAwakenCharacterMemory.mockResolvedValue({
      agentId: "Mika",
      count: 1,
      memories: [{ clarity: "clear", id: "canon-1", memory: "Never eats spicy food", pinned: false, retention: 1 }],
    });

    const { Wrapper } = createWrapper();
    const { result } = renderHook(() => useCharacterMemoryController({ memoryName: "Mika" }), { wrapper: Wrapper });

    act(() => {
      result.current.setMemoryInput("Never eats spicy food");
      result.current.setAddAsCanon(true);
    });
    await act(async () => {
      await result.current.add();
    });
    await waitFor(() =>
      expect(mockRememberCharacterMemory).toHaveBeenCalledWith("Mika", "Never eats spicy food", {
        kind: "canon",
        pinned: true,
      }),
    );
    expect(result.current.addAsCanon).toBe(false);

    await act(async () => {
      await result.current.pinMemory({ memoryId: "canon-1", name: "Mika", pinned: false });
    });
    await waitFor(() =>
      expect(mockPinCharacterMemory).toHaveBeenCalledWith({ memoryId: "canon-1", name: "Mika", pinned: false }),
    );

    await act(async () => {
      await result.current.awakenMemory({ memoryId: "canon-1", name: "Mika" });
    });
    await waitFor(() => expect(mockAwakenCharacterMemory).toHaveBeenCalledWith({ memoryId: "canon-1", name: "Mika" }));
  });
});
