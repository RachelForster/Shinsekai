import { state } from "./relationTestSetup";
import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { useCharacterRelationController } from "../../../features/character-relation/useCharacterRelationController";
import type { CharacterRelationGraph, RelationRequest } from "../../../shared/platform/types";

describe("useCharacterRelationController", () => {
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
});
