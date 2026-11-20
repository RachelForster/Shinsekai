import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { Check, Upload } from "lucide-react";

import type { PathPickerMode } from "../platform/types";
import { isStandaloneRuntimeActive } from "../platform/runtimeTarget";
import { stageUploadedFiles } from "../platform/standalone/storage/vfsBlobRegistry";
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
  const nativeRequestRef = useRef<{
    handled: boolean;
    promise: Promise<string[] | null>;
  } | null>(null);

  useEffect(() => {
    if (!open) {
      nativeRequestRef.current = null;
      setConfirmPaths([]);
      setNativeDialogFailed(false);
    }
  }, [open]);

  // On the Tauri desktop the OS-native dialog replaces the in-app browser.
  useEffect(() => {
    if (!open || !isTauriDesktop()) {
      return;
    }
    // Keep one request for this opening. Parent renders and StrictMode effect
    // replays may resubscribe, but cleanup cannot close an OS-native dialog.
    const request = (nativeRequestRef.current ??= {
      handled: false,
      promise: pickDesktopNativePath({
        defaultPath: value,
        extensions: acceptedExtensions,
        mode,
        multiple,
        title,
      }),
    });
    let cancelled = false;
    void (async () => {
      try {
        const paths = await request.promise;
        if (cancelled || request.handled) {
          return;
        }
        request.handled = true;
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
        if (!cancelled && !request.handled) {
          request.handled = true;
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

  const standaloneInputRef = useRef<HTMLInputElement>(null);
  const [standaloneBusy, setStandaloneBusy] = useState(false);
  const [standaloneError, setStandaloneError] = useState("");
  const standaloneMode = isStandaloneRuntimeActive();

  const standaloneAccept = (() => {
    const exts = (acceptedExtensions ?? [])
      .map((ext) => ext.trim().replace(/^\.+/, "").toLowerCase())
      .filter(Boolean);
    if (!exts.length) {
      return ".char,.zip,.png,.jpg,.jpeg,.webp,.gif,.mp4,.webm,.wav,.mp3,.ogg,application/zip,application/octet-stream";
    }
    const tokens = new Set<string>();
    for (const ext of exts) {
      tokens.add(`.${ext}`);
      if (ext === "char" || ext === "cha" || ext === "zip" || ext === "bg" || ext === "ef") {
        tokens.add(".zip");
        tokens.add("application/zip");
        tokens.add("application/octet-stream");
      }
    }
    return Array.from(tokens).join(",");
  })();

  const handleStandaloneFilePick = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    setStandaloneBusy(true);
    setStandaloneError("");
    try {
      const vfsPaths = await stageUploadedFiles(files, "uploads");
      if (multiple && mode === "file" && onSelectMany) {
        onSelectMany(vfsPaths);
      } else if (vfsPaths[0]) {
        onSelect(vfsPaths[0]);
      }
      onClose();
    } catch (error) {
      setStandaloneError(error instanceof Error ? error.message : String(error));
    } finally {
      setStandaloneBusy(false);
    }
  };

  if (!open) {
    return null;
  }
  if (isTauriDesktop() && !nativeDialogFailed) {
    // The native dialog owns the whole flow; render nothing behind it.
    return null;
  }

  if (standaloneMode) {
    return (
      <Dialog
        bodyClassName="path-picker__body"
        className="path-picker path-picker--standalone"
        closeLabel={t("common.close")}
        footer={<Button onClick={onClose}>{t("common.cancel")}</Button>}
        onClose={onClose}
        open={open}
        title={title}
      >
        <div className="path-picker__standalone-box">
          {mode === "directory" ? (
            <p className="path-picker__standalone-note">
              当前处于浏览器/手机独立模式，暂不支持直接选取本地文件夹路径；如需操作电脑磁盘文件夹，请连接电脑端新世界或选择具体文件导入。
            </p>
          ) : (
            <>
              <p className="path-picker__standalone-note">
                选择的文件将仅缓存在当前设备的浏览器/应用本地 IndexedDB 存储中，不会上传至第三方服务器。
              </p>
              <input
                accept={standaloneAccept}
                className="path-picker__standalone-input"
                multiple={multiple && mode === "file"}
                onChange={(event) => void handleStandaloneFilePick(event)}
                ref={standaloneInputRef}
                type="file"
              />
              <div>
                <Button
                  disabled={standaloneBusy}
                  icon={<Upload aria-hidden className="button__icon" />}
                  onClick={() => standaloneInputRef.current?.click()}
                  variant="primary"
                >
                  {standaloneBusy ? "正在读取文件..." : "从设备选择文件"}
                </Button>
              </div>
              {standaloneError ? <p className="path-picker__error">{standaloneError}</p> : null}
            </>
          )}
        </div>
      </Dialog>
    );
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
