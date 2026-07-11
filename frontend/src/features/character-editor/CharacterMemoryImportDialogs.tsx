import { AlertTriangle } from "lucide-react";

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
        {preview ? (
          <div className="memory-import-preview">
            <p className="memory-import-preview__lead">
              {t("character.memory.importPreviewSummary", {
                chunks: formatNumber(preview.chunkCount),
                files: formatNumber(preview.fileCount),
                tokens: formatNumber(preview.estimatedTotalTokens),
              })}
            </p>
            <dl className="memory-import-preview__metrics">
              <div>
                <dt>{t("character.memory.importDialogue")}</dt>
                <dd>
                  {t("character.memory.importDialogueValue", {
                    characters: formatNumber(preview.dialogueCharacters),
                    lines: formatNumber(preview.dialogueLineCount),
                  })}
                </dd>
              </div>
              <div>
                <dt>{t("character.memory.importSourceTokens")}</dt>
                <dd>≈ {formatNumber(preview.sourceTokens)}</dd>
              </div>
              <div>
                <dt>{t("character.memory.importChunks")}</dt>
                <dd>
                  {t("character.memory.importChunksValue", {
                    chunks: formatNumber(preview.chunkCount),
                    requests: formatNumber(preview.chunkCount),
                  })}
                </dd>
              </div>
              <div>
                <dt>{t("character.memory.importEstimatedInput")}</dt>
                <dd>≈ {formatNumber(preview.estimatedInputTokens)}</dd>
              </div>
              <div>
                <dt>{t("character.memory.importEstimatedOutput")}</dt>
                <dd>≈ {formatNumber(preview.estimatedOutputTokens)}</dd>
              </div>
              <div className="memory-import-preview__metric--total">
                <dt>{t("character.memory.importEstimatedTotal")}</dt>
                <dd>≈ {formatNumber(preview.estimatedTotalTokens)}</dd>
              </div>
            </dl>
            <p className="memory-import-preview__notice">
              <AlertTriangle aria-hidden size={18} />
              <span>{t("character.memory.importBillingNote")}</span>
            </p>
            {preview.files.some((file) => file.kind.toLowerCase() === "json") ? (
              <p className="inline-status">{t("character.memory.importJsonNote")}</p>
            ) : null}
            {preview.warnings.length ? (
              <ul className="memory-import-preview__warnings">
                {preview.warnings.map((warning, index) => (
                  <li key={`${warning}-${index}`}>{warning}</li>
                ))}
              </ul>
            ) : null}
            <div className="memory-import-preview__files">
              {preview.files.map((file, index) => (
                <div className="memory-import-preview__file" key={`${file.name}-${index}`}>
                  <strong>{file.name}</strong>
                  <span>
                    {t("character.memory.importFileDetail", {
                      chunks: formatNumber(file.chunkCount),
                      kind: file.kind.toUpperCase(),
                      tokens: formatNumber(file.sourceTokens),
                    })}
                  </span>
                </div>
              ))}
            </div>
          </div>
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
