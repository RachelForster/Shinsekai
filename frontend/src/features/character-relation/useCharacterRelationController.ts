import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { charactersQueryKey } from "../../entities/character/repository";

import {
  applyCharacterRelationChanges,
  getCharacterRelationGraph,
  relationQueryKey,
} from "../../entities/character-relation/repository";
import type { CharacterRelationGraph, RelationRequest } from "../../shared/platform/types";

export interface CharacterRelationController {
  data: CharacterRelationGraph | undefined;
  isLoading: boolean;
  isFetching: boolean;
  loadError: string;
  savePending: boolean;
  cleanPending: boolean;
  saveError: string;
  /** True only when the changes have been saved; false on failure or a concurrent save. */
  save: (operations: RelationRequest[]) => Promise<boolean>;
  reload: () => Promise<void>;
  clean: () => Promise<void>;
}

function saveErrorMessage(error: unknown): string {
  if (error == null) return "";
  return error instanceof Error ? error.message : String(error);
}

export function useCharacterRelationController(owner: string): CharacterRelationController {
  const queryClient = useQueryClient();
  const saveInProgress = useRef(false);
  const [cleanPending, setCleanPending] = useState(false);
  const queryKey = [...relationQueryKey, owner];
  const query = useQuery<CharacterRelationGraph, Error>({
    queryKey,
    queryFn: () => getCharacterRelationGraph(owner),
    enabled: Boolean(owner),
    retry: false,
  });

  const saveMutation = useMutation<CharacterRelationGraph, Error, RelationRequest[]>({
    mutationFn: (operations) => applyCharacterRelationChanges(owner, operations),
    onSuccess(graph) {
      queryClient.setQueryData(queryKey, graph);
    },
    retry: false,
  });

  async function save(operations: RelationRequest[]): Promise<boolean> {
    if (saveInProgress.current) return false;

    saveInProgress.current = true;
    try {
      await saveMutation.mutateAsync(operations);
      return true;
    } catch {
      return false;
    } finally {
      saveInProgress.current = false;
    }
  }

  async function reload(): Promise<void> {
    saveMutation.reset();
    try {
      await query.refetch();
    } finally {
      await queryClient.invalidateQueries({ queryKey: charactersQueryKey });
    }
  }

  async function clean(): Promise<void> {
    if (saveInProgress.current) return;
    saveInProgress.current = true;
    setCleanPending(true);
    saveMutation.reset();
    try {
      const result = await query.refetch();
      if (result.isError || !result.data) return;
      const graph = result.data;
      const retainedEdges = graph.edges.filter((edge) => edge.source === graph.owner || edge.target === graph.owner);
      const connected = new Set(retainedEdges.flatMap((edge) => [edge.source, edge.target]));
      const operations: RelationRequest[] = [
        ...graph.edges
          .filter((edge) => edge.source !== graph.owner && edge.target !== graph.owner)
          .map((edge): RelationRequest => ({ op: "delete_edge", source: edge.source, target: edge.target })),
        ...graph.nodes
          .filter((node) => node.key !== graph.owner && !connected.has(node.key))
          .map((node): RelationRequest => ({ op: "delete_node", key: node.key })),
      ];
      if (operations.length) {
        try {
          await saveMutation.mutateAsync(operations);
        } catch {
          // The mutation exposes the error to the editor.
        }
      }
    } finally {
      try {
        await queryClient.invalidateQueries({ queryKey: charactersQueryKey });
      } finally {
        saveInProgress.current = false;
        setCleanPending(false);
      }
    }
  }

  return {
    data: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    loadError: query.error ? String(query.error) : "",
    savePending: saveMutation.isPending,
    cleanPending,
    saveError: saveErrorMessage(saveMutation.error),
    save,
    reload,
    clean,
  };
}
