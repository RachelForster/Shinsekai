import { AlertDialog, Button, Dialog, TaskProgress, AsyncButton } from "../../shared/ui";
import { useI18n } from "../../shared/i18n";
import { type KnowledgeDeleteTarget } from "./useKnowledgeController";
import {
  type TaskSnapshot,
  type KnowledgeImportPreview,
  type KnowledgeImportResult,
} from "../../shared/platform/types";
import { ImportPreview } from "../../shared/ui/ImportPreview";

export function KnowledgeDeleteDialogs({
  target,
  pending,
  onCancel,
  onConfirm,
}: {
  target: KnowledgeDeleteTarget | null;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  return (
    <AlertDialog
      open={Boolean(target)}
      pending={pending}
      title={t(target?.memoryId ? "knowledge.deleteEntry" : "knowledge.deleteKnowledge")}
      body={t(target?.memoryId ? "knowledge.deleteEntryBody" : "knowledge.deleteKnowledgeBody", {
        knowledgeId: target?.knowledgeId ?? "",
        content: target?.content ?? "",
      })}
      cancelLabel={t("common.cancel")}
      closeLabel={t("common.close")}
      confirmLabel={t("common.delete")}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}

export function KnowledgeLoadingDialog({
  open,
  message,
  task,
  onClose,
}: {
  open: boolean;
  message: string;
  task: TaskSnapshot | null;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t("knowledge.title")}
      closeLabel={t("common.close")}
      footer={<Button onClick={onClose}>{t("common.close")}</Button>}
    >
      <div className="knowledge-loading-dialog">
        <p>{message}</p>
        {task ? (
          <TaskProgress logLimit={6} task={task} />
        ) : (
          <span className="knowledge-loading-progress" role="progressbar" aria-label={message} />
        )}
      </div>
    </Dialog>
  );
}

export function KnowledgeImportDialogs(props: {
  knowledgeId: string;
  importPending: boolean;
  onClosePreview: () => void;
  onCloseTask: () => void;
  onConfirm: () => void;
  preview: KnowledgeImportPreview | null;
  previewOpen: boolean;
  result: KnowledgeImportResult | null;
  task: TaskSnapshot<KnowledgeImportResult> | null;
  taskOpen: boolean;
}) {
  const { t } = useI18n();
  const { importPending, onClosePreview, onCloseTask, onConfirm, preview, previewOpen, result, task, taskOpen } = props;
  return (
    <>
      <Dialog
        className="memory-import-preview-dialog"
        closeLabel={t("common.close")}
        footer={
          <>
            <Button onClick={onClosePreview}>{t("common.cancel")}</Button>
            <AsyncButton loading={importPending} onClick={onConfirm} variant="primary">
              {t("knowledge.importConfirm")}
            </AsyncButton>
          </>
        }
        onClose={onClosePreview}
        open={previewOpen && Boolean(preview)}
        title={t("knowledge.importPreviewTitle")}
      >
        {preview ? (
          <ImportPreview
            preview={preview}
            target={t("knowledge.importTarget", { knowledgeId: props.knowledgeId })}
            sourceLabel={t("knowledge.importSourceContent")}
          />
        ) : null}
      </Dialog>
      <Dialog
        closeLabel={t("common.close")}
        dismissible={!importPending}
        footer={
          <Button disabled={importPending} onClick={onCloseTask}>
            {importPending ? t("character.memory.importRunning") : t("common.close")}
          </Button>
        }
        onClose={onCloseTask}
        open={taskOpen}
        title={t("knowledge.importTaskTitle")}
      >
        <div className="memory-import-task">
          {task ? (
            <TaskProgress logLimit={6} task={task} />
          ) : (
            <p className="inline-status">{t("knowledge.importPreparing")}</p>
          )}
          {result ? (
            <p className="memory-import-task__result">
              {t("knowledge.importCompleteBody", { count: result.savedCount, knowledgeId: result.knowledge_id })}
            </p>
          ) : null}
        </div>
      </Dialog>
    </>
  );
}
