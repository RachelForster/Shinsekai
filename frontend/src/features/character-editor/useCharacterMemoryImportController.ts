import { useEffect, useState } from "react";

import { importCharacterMemories, previewCharacterMemoryImport } from "../../entities/character/repository";
import { useI18n } from "../../shared/i18n";
import type {
  CharacterMemoryImportPreview,
  CharacterMemoryImportResult,
  TaskSnapshot,
} from "../../shared/platform/types";
import { useToast } from "../../shared/ui";

interface UseCharacterMemoryImportControllerOptions {
  ensureReady: () => Promise<boolean>;
  memoryName: string;
  onRefresh: () => Promise<void> | void;
}

export function useCharacterMemoryImportController({
  ensureReady,
  memoryName,
  onRefresh,
}: UseCharacterMemoryImportControllerOptions) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const [items, setItems] = useState<File[] | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [preview, setPreview] = useState<CharacterMemoryImportPreview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewPending, setPreviewPending] = useState(false);
  const [importPending, setImportPending] = useState(false);
  const [taskOpen, setTaskOpen] = useState(false);
  const [task, setTask] = useState<TaskSnapshot<CharacterMemoryImportResult> | null>(null);
  const [result, setResult] = useState<CharacterMemoryImportResult | null>(null);

  useEffect(() => {
    setItems(null);
    setPickerOpen(false);
    setPreview(null);
    setPreviewOpen(false);
    setPreviewPending(false);
    setImportPending(false);
    setTaskOpen(false);
    setTask(null);
    setResult(null);
  }, [memoryName]);

  const openPicker = () => {
    if (!memoryName || previewPending || importPending) {
      return;
    }
    setPickerOpen(true);
  };

  const previewItems = async (nextItems: File[]) => {
    if (!memoryName || !nextItems.length || previewPending || importPending) {
      return;
    }
    setItems(nextItems);
    setPreview(null);
    setResult(null);
    setPreviewPending(true);
    try {
      const nextPreview = await previewCharacterMemoryImport(memoryName, nextItems);
      setPreview(nextPreview);
      setPreviewOpen(true);
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.importFailed"),
        title: t("character.memory.importPreviewTitle"),
      });
    } finally {
      setPreviewPending(false);
    }
  };

  const confirmImport = async () => {
    if (!memoryName || !items?.length || !preview || importPending) {
      return;
    }
    setImportPending(true);
    if (!(await ensureReady())) {
      setImportPending(false);
      return;
    }
    setPreviewOpen(false);
    setTask(null);
    setResult(null);
    setTaskOpen(true);
    try {
      const nextResult = await importCharacterMemories(memoryName, items, {
        onTaskUpdate: (nextTask) => setTask(nextTask),
      });
      setResult(nextResult);
      showToast({
        kind: "success",
        message: t("character.memory.importCompleteBody", {
          duplicates: nextResult.duplicateCount,
          extracted: nextResult.extractedCount,
          saved: nextResult.savedCount,
        }),
        title: t("character.memory.importComplete"),
      });
      await onRefresh();
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("character.memory.importFailed"),
        title: t("character.memory.importFailed"),
      });
    } finally {
      setImportPending(false);
    }
  };

  return {
    closePicker: () => setPickerOpen(false),
    closePreview: () => {
      if (!importPending) {
        setPreviewOpen(false);
      }
    },
    closeTask: () => {
      if (!importPending) {
        setTaskOpen(false);
      }
    },
    confirmImport,
    importPending,
    openPicker,
    pickerOpen,
    preview,
    previewItems,
    previewOpen,
    previewPending,
    result,
    task,
    taskOpen,
  };
}
