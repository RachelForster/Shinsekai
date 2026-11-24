import { useCallback, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { charactersQueryKey } from "../../../entities/character/repository";
import type { Character } from "../../../entities/config/types";

interface UseCharacterAiSyncControllerOptions {
  activeCharacterKeyRef: MutableRefObject<string>;
  deletedCharacterKeysRef: MutableRefObject<Set<string>>;
  identityMutationEpochRef: MutableRefObject<number>;
  identityPendingRef: MutableRefObject<boolean>;
  inCreateModeRef: MutableRefObject<boolean>;
  queryClient: QueryClient;
  setDraft: Dispatch<SetStateAction<Character>>;
}

export interface SyncGeneratedSettingInput {
  characterBrief?: string;
  characterSetting: string;
  committedName: string;
  identityEpoch: number;
  name: string;
  sourceKey: string;
  wasCreating: boolean;
}

/** Coordinates AI action serialization and guarded cache/draft synchronization for character settings. */
export function useCharacterAiSyncController({
  activeCharacterKeyRef,
  deletedCharacterKeysRef,
  identityMutationEpochRef,
  identityPendingRef,
  inCreateModeRef,
  queryClient,
  setDraft,
}: UseCharacterAiSyncControllerOptions) {
  const [pendingAiActionsCount, setPendingAiActionsCount] = useState(0);
  const pendingAiActionsRef = useRef(0);

  const aiActionPending = pendingAiActionsCount > 0;

  const tryBeginAiAction = useCallback(() => {
    if (identityPendingRef.current) {
      return null;
    }
    pendingAiActionsRef.current += 1;
    setPendingAiActionsCount(pendingAiActionsRef.current);
    const identityEpoch = identityMutationEpochRef.current;
    let released = false;
    return {
      identityEpoch,
      release: () => {
        if (released) {
          return;
        }
        released = true;
        pendingAiActionsRef.current = Math.max(0, pendingAiActionsRef.current - 1);
        setPendingAiActionsCount(pendingAiActionsRef.current);
      },
    };
  }, [identityMutationEpochRef, identityPendingRef]);

  const isSelectionActive = useCallback(
    (sourceKey: string, wasCreating: boolean) =>
      inCreateModeRef.current === wasCreating && (wasCreating || activeCharacterKeyRef.current === sourceKey),
    [activeCharacterKeyRef, inCreateModeRef],
  );

  const syncGeneratedSetting = useCallback(
    ({
      characterBrief,
      characterSetting,
      committedName,
      identityEpoch,
      name,
      sourceKey,
      wasCreating,
    }: SyncGeneratedSettingInput) => {
      const isDeleted = Boolean(
        (sourceKey && deletedCharacterKeysRef.current.has(sourceKey)) ||
        (committedName && deletedCharacterKeysRef.current.has(`name:${committedName}`)),
      );
      if (
        !wasCreating &&
        committedName &&
        committedName === name &&
        !isDeleted &&
        identityMutationEpochRef.current === identityEpoch
      ) {
        queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) =>
          current.map((item) => {
            const itemKey = item.id || `name:${item.name}`;
            if (itemKey !== sourceKey && item.name !== committedName) {
              return item;
            }
            return {
              ...item,
              character_brief: characterBrief ?? item.character_brief ?? "",
              character_setting: characterSetting,
            };
          }),
        );
      }
      if (isSelectionActive(sourceKey, wasCreating)) {
        setDraft((current) => ({
          ...current,
          character_brief: characterBrief ?? current.character_brief ?? "",
          character_setting: characterSetting,
        }));
      }
    },
    [deletedCharacterKeysRef, identityMutationEpochRef, isSelectionActive, queryClient, setDraft],
  );

  return {
    aiActionPending,
    isSelectionActive,
    pendingAiActionsRef,
    syncGeneratedSetting,
    tryBeginAiAction,
  };
}
