import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ChevronRight, ChevronUp, Eye, EyeOff, File, Folder, HardDrive, RefreshCw } from "lucide-react";

import type { FileBrowserEntry, FileBrowserRoot, FileBrowserSnapshot, PathPickerMode } from "../platform/types";
import { useI18n } from "../i18n";
import { IconButton } from "./IconButton";

export type FileBrowseHandler = (options?: { path?: string; showHidden?: boolean }) => Promise<FileBrowserSnapshot>;

const BROWSE_TIMEOUT_MS = 12_000;

const FileBrowserContext = createContext<FileBrowseHandler | null>(null);

export function FileBrowserProvider({ browse, children }: { browse: FileBrowseHandler; children: ReactNode }) {
  return <FileBrowserContext.Provider value={browse}>{children}</FileBrowserContext.Provider>;
}

export interface FileManagerSelection {
  address: string;
  confirmPaths: string[];
  cwd: string;
  selectedPaths: string[];
}

export interface FileManagerProps {
  acceptedExtensions?: string[];
  mode?: PathPickerMode;
  multiple?: boolean;
  onBrowse?: FileBrowseHandler;
  onOpenFile?: (path: string) => void;
  onSelectionChange?: (selection: FileManagerSelection) => void;
  value?: string;
}

function basename(path: string) {
  const normalized = normalizeFileManagerPath(path);
  return normalized.split(/[\\/]/).filter(Boolean).pop() || normalized || path;
}

export function normalizeFileManagerPath(path: string) {
  const raw = path.trim();
  if (!raw) {
    return "";
  }
  let normalized = raw.replace(/\\/g, "/");
  if (/^\/\/\?\/UNC\//i.test(normalized)) {
    normalized = `//${normalized.slice("//?/UNC/".length)}`;
  } else if (normalized.startsWith("//?/")) {
    normalized = normalized.slice("//?/".length);
  } else if (normalized.startsWith("//./")) {
    normalized = normalized.slice("//./".length);
  }
  if (/^[A-Za-z]:$/.test(normalized)) {
    return `${normalized}/`;
  }
  return normalized.replace(/^([A-Za-z]:)\/+$/, "$1/");
}

function normalizeFileBrowserSnapshot(snapshot: FileBrowserSnapshot): FileBrowserSnapshot {
  return {
    ...snapshot,
    cwd: normalizeFileManagerPath(snapshot.cwd),
    entries: snapshot.entries.map((entry) => ({
      ...entry,
      path: normalizeFileManagerPath(entry.path),
    })),
    parent: snapshot.parent ? normalizeFileManagerPath(snapshot.parent) : snapshot.parent,
    roots: normalizeFileBrowserRoots(snapshot.roots),
  };
}

function isWindowsDrivePath(path: string) {
  return /^[A-Za-z]:(?:\/|$)/.test(normalizeFileManagerPath(path));
}

function fileManagerRootKey(path: string) {
  const normalized = normalizeFileManagerPath(path);
  if (isWindowsDrivePath(normalized) || normalized.startsWith("//")) {
    return normalized.replace(/\/+$/, "").toLowerCase();
  }
  return normalized;
}

function normalizeFileBrowserRoots(roots: FileBrowserRoot[]) {
  const seen = new Set<string>();
  const normalizedRoots: FileBrowserRoot[] = [];
  for (const root of roots) {
    const normalizedPath = normalizeFileManagerPath(root.path);
    const key = fileManagerRootKey(normalizedPath);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    normalizedRoots.push({ ...root, path: normalizedPath });
  }
  return normalizedRoots;
}

function driveRootName(path: string) {
  return normalizeFileManagerPath(path).match(/^([A-Za-z]):\/?$/)?.[1];
}

function rootLabel(
  root: FileBrowserRoot,
  t: (
    key: "filePicker.rootData" | "filePicker.rootDownloads" | "filePicker.rootHome" | "filePicker.rootUserProfile",
  ) => string,
) {
  const label = root.label.trim();
  const driveLabel = driveRootName(label) ?? driveRootName(root.path);
  if (driveLabel) {
    return `${driveLabel}:`;
  }
  if (/^home$/i.test(label)) {
    return isWindowsDrivePath(root.path) ? t("filePicker.rootUserProfile") : t("filePicker.rootHome");
  }
  if (/^data$/i.test(label)) {
    return t("filePicker.rootData");
  }
  if (/^downloads$/i.test(label)) {
    return t("filePicker.rootDownloads");
  }
  return label || normalizeFileManagerPath(root.path);
}

function pathBreadcrumbs(path: string) {
  const raw = normalizeFileManagerPath(path);
  if (!raw) {
    return [];
  }
  const normalized = raw;
  const drive = normalized.match(/^[A-Za-z]:/)?.[0];
  if (drive) {
    const rest = normalized.slice(drive.length).replace(/^\/+/, "");
    let current = `${drive}/`;
    const crumbs = [{ label: drive, path: current }];
    for (const part of rest.split("/").filter(Boolean)) {
      current = current.endsWith("/") ? `${current}${part}` : `${current}/${part}`;
      crumbs.push({ label: part, path: current });
    }
    return crumbs;
  }

  if (normalized.startsWith("/")) {
    let current = "/";
    const crumbs = [{ label: "/", path: "/" }];
    for (const part of normalized.split("/").filter(Boolean)) {
      current = current === "/" ? `/${part}` : `${current}/${part}`;
      crumbs.push({ label: part, path: current });
    }
    return crumbs;
  }

  let current = "";
  return normalized
    .split("/")
    .filter(Boolean)
    .map((part) => {
      current = current ? `${current}/${part}` : part;
      return { label: part, path: current };
    });
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

export function normalizeFileExtensions(extensions?: string[]) {
  return (extensions ?? [])
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .map((item) => (item.startsWith(".") ? item : `.${item}`));
}

function matchesExtension(entry: FileBrowserEntry, acceptedExtensions: string[]) {
  if (!acceptedExtensions.length || entry.kind !== "file") {
    return true;
  }
  const lowerName = entry.name.toLowerCase();
  return acceptedExtensions.some((extension) => lowerName.endsWith(extension));
}

function isSelectable(entry: FileBrowserEntry, mode: PathPickerMode, acceptedExtensions: string[]) {
  if (mode === "file") {
    return entry.kind === "file" && matchesExtension(entry, acceptedExtensions);
  }
  if (mode === "path") {
    return entry.kind === "directory" || matchesExtension(entry, acceptedExtensions);
  }
  return entry.kind === "directory";
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, timeoutMessage: string): Promise<T> {
  let timeoutId: number | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = window.setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timeoutId !== undefined) {
      window.clearTimeout(timeoutId);
    }
  });
}

export function FileManager({
  acceptedExtensions,
  mode = "file",
  multiple = false,
  onBrowse,
  onOpenFile,
  onSelectionChange,
  value = "",
}: FileManagerProps) {
  const { t } = useI18n();
  const normalizedValue = normalizeFileManagerPath(value);
  const contextBrowse = useContext(FileBrowserContext);
  const browseFiles = onBrowse ?? contextBrowse;
  const [address, setAddress] = useState(normalizedValue);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedPaths, setSelectedPaths] = useState<string[]>(normalizedValue ? [normalizedValue] : []);
  const [showHidden, setShowHidden] = useState(false);
  const [snapshot, setSnapshot] = useState<FileBrowserSnapshot | null>(null);
  const [editingAddress, setEditingAddress] = useState(false);
  const addressInputRef = useRef<HTMLInputElement>(null);
  const activeBrowseRequestRef = useRef(0);
  const mountedRef = useRef(false);
  const selectedPathsRef = useRef(selectedPaths);
  const showHiddenRef = useRef(showHidden);
  const acceptedExtensionsKey = (acceptedExtensions ?? []).join("\0");
  const normalizedAcceptedExtensions = useMemo(
    () => normalizeFileExtensions(acceptedExtensions),
    [acceptedExtensionsKey],
  );
  const selectedPath = selectedPaths[0] ?? "";
  const displayAddress = normalizeFileManagerPath(snapshot?.cwd || address);
  const breadcrumbs = useMemo(() => pathBreadcrumbs(displayAddress), [displayAddress]);

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

  const confirmPath =
    mode === "directory"
      ? selectedEntry?.kind === "directory"
        ? selectedEntry.path
        : normalizeFileManagerPath(snapshot?.cwd || address)
      : mode === "path"
        ? (selectedEntry?.path ?? normalizeFileManagerPath(address))
        : selectedEntry?.kind === "file"
          ? selectedEntry.path
          : normalizeFileManagerPath(address);
  const confirmPaths = multiple && mode === "file" ? selectedPaths : confirmPath ? [confirmPath] : [];
  const confirmPathsKey = confirmPaths.join("\0");

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeBrowseRequestRef.current += 1;
    };
  }, []);

  const isCurrentBrowseRequest = useCallback(
    (requestId: number) => mountedRef.current && requestId === activeBrowseRequestRef.current,
    [],
  );

  useEffect(() => {
    onSelectionChange?.({
      address,
      confirmPaths,
      cwd: snapshot?.cwd || "",
      selectedPaths,
    });
  }, [address, confirmPathsKey, onSelectionChange, selectedPaths, snapshot?.cwd]);

  const browse = useCallback(
    async (path?: string, selection?: string[], hidden?: boolean) => {
      const requestId = activeBrowseRequestRef.current + 1;
      activeBrowseRequestRef.current = requestId;
      setLoading(true);
      setError("");
      const desiredSelection = selection ?? selectedPathsRef.current;
      try {
        if (!browseFiles) {
          throw new Error("File browser is not configured.");
        }
        const next = normalizeFileBrowserSnapshot(
          await withTimeout(
            browseFiles({
              path: path ? normalizeFileManagerPath(path) : path,
              showHidden: hidden ?? showHiddenRef.current,
            }),
            BROWSE_TIMEOUT_MS,
            t("filePicker.timeout"),
          ),
        );
        if (!isCurrentBrowseRequest(requestId)) {
          return;
        }
        setSnapshot(next);
        setAddress(next.cwd);
        setEditingAddress(false);
        if (mode === "directory") {
          updateSelectedPaths([next.cwd]);
        } else if (mode === "path") {
          const visiblePaths = new Set(next.entries.map((entry) => entry.path));
          updateSelectedPaths(desiredSelection.filter((item) => visiblePaths.has(item)));
        } else {
          const visibleFilePaths = new Set(
            next.entries
              .filter((entry) => entry.kind === "file" && matchesExtension(entry, normalizedAcceptedExtensions))
              .map((entry) => entry.path),
          );
          updateSelectedPaths(desiredSelection.filter((item) => visibleFilePaths.has(item)));
        }
      } catch (err) {
        if (!isCurrentBrowseRequest(requestId)) {
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (isCurrentBrowseRequest(requestId)) {
          setLoading(false);
        }
      }
    },
    [browseFiles, isCurrentBrowseRequest, mode, normalizedAcceptedExtensions, t],
  );

  const beginAddressEdit = useCallback(() => {
    setAddress(displayAddress);
    setEditingAddress(true);
    window.requestAnimationFrame(() => {
      addressInputRef.current?.focus();
      addressInputRef.current?.select();
    });
  }, [displayAddress]);

  useEffect(() => {
    const initialSelection = mode !== "directory" && normalizedValue && !multiple ? [normalizedValue] : [];
    setAddress(normalizedValue);
    updateSelectedPaths(initialSelection);
    void browse(normalizedValue, initialSelection, showHiddenRef.current);
  }, [browse, mode, multiple, normalizedValue]);

  const openEntry = (entry: FileBrowserEntry) => {
    if (entry.kind === "directory") {
      void browse(entry.path, [], showHiddenRef.current);
      return;
    }
    if (mode === "file" && !multiple) {
      onOpenFile?.(entry.path);
    }
  };

  const toggleEntry = (entry: FileBrowserEntry) => {
    const selectable = isSelectable(entry, mode, normalizedAcceptedExtensions);
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
    <>
      <div className="path-picker__toolbar">
        <div className="path-picker__address">
          <span className="path-picker__address-label">{t("filePicker.address")}</span>
          {editingAddress ? (
            <input
              ref={addressInputRef}
              className="input path-picker__address-input"
              onBlur={() => setEditingAddress(false)}
              onChange={(event) => setAddress(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void browse(address);
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  setAddress(displayAddress);
                  setEditingAddress(false);
                }
              }}
              spellCheck={false}
              value={address}
            />
          ) : (
            <div
              aria-label={displayAddress || t("filePicker.address")}
              className="path-picker__address-control"
              onClick={beginAddressEdit}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  beginAddressEdit();
                }
              }}
              role="group"
              tabIndex={0}
              title={displayAddress}
            >
              <div className="path-picker__breadcrumbs">
                {breadcrumbs.map((crumb, index) => (
                  <span className="path-picker__breadcrumb-item" key={`${crumb.path}:${index}`}>
                    {index > 0 ? <ChevronRight aria-hidden className="path-picker__breadcrumb-separator" /> : null}
                    <button
                      className="path-picker__breadcrumb"
                      onClick={(event) => {
                        event.stopPropagation();
                        void browse(crumb.path, [], showHiddenRef.current);
                      }}
                      type="button"
                    >
                      {crumb.label}
                    </button>
                  </span>
                ))}
                <span aria-hidden className="path-picker__address-spacer" />
              </div>
            </div>
          )}
        </div>
        <IconButton
          disabled={!snapshot?.parent || loading}
          label={t("filePicker.parent")}
          onClick={() => void browse(snapshot?.parent, [], showHiddenRef.current)}
        >
          <ChevronUp aria-hidden className="icon-button__icon" />
        </IconButton>
        <IconButton
          disabled={loading}
          label={t("common.refresh")}
          onClick={() => void browse(snapshot?.cwd || address, selectedPathsRef.current, showHiddenRef.current)}
        >
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
          {showHidden ? (
            <Eye aria-hidden className="icon-button__icon" />
          ) : (
            <EyeOff aria-hidden className="icon-button__icon" />
          )}
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
              <span>{rootLabel(root, t)}</span>
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
                const selectable = isSelectable(entry, mode, normalizedAcceptedExtensions);
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
    </>
  );
}
