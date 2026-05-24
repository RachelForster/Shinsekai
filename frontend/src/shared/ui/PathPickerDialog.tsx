import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronUp, Eye, EyeOff, File, Folder, HardDrive, RefreshCw } from "lucide-react";

import type { FileBrowserEntry, FileBrowserSnapshot, PathPickerMode } from "../platform/types";
import { getPlatform } from "../platform/platform";
import { useI18n } from "../i18n";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { IconButton } from "./IconButton";

interface PathPickerDialogProps {
  mode?: PathPickerMode;
  multiple?: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
  onSelectMany?: (paths: string[]) => void;
  open: boolean;
  title: string;
  value?: string;
}

function basename(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

function formatSize(size?: number | null) {
  if (typeof size !== "number") {
    return "";
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value?: number) {
  if (!value) {
    return "";
  }
  return new Date(value * 1000).toLocaleString();
}

function isSelectable(entry: FileBrowserEntry, mode: PathPickerMode) {
  return mode === "file" ? entry.kind === "file" : entry.kind === "directory";
}

export function PathPickerDialog({
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
  const [address, setAddress] = useState(value);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedPaths, setSelectedPaths] = useState<string[]>(value ? [value] : []);
  const [showHidden, setShowHidden] = useState(false);
  const [snapshot, setSnapshot] = useState<FileBrowserSnapshot | null>(null);
  const selectedPathsRef = useRef(selectedPaths);
  const showHiddenRef = useRef(showHidden);
  const selectedPath = selectedPaths[0] ?? "";

  const updateSelectedPaths = (paths: string[]) => {
    selectedPathsRef.current = paths;
    setSelectedPaths(paths);
  };

  const updateShowHidden = (next: boolean) => {
    showHiddenRef.current = next;
    setShowHidden(next);
  };

  const selectedEntry = useMemo(
    () => snapshot?.entries.find((entry) => entry.path === selectedPath),
    [selectedPath, snapshot],
  );

  const browse = useCallback(async (path?: string, selection?: string[], hidden?: boolean) => {
    setLoading(true);
    setError("");
    const desiredSelection = selection ?? selectedPathsRef.current;
    try {
      const next = await getPlatform().files.browse({ path, showHidden: hidden ?? showHiddenRef.current });
      setSnapshot(next);
      setAddress(next.cwd);
      if (mode === "directory") {
        updateSelectedPaths([next.cwd]);
      } else {
        const visibleFilePaths = new Set(
          next.entries.filter((entry) => entry.kind === "file").map((entry) => entry.path),
        );
        updateSelectedPaths(desiredSelection.filter((item) => visibleFilePaths.has(item)));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    if (open) {
      const initialSelection = mode === "file" && value && !multiple ? [value] : [];
      setAddress(value);
      updateSelectedPaths(initialSelection);
      void browse(value, initialSelection, showHiddenRef.current);
    }
  }, [browse, mode, multiple, open, value]);

  if (!open) {
    return null;
  }

  const confirmPath =
    mode === "directory"
      ? selectedEntry?.kind === "directory"
        ? selectedEntry.path
        : snapshot?.cwd || address.trim()
      : selectedEntry?.kind === "file"
        ? selectedEntry.path
        : address.trim();
  const confirmPaths =
    multiple && mode === "file" ? selectedPaths : confirmPath ? [confirmPath] : [];

  const handleConfirm = () => {
    if (confirmPaths.length) {
      if (multiple && mode === "file") {
        onSelectMany?.(confirmPaths);
      } else {
        onSelect(confirmPaths[0]);
      }
      onClose();
    }
  };

  const openEntry = (entry: FileBrowserEntry) => {
    if (entry.kind === "directory") {
      void browse(entry.path, [], showHiddenRef.current);
      return;
    }
    if (mode === "file" && !multiple) {
      onSelect(entry.path);
      onClose();
    }
  };

  const toggleEntry = (entry: FileBrowserEntry) => {
    const selectable = isSelectable(entry, mode);
    if (!selectable) {
      updateSelectedPaths([]);
      return;
    }
    setAddress(entry.path);
    if (multiple && mode === "file") {
      setSelectedPaths((current) => {
        const next = current.includes(entry.path)
          ? current.filter((item) => item !== entry.path)
          : [...current, entry.path];
        selectedPathsRef.current = next;
        return next;
      });
      return;
    }
    updateSelectedPaths([entry.path]);
  };

  return (
    <Dialog
      bodyClassName="path-picker__body"
      className="path-picker"
      closeLabel={t("common.close")}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button disabled={!confirmPaths.length} icon={<Check aria-hidden className="button__icon" />} onClick={handleConfirm} variant="primary">
            {mode === "directory" ? t("filePicker.selectCurrent") : t("filePicker.selectFile")}
          </Button>
        </>
      }
      onClose={onClose}
      open={open}
      title={title}
    >
      <div className="path-picker__toolbar">
        <label className="path-picker__address">
          <span>{t("filePicker.address")}</span>
          <input
            className="input"
            onChange={(event) => setAddress(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void browse(address);
              }
            }}
            spellCheck={false}
            value={address}
          />
        </label>
        <IconButton disabled={!snapshot?.parent || loading} label={t("filePicker.parent")} onClick={() => void browse(snapshot?.parent, [], showHiddenRef.current)}>
          <ChevronUp aria-hidden className="icon-button__icon" />
        </IconButton>
        <IconButton disabled={loading} label={t("common.refresh")} onClick={() => void browse(snapshot?.cwd || address, selectedPathsRef.current, showHiddenRef.current)}>
          <RefreshCw aria-hidden className="icon-button__icon" />
        </IconButton>
        <IconButton
          label={t("filePicker.hidden")}
          onClick={() => {
            const next = !showHiddenRef.current;
            updateShowHidden(next);
            void browse(snapshot?.cwd || address, selectedPathsRef.current, next);
          }}
        >
          {showHidden ? <Eye aria-hidden className="icon-button__icon" /> : <EyeOff aria-hidden className="icon-button__icon" />}
        </IconButton>
      </div>

      <div className="path-picker__main">
        <aside className="path-picker__roots" aria-label={t("filePicker.roots")}>
          {(snapshot?.roots ?? []).map((root) => (
            <button
              className="path-picker__root"
              key={root.path}
              onClick={() => void browse(root.path, [], showHiddenRef.current)}
              type="button"
            >
              <HardDrive aria-hidden className="path-picker__root-icon" />
              <span>{root.label}</span>
            </button>
          ))}
        </aside>

        <div className="path-picker__list-wrap">
          {error ? <div className="path-picker__error">{error}</div> : null}
          {loading ? <div className="path-picker__status">{t("filePicker.loading")}</div> : null}
          <table className="path-picker__list">
            <thead>
              <tr>
                <th>{t("filePicker.name")}</th>
                <th>{t("filePicker.type")}</th>
                <th>{t("filePicker.size")}</th>
                <th>{t("filePicker.modified")}</th>
              </tr>
            </thead>
            <tbody>
              {(snapshot?.entries ?? []).map((entry) => {
                const selected = selectedPaths.includes(entry.path);
                const selectable = isSelectable(entry, mode);
                return (
                  <tr
                    aria-selected={selected}
                    className={selectable ? "path-picker__row path-picker__row--selectable" : "path-picker__row"}
                    key={entry.path}
                    onClick={() => toggleEntry(entry)}
                    onDoubleClick={() => openEntry(entry)}
                  >
                    <td>
                      <span className="path-picker__name">
                        {entry.kind === "directory" ? (
                          <Folder aria-hidden className="path-picker__entry-icon" />
                        ) : (
                          <File aria-hidden className="path-picker__entry-icon" />
                        )}
                        <span>{entry.name || basename(entry.path)}</span>
                      </span>
                    </td>
                    <td>{entry.kind === "directory" ? t("filePicker.typeDirectory") : t("filePicker.typeFile")}</td>
                    <td>{formatSize(entry.size)}</td>
                    <td>{formatDate(entry.modifiedAt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!loading && !error && snapshot?.entries.length === 0 ? (
            <div className="path-picker__empty">{t("filePicker.empty")}</div>
          ) : null}
        </div>
      </div>
    </Dialog>
  );
}
