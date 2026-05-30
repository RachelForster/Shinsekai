import { useCallback, useEffect, useState } from "react";
import { Check } from "lucide-react";

import type { PathPickerMode } from "../platform/types";
import { useI18n } from "../i18n";
import "./PathPickerDialog.css";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { FileManager } from "./FileManager";

interface PathPickerDialogProps {
  acceptedExtensions?: string[];
  mode?: PathPickerMode;
  multiple?: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
  onSelectMany?: (paths: string[]) => void;
  open: boolean;
  title: string;
  value?: string;
}

export function PathPickerDialog({
  acceptedExtensions,
  mode = "file",
  multiple = false,
  onClose,
  onSelect,
  onSelectMany,
  open,
  title,
  value = "",
}: PathPickerDialogProps) {
  const { t } = useI18n();
  const [confirmPaths, setConfirmPaths] = useState<string[]>([]);

  useEffect(() => {
    if (!open) {
      setConfirmPaths([]);
    }
  }, [open]);

  const handleConfirm = () => {
    if (!confirmPaths.length) {
      return;
    }
    if (multiple && mode === "file") {
      onSelectMany?.(confirmPaths);
    } else {
      onSelect(confirmPaths[0]);
    }
    onClose();
  };

  const handleOpenFile = useCallback(
    (path: string) => {
      onSelect(path);
      onClose();
    },
    [onClose, onSelect],
  );

  const handleSelectionChange = useCallback((selection: { confirmPaths: string[] }) => {
    setConfirmPaths(selection.confirmPaths);
  }, []);

  if (!open) {
    return null;
  }

  return (
    <Dialog
      bodyClassName="path-picker__body"
      className="path-picker"
      closeLabel={t("common.close")}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!confirmPaths.length}
            icon={<Check aria-hidden className="button__icon" />}
            onClick={handleConfirm}
            variant="primary"
          >
            {mode === "directory" ? t("filePicker.selectCurrent") : t("filePicker.selectFile")}
          </Button>
        </>
      }
      onClose={onClose}
      open={open}
      title={title}
    >
      <FileManager
        acceptedExtensions={acceptedExtensions}
        mode={mode}
        multiple={multiple}
        onOpenFile={handleOpenFile}
        onSelectionChange={handleSelectionChange}
        value={value}
      />
    </Dialog>
  );
}
