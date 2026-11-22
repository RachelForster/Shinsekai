import { state } from "./relationTestSetup";
import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { useCharacterRelationController } from "../../../features/character-relation/useCharacterRelationController";
import type { CharacterRelationGraph, RelationRequest } from "../../../shared/platform/types";

describe("useCharacterRelationController", () => {
  it("reloads the latest graph", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(() => useCharacterRelationController("A"), { wrapper });
    await waitFor(() => expect(result.current.data?.nodes).toEqual([{ key: "A" }]));

    const latest = await state.api!.applyRelationChanges("A", [
      { op: "add_node", node: { key: "B" } },
      { op: "add_node", node: { key: "C" } },
      { op: "upsert_edge", edge: { source: "B", target: "C", temperature: 0, content: "other" } },
    ]);
    await act(async () => result.current.reload());
    await waitFor(() => expect(result.current.data).toEqual(latest));
    unmount();
    client.clear();
  });

  it("cleans unrelated edges and isolated nodes", async () => {
    await state.api!.applyRelationChanges("A", [
      ...["B", "C", "D"].map((key): RelationRequest => ({ op: "add_node", node: { key } })),
      { op: "upsert_edge", edge: { source: "B", target: "A", temperature: 1, content: "friend" } },
      { op: "upsert_edge", edge: { source: "B", target: "C", temperature: 0, content: "other" } },
    ]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(() => useCharacterRelationController("A"), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    await act(async () => result.current.clean());
    const graph = await state.api!.getRelationGraph("A");
    expect(graph.nodes.map((node) => node.key)).toEqual(["A", "B"]);
    expect(graph.edges).toEqual([{ source: "B", target: "A", temperature: 1, content: "friend" }]);
    unmount();
    client.clear();
  });

  it("rejects a second save started before the first request completes", async () => {
    const graph: CharacterRelationGraph = {
      owner: "A",
      nodes: [{ key: "A" }, { key: "B" }],
      edges: [],
    };
    const operations: RelationRequest[] = [{ op: "add_node", node: { key: "B" } }];
    let completeSave!: (value: CharacterRelationGraph) => void;
    const request = new Promise<CharacterRelationGraph>((resolve) => {
      completeSave = resolve;
    });
    const saveRequest = vi.spyOn(state.api!, "applyRelationChanges").mockReturnValueOnce(request);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(() => useCharacterRelationController("A"), { wrapper });
    let firstSave!: Promise<boolean>;
    await act(async () => {
      firstSave = result.current.save(operations);
      expect(await result.current.save(operations)).toBe(false);
    });
    expect(saveRequest).toHaveBeenCalledTimes(1);
    await act(async () => {
      completeSave(graph);
      await firstSave;
    });
    unmount();
    client.clear();
  });

  it("blocks saves while clean is fetching and then applies the cleanup", async () => {
    await state.api!.applyRelationChanges("A", [{ op: "add_node", node: { key: "B" } }]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(() => useCharacterRelationController("A"), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    let resolveFetch!: (graph: CharacterRelationGraph) => void;
    const fetch = vi.spyOn(state.api!, "getRelationGraph").mockReturnValueOnce(
      new Promise((resolve) => { resolveFetch = resolve; }),
    );
    const save = vi.spyOn(state.api!, "applyRelationChanges");
    let cleaning!: Promise<void>;
    act(() => { cleaning = result.current.clean(); });
    await waitFor(() => expect(result.current.cleanPending).toBe(true));
    await act(async () => {
      expect(await result.current.save([{ op: "add_node", node: { key: "C" } }])).toBe(false);
    });
    expect(save).not.toHaveBeenCalled();
    await act(async () => {
      resolveFetch({ owner: "A", nodes: [{ key: "A" }, { key: "B" }], edges: [] });
      await cleaning;
    });
    expect(save).toHaveBeenCalledWith("A", [{ op: "delete_node", key: "B" }]);
    expect((await state.api!.getRelationGraph("A")).nodes).toEqual([{ key: "A" }]);
    expect(result.current.cleanPending).toBe(false);
    fetch.mockRestore();
    unmount();
    client.clear();
  });

  it("releases the clean lock and exposes errors when cleanup fails", async () => {
    await state.api!.applyRelationChanges("A", [{ op: "add_node", node: { key: "B" } }]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(() => useCharacterRelationController("A"), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    vi.spyOn(state.api!, "applyRelationChanges").mockRejectedValueOnce(new Error("cleanup failed"));
    await act(async () => result.current.clean());
    await waitFor(() => expect(result.current.saveError).toContain("cleanup failed"));
    expect(result.current.cleanPending).toBe(false);
    await act(async () => {
      expect(await result.current.save([{ op: "add_node", node: { key: "C" } }])).toBe(true);
    });
    unmount();
    client.clear();
  });
});
