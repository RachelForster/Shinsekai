import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

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
  saveError: string;
  /** True only when the changes have been saved; false on failure or a concurrent save. */
  save: (operations: RelationRequest[]) => Promise<boolean>;
  reload: () => Promise<void>;
}

function saveErrorMessage(error: unknown): string {
  if (error == null) return "";
  return error instanceof Error ? error.message : String(error);
}

export function useCharacterRelationController(owner: string): CharacterRelationController {
  const queryClient = useQueryClient();
  const saveInProgress = useRef(false);
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
    await query.refetch();
  }

  return {
    data: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    loadError: query.error ? String(query.error) : "",
    savePending: saveMutation.isPending,
    saveError: saveErrorMessage(saveMutation.error),
    save,
    reload,
  };
}
