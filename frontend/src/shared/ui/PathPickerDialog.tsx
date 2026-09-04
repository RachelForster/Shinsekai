import { useCallback, useEffect, useState } from "react";
import { Check } from "lucide-react";

import type { PathPickerMode } from "../platform/types";
import { isTauriDesktop, pickDesktopNativePath } from "../desktop/desktopApi";
import { useI18n } from "../i18n";
import "./PathPickerDialog.css";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { FileManager, type FileBrowseHandler } from "./FileManager";

interface PathPickerDialogProps {
  acceptedExtensions?: string[];
  mode?: PathPickerMode;
  multiple?: boolean;
  onBrowse?: FileBrowseHandler;
  onClose: () => void;
  onSelect: (path: string) => void;
  onSelectMany?: (paths: string[]) => void;
  open: boolean;
  title: string;
  value?: string;
}

function confirmLabelForMode(mode: PathPickerMode, t: ReturnType<typeof useI18n>["t"]) {
  if (mode === "directory") {
    return t("filePicker.selectCurrent");
  }
  if (mode === "path") {
    return t("filePicker.selectPath");
  }
  return t("filePicker.selectFile");
}

export function PathPickerDialog({
  acceptedExtensions,
  mode = "file",
  multiple = false,
  onBrowse,
  onClose,
  onSelect,
  onSelectMany,
  open,
  title,
  value = "",
}: PathPickerDialogProps) {
  const { t } = useI18n();
  const [confirmPaths, setConfirmPaths] = useState<string[]>([]);
  const [nativeDialogFailed, setNativeDialogFailed] = useState(false);

  useEffect(() => {
    if (!open) {
      setConfirmPaths([]);
      setNativeDialogFailed(false);
    }
  }, [open]);

  // On the Tauri desktop the OS-native dialog replaces the in-app browser.
  useEffect(() => {
    if (!open || !isTauriDesktop()) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const paths = await pickDesktopNativePath({
          defaultPath: value,
          extensions: acceptedExtensions,
          mode,
          multiple,
          title,
        });
        if (cancelled) {
          return;
        }
        if (paths === null) {
          onClose();
          return;
        }
        if (multiple && mode === "file" && onSelectMany) {
          onSelectMany(paths);
        } else if (paths[0]) {
          onSelect(paths[0]);
        }
        onClose();
      } catch {
        // The dialog plugin may be unavailable (e.g. older desktop shell);
        // fall back to the in-app browser instead of failing the pick.
        if (!cancelled) {
          setNativeDialogFailed(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [acceptedExtensions, mode, multiple, onClose, onSelect, onSelectMany, open, title, value]);

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
  if (isTauriDesktop() && !nativeDialogFailed) {
    // The native dialog owns the whole flow; render nothing behind it.
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
            {confirmLabelForMode(mode, t)}
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
        onBrowse={onBrowse}
        onOpenFile={handleOpenFile}
        onSelectionChange={handleSelectionChange}
        value={value}
      />
    </Dialog>
  );
}
