import { ImportPreview } from "../../shared/ui/ImportPreview";
import { useI18n } from "../../shared/i18n";
import type {
  CharacterMemoryImportPreview,
  CharacterMemoryImportResult,
  TaskSnapshot,
} from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, TaskProgress } from "../../shared/ui";

interface CharacterMemoryImportDialogsProps {
  importPending: boolean;
  onClosePicker: () => void;
  onClosePreview: () => void;
  onCloseTask: () => void;
  onConfirm: () => void;
  onSelect: (items: File[]) => void;
  pickerOpen: boolean;
  preview: CharacterMemoryImportPreview | null;
  previewOpen: boolean;
  result: CharacterMemoryImportResult | null;
  task: TaskSnapshot<CharacterMemoryImportResult> | null;
  taskOpen: boolean;
}

export function CharacterMemoryImportDialogs({
  importPending,
  onClosePicker,
  onClosePreview,
  onCloseTask,
  onConfirm,
  onSelect,
  pickerOpen,
  preview,
  previewOpen,
  result,
  task,
  taskOpen,
}: CharacterMemoryImportDialogsProps) {
  const { language, t } = useI18n();
  const formatNumber = (value: number) =>
    new Intl.NumberFormat(language === "zh_CN" ? "zh-CN" : language).format(value);

  return (
    <>
      <Dialog
        closeLabel={t("common.close")}
        footer={<Button onClick={onClosePicker}>{t("common.cancel")}</Button>}
        onClose={onClosePicker}
        open={pickerOpen}
        title={t("character.memory.importPickerTitle")}
      >
        <Button className="memory-import-file-picker" variant="primary">
          {t("character.memory.importPickerTitle")}
          <input
            accept=".txt,.json,application/json,text/plain"
            aria-label={t("character.memory.importPickerTitle")}
            multiple
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []);
              event.currentTarget.value = "";
              if (!files.length) {
                return;
              }
              onClosePicker();
              onSelect(files);
            }}
            type="file"
          />
        </Button>
      </Dialog>

      <Dialog
        className="memory-import-preview-dialog"
        closeLabel={t("common.close")}
        footer={
          <>
            <Button onClick={onClosePreview}>{t("common.cancel")}</Button>
            <AsyncButton loading={importPending} onClick={onConfirm} variant="primary">
              {t("character.memory.importConfirm")}
            </AsyncButton>
          </>
        }
        onClose={onClosePreview}
        open={previewOpen && Boolean(preview)}
        title={t("character.memory.importPreviewTitle")}
      >
        {preview ? <ImportPreview preview={preview} /> : null}
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
        title={t("character.memory.importTaskTitle")}
      >
        <div className="memory-import-task">
          {task ? (
            <TaskProgress logLimit={6} task={task} />
          ) : (
            <p className="inline-status">{t("character.memory.importPreparing")}</p>
          )}
          {result ? (
            <p className="memory-import-task__result">
              {t("character.memory.importCompleteBody", {
                duplicates: formatNumber(result.duplicateCount),
                extracted: formatNumber(result.extractedCount),
                saved: formatNumber(result.savedCount),
              })}
            </p>
          ) : null}
        </div>
      </Dialog>
    </>
  );
}
