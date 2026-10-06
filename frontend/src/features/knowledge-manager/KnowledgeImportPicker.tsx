import "../../shared/ui/ImportPreview.css";
import { useId, useState } from "react";
import { Upload } from "lucide-react";

import { useI18n } from "../../shared/i18n";
import { AsyncButton, Button, Dialog, TextInput } from "../../shared/ui";

interface KnowledgeImportPickerProps {
  importPending?: boolean;
  selectedKnowledge?: string;
  onImportFiles: (items: File[]) => Promise<boolean>;
  importKnowledgeId: string;
  onImportKnowledgeIdChange: (value: string) => void;
}

export function KnowledgeImportPicker({
  importPending = false,
  selectedKnowledge = "",
  onImportFiles,
  importKnowledgeId,
  onImportKnowledgeIdChange,
}: KnowledgeImportPickerProps) {
  const { t } = useI18n();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const targetId = useId();

  const previewFiles = async () => {
    if (!importKnowledgeId.trim() || !selectedFiles.length || importPending) return;
    if (await onImportFiles(selectedFiles)) setPickerOpen(false);
  };

  return (
    <>
      <AsyncButton
        icon={<Upload aria-hidden className="button__icon" />}
        loading={importPending}
        onClick={() => {
          onImportKnowledgeIdChange(selectedKnowledge);
          setSelectedFiles([]);
          setPickerOpen(true);
        }}
        variant="ghost"
      >
        {t("knowledge.import")}
      </AsyncButton>

      <Dialog
        closeLabel={t("common.close")}
        dismissible={!importPending}
        footer={
          <>
            <Button disabled={importPending} onClick={() => setPickerOpen(false)}>
              {t("common.cancel")}
            </Button>
            <AsyncButton
              disabled={!importKnowledgeId.trim() || !selectedFiles.length}
              loading={importPending}
              onClick={() => void previewFiles()}
              variant="primary"
            >
              {t("knowledge.previewFiles")}
            </AsyncButton>
          </>
        }
        onClose={() => setPickerOpen(false)}
        open={pickerOpen}
        title={t("knowledge.importPickerTitle")}
      >
        <div className="field-row">
          <label className="field-row__label" htmlFor={targetId}>
            {t("knowledge.importKnowledgeId")}
          </label>
          <TextInput
            id={targetId}
            value={importKnowledgeId}
            disabled={importPending}
            onChange={(event) => onImportKnowledgeIdChange(event.target.value)}
            placeholder={t("knowledge.knowledgeIdPlaceholder")}
          />
        </div>
        <Button className="memory-import-file-picker" disabled={importPending} variant="primary">
          {t("knowledge.selectFiles")}
          <input
            accept=".txt,text/plain"
            aria-label={t("knowledge.selectFiles")}
            multiple
            disabled={importPending}
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []);
              event.currentTarget.value = "";
              if (files.length) setSelectedFiles(files);
            }}
            type="file"
          />
        </Button>
        <div className="memory-import-preview__files">
          {selectedFiles.map((file, index) => (
            <div className="memory-import-preview__file" key={`${file.name}-${file.size}-${index}`}>
              <strong>{file.name}</strong>
              <span>{t("knowledge.fileSize", { size: file.size })}</span>
            </div>
          ))}
        </div>
      </Dialog>
    </>
  );
}
