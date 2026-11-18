import { useCallback, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import { SELF_PERSONA_ID, isSelfPersonaCharacter } from "../characterEditorUtils";
import type { CharacterPageContext } from "../characterContext";
import { useCharacterMemoryController } from "../useCharacterMemoryController";
import { useCharacterMemoryImportController } from "../useCharacterMemoryImportController";

type PendingMemoryDelete =
  | {
      characterName: string;
      displayName: string;
      kind: "single";
      memory: string;
      memoryId: string;
    }
  | {
      characterName: string;
      displayName: string;
      kind: "batch";
      memoryIds: string[];
    };

export function useCharacterMemorySectionController(ctx: CharacterPageContext) {
  const { t } = useI18n();
  const activeCharacter = ctx.selected ?? ctx.draft;
  const visibleName = ctx.isSavedCharacter ? ctx.currentCharacterName : ctx.draft.name.trim();
  const memoryName = isSelfPersonaCharacter(activeCharacter) ? SELF_PERSONA_ID : visibleName;
  const memoryController = useCharacterMemoryController({
    displayName: visibleName || memoryName,
    memoryName,
  });
  const memoryImportController = useCharacterMemoryImportController({
    ensureReady: memoryController.ensureReady,
    memoryName,
    onRefresh: memoryController.refresh,
  });
  const [pendingDelete, setPendingDelete] = useState<PendingMemoryDelete | null>(null);

  const requestMemoryDelete = useCallback(
    (memory: { id: string; memory: string }) => {
      setPendingDelete({
        characterName: memoryName,
        displayName: visibleName || memoryName,
        kind: "single",
        memory: memory.memory,
        memoryId: memory.id,
      });
    },
    [memoryName, visibleName],
  );

  const requestMemoryBatchDelete = useCallback(
    (memoryIds: string[]) => {
      if (!memoryName || memoryIds.length === 0) {
        return;
      }
      setPendingDelete({
        characterName: memoryName,
        displayName: visibleName || memoryName,
        kind: "batch",
        memoryIds,
      });
    },
    [memoryName, visibleName],
  );

  const confirmMemoryDelete = useCallback(async () => {
    if (!pendingDelete) {
      return;
    }
    const target = pendingDelete;
    setPendingDelete(null);
    if (target.kind === "batch") {
      await memoryController.deleteMemories({ memoryIds: target.memoryIds, name: target.characterName });
      return;
    }
    await memoryController.deleteMemory({ memoryId: target.memoryId, name: target.characterName });
  }, [memoryController, pendingDelete]);

  return {
    cancelMemoryDelete: () => setPendingDelete(null),
    confirmMemoryDelete,
    memoryController,
    memoryImportController,
    memoryName,
    pendingDeleteBody: pendingDelete
      ? pendingDelete.kind === "batch"
        ? t("character.memory.batchDeleteConfirmBody", {
            count: pendingDelete.memoryIds.length,
            name: pendingDelete.displayName,
          })
        : t("character.memory.deleteConfirmBody", {
            memory: pendingDelete.memory,
            name: pendingDelete.displayName,
          })
      : "",
    pendingDeleteOpen: Boolean(pendingDelete),
    pendingDeleteTitle:
      pendingDelete?.kind === "batch" ? t("character.memory.batchDeleteTitle") : t("character.memory.delete"),
    requestMemoryBatchDelete,
    requestMemoryDelete,
  };
}
