import { useEffect, useRef, useState } from "react";

import { importKnowledge, previewKnowledgeImport } from "../../entities/knowledge/repository";
import { useI18n } from "../../shared/i18n";
import type { KnowledgeImportPreview, KnowledgeImportResult, TaskSnapshot } from "../../shared/platform/types";
import { useToast } from "../../shared/ui";

export function useKnowledgeImportController(input: {
  ensureReady: () => Promise<boolean>;
  onSettled?: (importKnowledgeId: string) => void;
}) {
  const { ensureReady } = input;
  const { t } = useI18n();
  const { showToast } = useToast();
  const [importKnowledgeId, setImportKnowledgeId] = useState("");
  const currentTarget = useRef(importKnowledgeId);
  currentTarget.current = importKnowledgeId;
  const [items, setItems] = useState<File[]>([]);
  const [preview, setPreview] = useState<KnowledgeImportPreview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewPending, setPreviewPending] = useState(false);
  const [importPending, setImportPending] = useState(false);
  const [taskKnowledgeId, setTaskKnowledgeId] = useState("");
  const [taskOpen, setTaskOpen] = useState(false);
  const [task, setTask] = useState<TaskSnapshot<KnowledgeImportResult> | null>(null);
  const [result, setResult] = useState<KnowledgeImportResult | null>(null);

  useEffect(() => {
    setPreview(null);
    setPreviewOpen(false);
    setItems([]);
  }, [importKnowledgeId]);

  const previewFiles = async (nextItems: File[]) => {
    if (!importKnowledgeId.trim() || !nextItems.length || previewPending || importPending) return false;
    setItems(nextItems);
    setPreview(null);
    setPreviewPending(true);
    try {
      const next = await previewKnowledgeImport(importKnowledgeId.trim(), nextItems);
      if (currentTarget.current !== importKnowledgeId) return false;
      setPreview(next);
      setPreviewOpen(true);
      return true;
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("knowledge.importFailed"),
        title: t("knowledge.importFailed"),
      });
      return false;
    } finally {
      setPreviewPending(false);
    }
  };

  const confirmImport = async () => {
    if (!importKnowledgeId.trim() || !items.length || !preview || importPending) return false;
    setImportPending(true);
    try {
      if (!(await ensureReady())) return;
      if (currentTarget.current !== importKnowledgeId) return;
      setPreviewOpen(false);
      setTaskKnowledgeId(importKnowledgeId.trim());
      setTaskOpen(true);
      setTask(null);
      setResult(null);
      const next = await importKnowledge(importKnowledgeId.trim(), items, {
        onTaskUpdate: setTask,
      });
      setResult(next);
      showToast({
        kind: "success",
        message: t("knowledge.importCompleteBody", { count: next.savedCount, knowledgeId: next.knowledge_id }),
        title: t("knowledge.importComplete"),
      });
    } catch (error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("knowledge.importFailed"),
        title: t("knowledge.importFailed"),
      });
    } finally {
      setImportPending(false);
      input.onSettled?.(importKnowledgeId.trim());
    }
  };

  return {
    confirmImport,
    importPending,
    preview,
    previewFiles,
    previewOpen,
    previewPending,
    result,
    setPreviewOpen,
    setTaskOpen,
    setImportKnowledgeId,
    task,
    taskOpen,
    taskKnowledgeId,
    importKnowledgeId,
  };
}
