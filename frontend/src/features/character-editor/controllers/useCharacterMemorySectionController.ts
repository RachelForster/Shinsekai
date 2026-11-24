import { useCallback, useState } from "react";

import { useI18n } from "../../../shared/i18n";
import type { CharacterPageContext } from "../characterContext";
import { useCharacterMemoryController } from "../useCharacterMemoryController";
import { useCharacterMemoryImportController } from "../useCharacterMemoryImportController";

interface PendingMemoryDelete {
  characterName: string;
  memory: string;
  memoryId: string;
}

export function useCharacterMemorySectionController(ctx: CharacterPageContext) {
  const { t } = useI18n();
  const memoryName = ctx.isSavedCharacter ? ctx.currentCharacterName : ctx.draft.name.trim();
  const memoryController = useCharacterMemoryController({ memoryName });
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
        memory: memory.memory,
        memoryId: memory.id,
      });
    },
    [memoryName],
  );

  const confirmMemoryDelete = useCallback(async () => {
    if (!pendingDelete) {
      return;
    }
    const target = pendingDelete;
    setPendingDelete(null);
    await memoryController.deleteMemory({ memoryId: target.memoryId, name: target.characterName });
  }, [memoryController, pendingDelete]);

  return {
    cancelMemoryDelete: () => setPendingDelete(null),
    confirmMemoryDelete,
    memoryController,
    memoryImportController,
    memoryName,
    pendingDeleteBody: pendingDelete
      ? t("character.memory.deleteConfirmBody", {
          memory: pendingDelete.memory,
          name: pendingDelete.characterName,
        })
      : "",
    pendingDeleteOpen: Boolean(pendingDelete),
    requestMemoryDelete,
  };
}
