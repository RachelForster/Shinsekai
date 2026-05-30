import { memo, useCallback, useEffect, useMemo, useState } from "react";
import type { ChangeEvent, UIEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Download,
  ExternalLink,
  Image as ImageIcon,
  Languages,
  Music,
  Plus,
  Save,
  Trash2,
  Upload,
} from "lucide-react";

import {
  backgroundsQueryKey,
  deleteAllBackgroundBgm,
  deleteAllBackgroundImages,
  deleteBackground,
  deleteBackgroundBgm,
  deleteBackgroundImage,
  exportBackground,
  importBackgrounds,
  listBackgrounds,
  saveBackground,
  saveBackgroundBgmTags,
  saveBackgroundImageTags,
  translateBackgroundFields,
  uploadBackgroundBgm,
  uploadBackgroundImages,
} from "../../entities/background/repository";
import type { Background } from "../../entities/config/types";
import { fileUrl, openExternal } from "../../entities/files/repository";
import { baseName, numberedTags, tagContents } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import {
  AlertDialog,
  AsyncButton,
  Button,
  EmptyState,
  FilePicker,
  ImageAssetGallery,
  PathDisplay,
  QueryErrorState,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";
import "../settings-pages.css";

function createBackground(): Background {
  return {
    bg_tags: "",
    bgm_list: [],
    bgm_tags: "",
    name: "",
    sprite_prefix: "temp",
    sprites: [],
  };
}

const BGM_ROW_HEIGHT = 58;
const VIRTUAL_OVERSCAN_ROWS = 4;
const VIRTUAL_BGM_ROWS = 10;

type BackgroundDeleteTarget =
  | { kind: "background"; name: string }
  | { filename: string; index: number; kind: "image"; name: string }
  | { count: number; kind: "all-images"; name: string }
  | { filename: string; index: number; kind: "bgm"; name: string }
  | { count: number; indexes: number[]; kind: "selected-bgm"; name: string }
  | { count: number; kind: "all-bgm"; name: string };

type BgmSortDirection = "asc" | "desc";
type BgmSortKey = "filename" | "index";

interface BackgroundBgmItem {
  filename: string;
  originalIndex: number;
  path: string;
}

function useVirtualRange(count: number, rowHeight: number, visibleRows: number) {
  const [scrollTop, setScrollTop] = useState(0);
  const viewportHeight = Math.max(rowHeight, Math.min(count || 1, visibleRows) * rowHeight);
  const maxScrollTop = Math.max(0, count * rowHeight - viewportHeight);
  const clampedScrollTop = Math.min(scrollTop, maxScrollTop);
  const startIndex = Math.max(0, Math.floor(clampedScrollTop / rowHeight) - VIRTUAL_OVERSCAN_ROWS);
  const endIndex = Math.min(count, startIndex + visibleRows + VIRTUAL_OVERSCAN_ROWS * 2);
  const onScroll = useCallback((event: UIEvent<HTMLElement>) => {
    setScrollTop(event.currentTarget.scrollTop);
  }, []);

  return {
    endIndex,
    maxHeight: count > visibleRows ? viewportHeight : undefined,
    onScroll,
    paddingBottom: Math.max(0, (count - endIndex) * rowHeight),
    paddingTop: startIndex * rowHeight,
    startIndex,
  };
}

interface BackgroundBgmRowsProps {
  allSelected: boolean;
  clearSelectionLabel: string;
  deleting: boolean;
  filenameLabel: string;
  items: BackgroundBgmItem[];
  indexLabel: string;
  onDelete: (index: number) => void;
  onSort: (key: BgmSortKey) => void;
  onToggleAllSelection: () => void;
  onTagChange: (index: number, value: string) => void;
  onToggleSelection: (index: number, checked: boolean) => void;
  pathLabel: string;
  previewLabel: string;
  removeLabel: string;
  rowTags: string[];
  selectLabel: string;
  selectAllLabel: string;
  selectedIndexes: Set<number>;
  sortDirection: BgmSortDirection;
  sortKey: BgmSortKey;
  tagLabel: string;
}

interface BackgroundBgmRowProps {
  deleting: boolean;
  index: number;
  onDelete: (index: number) => void;
  onTagChange: (index: number, value: string) => void;
  onToggleSelection: (index: number, checked: boolean) => void;
  path: string;
  removeLabel: string;
  selected: boolean;
  tag: string;
}

const BackgroundBgmRow = memo(function BackgroundBgmRow({
  deleting,
  index,
  onDelete,
  onTagChange,
  onToggleSelection,
  path,
  removeLabel,
  selected,
  tag,
}: BackgroundBgmRowProps) {
  const handleDelete = useCallback(() => onDelete(index), [index, onDelete]);
  const handleTagChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => onTagChange(index, event.target.value),
    [index, onTagChange],
  );
  const handleToggle = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => onToggleSelection(index, event.target.checked),
    [index, onToggleSelection],
  );
  const filename = baseName(path);

  return (
    <tr aria-selected={selected}>
      <td>
        <input checked={selected} onChange={handleToggle} type="checkbox" />
      </td>
      <td>{index + 1}</td>
      <td className="background-bgm-table__filename" title={filename}>
        <span className="background-bgm-table__filename-inner">
          <Music aria-hidden className="asset-row__icon" />
          <span>{filename}</span>
        </span>
      </td>
      <td>
        <PathDisplay className="background-bgm-table__path" path={path} />
      </td>
      <td className="background-bgm-table__tag">
        <TextInput onChange={handleTagChange} value={tag} />
      </td>
      <td className="background-bgm-table__preview">
        {path ? <audio className="audio-inline" controls preload="none" src={fileUrl(path)} /> : null}
      </td>
      <td>
        <AsyncButton
          icon={<Trash2 aria-hidden className="button__icon" />}
          loading={deleting}
          onClick={handleDelete}
          variant="ghost"
        >
          {removeLabel}
        </AsyncButton>
      </td>
    </tr>
  );
});

function BgmSpacerRow({ height }: { height: number }) {
  if (!height) {
    return null;
  }
  return (
    <tr aria-hidden className="background-virtual-table__spacer">
      <td colSpan={7} style={{ height }} />
    </tr>
  );
}

const BackgroundBgmRows = memo(function BackgroundBgmRows({
  allSelected,
  clearSelectionLabel,
  deleting,
  filenameLabel,
  items,
  indexLabel,
  onDelete,
  onSort,
  onToggleAllSelection,
  onTagChange,
  onToggleSelection,
  pathLabel,
  previewLabel,
  removeLabel,
  rowTags,
  selectLabel,
  selectAllLabel,
  selectedIndexes,
  sortDirection,
  sortKey,
  tagLabel,
}: BackgroundBgmRowsProps) {
  const virtual = useVirtualRange(items.length, BGM_ROW_HEIGHT, VIRTUAL_BGM_ROWS);
  const visibleItems = items.slice(virtual.startIndex, virtual.endIndex);
  const indexAriaSort = sortKey === "index" ? (sortDirection === "asc" ? "ascending" : "descending") : undefined;
  const filenameAriaSort = sortKey === "filename" ? (sortDirection === "asc" ? "ascending" : "descending") : undefined;
  const SortIcon = sortDirection === "asc" ? ArrowUp : ArrowDown;

  return (
    <div
      className="data-table-wrap background-virtual-table"
      onScroll={virtual.onScroll}
      style={{ maxHeight: virtual.maxHeight }}
    >
      <table className="data-table background-bgm-table">
        <colgroup>
          <col className="background-bgm-table__select-col" />
          <col className="background-bgm-table__index-col" />
          <col className="background-bgm-table__filename-col" />
          <col className="background-bgm-table__path-col" />
          <col className="background-bgm-table__tag-col" />
          <col className="background-bgm-table__preview-col" />
          <col className="background-bgm-table__remove-col" />
        </colgroup>
        <thead>
          <tr>
            <th>
              <button
                aria-label={allSelected ? clearSelectionLabel : selectAllLabel}
                aria-pressed={allSelected}
                className="background-bgm-table__header-button"
                onClick={onToggleAllSelection}
                title={allSelected ? clearSelectionLabel : selectAllLabel}
                type="button"
              >
                {selectLabel}
              </button>
            </th>
            <th aria-sort={indexAriaSort}>
              <button className="background-bgm-table__header-button" onClick={() => onSort("index")} type="button">
                <span>{indexLabel}</span>
                {sortKey === "index" ? <SortIcon aria-hidden className="background-bgm-table__sort-indicator" /> : null}
              </button>
            </th>
            <th aria-sort={filenameAriaSort}>
              <button className="background-bgm-table__header-button" onClick={() => onSort("filename")} type="button">
                <span>{filenameLabel}</span>
                {sortKey === "filename" ? (
                  <SortIcon aria-hidden className="background-bgm-table__sort-indicator" />
                ) : null}
              </button>
            </th>
            <th>{pathLabel}</th>
            <th>{tagLabel}</th>
            <th>{previewLabel}</th>
            <th>{removeLabel}</th>
          </tr>
        </thead>
        <tbody>
          <BgmSpacerRow height={virtual.paddingTop} />
          {visibleItems.map((item) => {
            return (
              <BackgroundBgmRow
                deleting={deleting}
                index={item.originalIndex}
                key={`${item.path}-${item.originalIndex}`}
                onDelete={onDelete}
                onTagChange={onTagChange}
                onToggleSelection={onToggleSelection}
                path={item.path}
                removeLabel={removeLabel}
                selected={selectedIndexes.has(item.originalIndex)}
                tag={rowTags[item.originalIndex] ?? ""}
              />
            );
          })}
          <BgmSpacerRow height={virtual.paddingBottom} />
        </tbody>
      </table>
    </div>
  );
});

export function BackgroundManagerPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const backgroundsQuery = useQuery({ queryFn: listBackgrounds, queryKey: backgroundsQueryKey });
  const data = backgroundsQuery.data ?? [];
  const isLoading = backgroundsQuery.isLoading;
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<Background>(createBackground());
  const [isCreating, setIsCreating] = useState(false);
  const [pendingBgmPaths, setPendingBgmPaths] = useState<string[]>([]);
  const [pendingImportFiles, setPendingImportFiles] = useState<string[]>([]);
  const [pendingImagePaths, setPendingImagePaths] = useState<string[]>([]);
  const [pendingDelete, setPendingDelete] = useState<BackgroundDeleteTarget | null>(null);
  const [selectedBgmIndexes, setSelectedBgmIndexes] = useState<number[]>([]);
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);
  const [bgmSort, setBgmSort] = useState<{ direction: BgmSortDirection; key: BgmSortKey }>({
    direction: "asc",
    key: "index",
  });
  const [nameError, setNameError] = useState("");

  const selected = useMemo(
    () => (isCreating ? undefined : (data.find((background) => background.name === selectedName) ?? data[0])),
    [data, isCreating, selectedName],
  );
  const currentBackgroundName = isCreating ? "" : selectedName;
  useEffect(() => {
    if (selected) {
      setSelectedName(selected.name);
      setDraft(structuredClone(selected));
      setPendingBgmPaths([]);
      setPendingImagePaths([]);
      setSelectedBgmIndexes([]);
      setSelectedImageIndex(0);
      setNameError("");
    }
  }, [selected]);

  useEffect(() => {
    setSelectedImageIndex((current) => Math.min(current, Math.max(0, draft.sprites.length - 1)));
  }, [draft.sprites.length]);

  const saveMutation = useMutation({
    mutationFn: ({ background, originalName }: { background: Background; originalName?: string }) =>
      saveBackground(background, originalName),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setIsCreating(false);
      setSelectedName(background.name);
      showToast({ kind: "success", title: t("background.toast.saved") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteBackground,
    onSuccess() {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      showToast({ kind: "success", title: t("background.toast.deleted") });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.deleteFallback"),
        title: t("common.deleteFailed"),
      });
    },
  });

  const importMutation = useMutation({
    mutationFn: importBackgrounds,
    onSuccess(imported) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setPendingImportFiles([]);
      const lastImported = imported[imported.length - 1];
      if (lastImported) {
        setIsCreating(false);
        setSelectedName(lastImported.name);
        setDraft(lastImported);
      }
      showToast({ kind: "success", title: t("background.toast.importComplete", { count: imported.length }) });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.importFallback"),
        title: t("common.importFailed"),
      });
    },
  });

  const exportMutation = useMutation({
    mutationFn: exportBackground,
    onSuccess(path) {
      showToast({ kind: "success", message: path, title: t("background.toast.exportComplete") });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.exportFallback"),
        title: t("common.exportFailed"),
      });
    },
  });

  const translateMutation = useMutation({
    mutationFn: () =>
      translateBackgroundFields({
        bgTags: draft.bg_tags,
        bgmRowTags: tagContents(draft.bgm_tags, draft.bgm_list.length),
        bgmTags: draft.bgm_tags,
        name: draft.name,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.translateFallback"),
        title: t("background.action.aiTranslate"),
      });
    },
    onSuccess(result) {
      if (result.error) {
        showToast({ kind: "error", message: result.error, title: t("background.action.aiTranslate") });
        return;
      }
      setDraft((current) => ({
        ...current,
        bg_tags: result.bgTags,
        bgm_tags:
          result.bgmRowTags && result.bgmRowTags.length === current.bgm_list.length
            ? numberedTags("音乐", result.bgmRowTags)
            : result.bgmTags,
        name: result.name,
      }));
      if (result.name.trim()) {
        setNameError("");
      }
      showToast({ kind: "success", title: t("background.action.aiTranslate") });
    },
  });

  const imageUploadMutation = useMutation({
    mutationFn: () =>
      uploadBackgroundImages({
        bgTags: draft.bg_tags,
        name: currentBackgroundName,
        paths: pendingImagePaths,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.asset.uploadError"),
        title: t("background.asset.uploadImages"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bg_tags: background.bg_tags, sprites: background.sprites }));
      setPendingImagePaths([]);
      showToast({ kind: "success", title: t("background.asset.uploadImages") });
    },
  });

  const imageTagsSaveMutation = useMutation({
    mutationFn: () => saveBackgroundImageTags({ bgTags: draft.bg_tags, name: currentBackgroundName }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bg_tags: background.bg_tags }));
      showToast({ kind: "success", title: t("background.action.saveImageTags") });
    },
  });

  const bgmUploadMutation = useMutation({
    mutationFn: () =>
      uploadBackgroundBgm({
        bgmTags: draft.bgm_tags,
        name: currentBackgroundName,
        paths: pendingBgmPaths,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.asset.uploadError"),
        title: t("background.asset.uploadBgm"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bgm_list: background.bgm_list, bgm_tags: background.bgm_tags }));
      setPendingBgmPaths([]);
      showToast({ kind: "success", title: t("background.asset.uploadBgm") });
    },
  });

  const bgmTagsSaveMutation = useMutation({
    mutationFn: () => saveBackgroundBgmTags({ bgmTags: draft.bgm_tags, name: currentBackgroundName }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bgm_tags: background.bgm_tags }));
      showToast({ kind: "success", title: t("background.action.saveBgmTags") });
    },
  });

  const imageDeleteMutation = useMutation({
    mutationFn: ({ index, name }: { index: number; name: string }) => deleteBackgroundImage(name, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.asset.uploadError"),
        title: t("common.remove"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bg_tags: background.bg_tags, sprites: background.sprites }));
      showToast({ kind: "success", title: t("common.remove") });
    },
  });

  const imageDeleteAllMutation = useMutation({
    mutationFn: (name: string) => deleteAllBackgroundImages(name),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.asset.uploadError"),
        title: t("background.asset.clearImages"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bg_tags: background.bg_tags, sprites: background.sprites }));
      showToast({ kind: "success", title: t("background.asset.clearImages") });
    },
  });

  const bgmDeleteMutation = useMutation({
    mutationFn: ({ index, name }: { index: number; name: string }) => deleteBackgroundBgm(name, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.asset.uploadError"),
        title: t("common.remove"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bgm_list: background.bgm_list, bgm_tags: background.bgm_tags }));
      setSelectedBgmIndexes([]);
      showToast({ kind: "success", title: t("common.remove") });
    },
  });

  const bgmBatchDeleteMutation = useMutation({
    mutationFn: async ({ indexes, name }: { indexes: number[]; name: string }) => {
      let background: Background | null = null;
      for (const index of [...indexes].sort((a, b) => b - a)) {
        background = await deleteBackgroundBgm(name, index);
      }
      if (!background) {
        throw new Error(t("background.asset.noSelectedBgm"));
      }
      return background;
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.asset.uploadError"),
        title: t("background.asset.deleteSelectedBgm"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bgm_list: background.bgm_list, bgm_tags: background.bgm_tags }));
      setSelectedBgmIndexes([]);
      showToast({ kind: "success", title: t("background.asset.deleteSelectedBgm") });
    },
  });

  const bgmDeleteAllMutation = useMutation({
    mutationFn: (name: string) => deleteAllBackgroundBgm(name),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.asset.uploadError"),
        title: t("background.asset.clearBgm"),
      });
    },
    onSuccess(background) {
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bgm_list: background.bgm_list, bgm_tags: background.bgm_tags }));
      setSelectedBgmIndexes([]);
      showToast({ kind: "success", title: t("background.asset.clearBgm") });
    },
  });

  const update = <K extends keyof Background>(name: K, value: Background[K]) => {
    setDraft((current) => ({ ...current, [name]: value }));
    if (name === "name" && String(value).trim()) {
      setNameError("");
    }
  };

  const updateBgmRowTag = useCallback((index: number, value: string) => {
    setDraft((current) => {
      const tags = tagContents(current.bgm_tags, current.bgm_list.length);
      tags[index] = value;
      return { ...current, bgm_tags: numberedTags("音乐", tags) };
    });
  }, []);

  const updateImageRowTag = useCallback((index: number, value: string) => {
    setDraft((current) => {
      const tags = tagContents(current.bg_tags, current.sprites.length);
      tags[index] = value;
      return { ...current, bg_tags: numberedTags("场景", tags) };
    });
  }, []);

  const toggleBgmSelection = useCallback((index: number, checked: boolean) => {
    setSelectedBgmIndexes((current) => {
      if (checked) {
        return current.includes(index) ? current : [...current, index];
      }
      return current.filter((item) => item !== index);
    });
  }, []);

  const toggleAllBgmSelection = useCallback(() => {
    setSelectedBgmIndexes((current) => {
      const validSelection = current.filter((index) => index >= 0 && index < draft.bgm_list.length);
      const allSelected = draft.bgm_list.length > 0 && validSelection.length === draft.bgm_list.length;
      return allSelected ? [] : draft.bgm_list.map((_, index) => index);
    });
  }, [draft.bgm_list]);

  const toggleBgmSort = useCallback((key: BgmSortKey) => {
    setBgmSort((current) => {
      if (current.key === key) {
        return { ...current, direction: current.direction === "asc" ? "desc" : "asc" };
      }
      return { direction: "asc", key };
    });
  }, []);

  const handleImageDelete = useCallback(
    (index: number) => {
      const image = draft.sprites[index];
      if (!currentBackgroundName || !image) {
        showToast({ kind: "error", title: t("common.remove") });
        return;
      }
      setPendingDelete({
        filename: baseName(image.path) || `${index + 1}`,
        index,
        kind: "image",
        name: currentBackgroundName,
      });
    },
    [currentBackgroundName, draft.sprites, showToast, t],
  );
  const handleBgmDelete = useCallback(
    (index: number) => {
      const path = draft.bgm_list[index];
      if (!currentBackgroundName || !path) {
        showToast({ kind: "error", title: t("common.remove") });
        return;
      }
      setPendingDelete({
        filename: baseName(path) || `${index + 1}`,
        index,
        kind: "bgm",
        name: currentBackgroundName,
      });
    },
    [currentBackgroundName, draft.bgm_list, showToast, t],
  );

  const confirmPendingDelete = () => {
    if (!pendingDelete) {
      return;
    }
    const target = pendingDelete;
    setPendingDelete(null);
    if (target.kind === "background") {
      deleteMutation.mutate(target.name);
      return;
    }
    if (target.kind === "image") {
      imageDeleteMutation.mutate({ index: target.index, name: target.name });
      return;
    }
    if (target.kind === "all-images") {
      imageDeleteAllMutation.mutate(target.name);
      return;
    }
    if (target.kind === "bgm") {
      bgmDeleteMutation.mutate({ index: target.index, name: target.name });
      return;
    }
    if (target.kind === "selected-bgm") {
      bgmBatchDeleteMutation.mutate({ indexes: target.indexes, name: target.name });
      return;
    }
    bgmDeleteAllMutation.mutate(target.name);
  };

  const pendingDeleteCopy = pendingDelete
    ? {
        body:
          pendingDelete.kind === "background"
            ? t("background.delete.confirmBody", { name: pendingDelete.name })
            : pendingDelete.kind === "image"
              ? t("background.asset.deleteImageConfirmBody", {
                  filename: pendingDelete.filename,
                  index: pendingDelete.index + 1,
                  name: pendingDelete.name,
                })
              : pendingDelete.kind === "all-images"
                ? t("background.asset.clearImagesConfirmBody", {
                    count: pendingDelete.count,
                    name: pendingDelete.name,
                  })
                : pendingDelete.kind === "bgm"
                  ? t("background.asset.deleteBgmConfirmBody", {
                      filename: pendingDelete.filename,
                      index: pendingDelete.index + 1,
                      name: pendingDelete.name,
                    })
                  : pendingDelete.kind === "selected-bgm"
                    ? t("background.asset.deleteSelectedBgmConfirmBody", {
                        count: pendingDelete.count,
                        name: pendingDelete.name,
                      })
                    : t("background.asset.clearBgmConfirmBody", {
                        count: pendingDelete.count,
                        name: pendingDelete.name,
                      }),
        confirmLabel:
          pendingDelete.kind === "image" || pendingDelete.kind === "bgm" ? t("common.remove") : t("common.delete"),
        title:
          pendingDelete.kind === "background"
            ? t("background.delete.confirmTitle")
            : pendingDelete.kind === "all-images"
              ? t("background.asset.clearImages")
              : pendingDelete.kind === "selected-bgm"
                ? t("background.asset.deleteSelectedBgm")
                : pendingDelete.kind === "all-bgm"
                  ? t("background.asset.clearBgm")
                  : t("common.remove"),
      }
    : null;

  const saveDraft = () => {
    if (!draft.name.trim()) {
      setNameError(t("background.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return;
    }
    saveMutation.mutate({
      background: { ...draft, name: draft.name.trim(), sprite_prefix: draft.sprite_prefix.trim() || "temp" },
      originalName: isCreating ? undefined : selectedName,
    });
  };

  const bgmRowTags = useMemo(
    () => tagContents(draft.bgm_tags, draft.bgm_list.length),
    [draft.bgm_list.length, draft.bgm_tags],
  );
  const sortedBgmItems = useMemo(() => {
    const direction = bgmSort.direction === "asc" ? 1 : -1;
    return draft.bgm_list
      .map((path, originalIndex) => ({
        filename: baseName(path),
        originalIndex,
        path,
      }))
      .sort((left, right) => {
        if (bgmSort.key === "filename") {
          const filenameOrder = left.filename.localeCompare(right.filename, undefined, {
            numeric: true,
            sensitivity: "base",
          });
          return (filenameOrder || left.originalIndex - right.originalIndex) * direction;
        }
        return (left.originalIndex - right.originalIndex) * direction;
      });
  }, [bgmSort.direction, bgmSort.key, draft.bgm_list]);
  const imageRowTags = useMemo(
    () => tagContents(draft.bg_tags, draft.sprites.length),
    [draft.bg_tags, draft.sprites.length],
  );
  const selectedImage = draft.sprites[selectedImageIndex];
  const backgroundImageItems = useMemo(
    () =>
      draft.sprites.map((sprite, index) => ({
        id: `${sprite.path}-${index}`,
        imageSrc: sprite.path ? fileUrl(sprite.path) : "",
        meta: imageRowTags[index] || "",
        title: baseName(sprite.path) || `${index + 1}`,
      })),
    [draft.sprites, imageRowTags],
  );
  const selectedBgmIndexSet = useMemo(() => new Set(selectedBgmIndexes), [selectedBgmIndexes]);
  const selectedBgmCount = selectedBgmIndexes.filter((index) => index >= 0 && index < draft.bgm_list.length).length;
  const allBgmSelected = draft.bgm_list.length > 0 && selectedBgmCount === draft.bgm_list.length;

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h1 className="page__title">{t("background.title")}</h1>
          <p className="page__description">{t("background.description")}</p>
        </div>
        <div className="page__actions">
          <Button
            icon={<Plus aria-hidden className="button__icon" />}
            onClick={() => {
              setIsCreating(true);
              setSelectedName("");
              setDraft(createBackground());
              setPendingBgmPaths([]);
              setPendingImagePaths([]);
              setSelectedBgmIndexes([]);
              setSelectedImageIndex(0);
              setNameError("");
            }}
          >
            {t("common.new")}
          </Button>
          <div className="page__file-picker">
            <FilePicker
              acceptedExtensions={[".bg"]}
              multiple
              onPathsChange={setPendingImportFiles}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("common.import")}
              readOnly
              value={
                pendingImportFiles.length
                  ? t("background.asset.selectedFiles", { count: pendingImportFiles.length })
                  : ""
              }
            />
          </div>
          <AsyncButton
            disabled={!pendingImportFiles.length}
            icon={<Upload aria-hidden className="button__icon" />}
            loading={importMutation.isPending}
            onClick={() => {
              importMutation.mutate(pendingImportFiles);
            }}
          >
            {t("common.import")}
          </AsyncButton>
          <AsyncButton
            icon={<Download aria-hidden className="button__icon" />}
            loading={exportMutation.isPending}
            onClick={() => {
              if (!currentBackgroundName) {
                showToast({
                  kind: "error",
                  message: t("background.validation.nameRequired"),
                  title: t("common.export"),
                });
                return;
              }
              exportMutation.mutate(currentBackgroundName);
            }}
          >
            {t("common.export")}
          </AsyncButton>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={saveMutation.isPending}
            onClick={saveDraft}
            variant="primary"
          >
            {t("common.save")}
          </AsyncButton>
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal("https://rachelforster.github.io/Shinsekai/resources.html?type=background")}
            variant="ghost"
          >
            {t("background.action.community")}
          </Button>
          <Button
            icon={<ExternalLink aria-hidden className="button__icon" />}
            onClick={() => openExternal("https://wj.qq.com/s2/26616089/b61a/")}
            variant="ghost"
          >
            {t("background.action.uploadContribution")}
          </Button>
        </div>
      </header>

      <div className="settings-grid settings-grid--split">
        <aside className="entity-list">
          <div className="entity-list__header">
            <strong>{t("background.groupListTitle")}</strong>
            <span className="entity-list__meta">{data.length}</span>
          </div>
          {isLoading ? <EmptyState title={t("background.loading")} /> : null}
          {backgroundsQuery.isError ? (
            <QueryErrorState
              error={backgroundsQuery.error}
              onRetry={() => void backgroundsQuery.refetch()}
              retryLabel={t("common.retry")}
              title={t("common.operationFailed")}
            />
          ) : null}
          {!isLoading && !backgroundsQuery.isError && !data.length ? (
            <EmptyState title={t("background.emptyTitle")} body={t("background.emptyBody")} />
          ) : null}
          {data.map((background) => (
            <button
              aria-selected={!isCreating && background.name === draft.name}
              className="entity-list__item"
              key={background.name}
              onClick={() => {
                setIsCreating(false);
                setSelectedName(background.name);
              }}
              type="button"
            >
              <span className="entity-list__primary">{background.name}</span>
              <span className="entity-list__meta">
                {t("background.resource.imageCount", { count: background.sprites.length })}
              </span>
            </button>
          ))}
        </aside>

        <section className="settings-grid">
          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("background.section.info")}</h2>
              <div className="page__actions">
                <AsyncButton
                  icon={<Languages aria-hidden className="button__icon" />}
                  loading={translateMutation.isPending}
                  onClick={() => {
                    if (!draft.name.trim() && !draft.bg_tags.trim() && !draft.bgm_tags.trim()) {
                      showToast({
                        kind: "error",
                        message: t("common.fixInvalidFields"),
                        title: t("common.validationFailed"),
                      });
                      return;
                    }
                    translateMutation.mutate();
                  }}
                  variant="ghost"
                >
                  {t("background.action.aiTranslate")}
                </AsyncButton>
                <Button
                  icon={<Trash2 aria-hidden className="button__icon" />}
                  onClick={() => {
                    if (!currentBackgroundName) {
                      showToast({
                        kind: "error",
                        message: t("background.error.deleteFallback"),
                        title: t("common.deleteFailed"),
                      });
                      return;
                    }
                    setPendingDelete({ kind: "background", name: currentBackgroundName });
                  }}
                  variant="danger"
                >
                  {t("common.delete")}
                </Button>
              </div>
            </div>
            <div className="form-grid form-grid--two">
              <label className="field-row">
                <span className="field-row__label">{t("background.field.name")}</span>
                <span className="field-row__control">
                  <TextInput
                    className={nameError ? "input--error" : ""}
                    onChange={(event) => update("name", event.target.value)}
                    value={draft.name}
                  />
                  {nameError ? <span className="field-error">{nameError}</span> : null}
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("background.field.spritePrefix")}</span>
                <span className="field-row__control">
                  <TextInput
                    onChange={(event) => update("sprite_prefix", event.target.value)}
                    value={draft.sprite_prefix}
                  />
                </span>
              </label>
            </div>
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("background.section.tags")}</h2>
            </div>
            <div className="form-grid">
              <label className="field-row">
                <span className="field-row__label">{t("background.field.bgTags")}</span>
                <span className="field-row__control">
                  <TextArea onChange={(event) => update("bg_tags", event.target.value)} value={draft.bg_tags} />
                  <AsyncButton
                    icon={<Save aria-hidden className="button__icon" />}
                    loading={imageTagsSaveMutation.isPending}
                    onClick={() => {
                      if (!currentBackgroundName) {
                        showToast({
                          kind: "error",
                          message: t("background.validation.nameRequired"),
                          title: t("background.action.saveImageTags"),
                        });
                        return;
                      }
                      imageTagsSaveMutation.mutate();
                    }}
                    variant="ghost"
                  >
                    {t("background.action.saveImageTags")}
                  </AsyncButton>
                </span>
              </label>
              <label className="field-row">
                <span className="field-row__label">{t("background.field.bgmTags")}</span>
                <span className="field-row__control">
                  <TextArea onChange={(event) => update("bgm_tags", event.target.value)} value={draft.bgm_tags} />
                  <AsyncButton
                    icon={<Save aria-hidden className="button__icon" />}
                    loading={bgmTagsSaveMutation.isPending}
                    onClick={() => {
                      if (!currentBackgroundName) {
                        showToast({
                          kind: "error",
                          message: t("background.validation.nameRequired"),
                          title: t("background.action.saveBgmTags"),
                        });
                        return;
                      }
                      bgmTagsSaveMutation.mutate();
                    }}
                    variant="ghost"
                  >
                    {t("background.action.saveBgmTags")}
                  </AsyncButton>
                </span>
              </label>
            </div>
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("background.section.images")}</h2>
              <div className="page__actions">
                <AsyncButton
                  icon={<Upload aria-hidden className="button__icon" />}
                  loading={imageUploadMutation.isPending}
                  onClick={() => {
                    if (!currentBackgroundName) {
                      showToast({
                        kind: "error",
                        message: t("background.validation.nameRequired"),
                        title: t("background.asset.uploadImages"),
                      });
                      return;
                    }
                    if (!pendingImagePaths.length) {
                      showToast({ kind: "error", title: t("background.asset.selectImages") });
                      return;
                    }
                    imageUploadMutation.mutate();
                  }}
                  variant="ghost"
                >
                  {t("background.asset.uploadImages")}
                </AsyncButton>
                <Button
                  icon={<Trash2 aria-hidden className="button__icon" />}
                  onClick={() => {
                    if (!currentBackgroundName || !draft.sprites.length) {
                      showToast({ kind: "error", title: t("background.asset.clearImages") });
                      return;
                    }
                    setPendingDelete({
                      count: draft.sprites.length,
                      kind: "all-images",
                      name: currentBackgroundName,
                    });
                  }}
                  variant="ghost"
                >
                  {t("background.asset.clearImages")}
                </Button>
              </div>
            </div>
            <div className="asset-editor">
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("background.asset.selectImages")}</span>
                <span className="field-row__control">
                  <FilePicker
                    acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
                    multiple
                    onPathsChange={(paths) => {
                      if (paths.length) {
                        setPendingImagePaths(paths);
                      }
                    }}
                    pickLabel={t("common.chooseFile")}
                    pickerTitle={t("background.asset.selectImages")}
                    value={
                      pendingImagePaths.length
                        ? t("background.asset.selectedFiles", { count: pendingImagePaths.length })
                        : ""
                    }
                  />
                </span>
              </label>
              {!draft.sprites.length ? <EmptyState title={t("background.asset.emptyImages")} /> : null}
              {selectedImage ? (
                <div className="asset-gallery-layout asset-gallery-layout--background">
                  <ImageAssetGallery
                    items={backgroundImageItems}
                    onSelect={setSelectedImageIndex}
                    selectedIndex={selectedImageIndex}
                  />
                  <aside className="asset-inspector">
                    <div className="asset-inspector__preview asset-inspector__preview--background">
                      {selectedImage.path ? (
                        <img alt="" decoding="async" src={fileUrl(selectedImage.path)} />
                      ) : (
                        <ImageIcon aria-hidden className="asset-inspector__fallback" />
                      )}
                    </div>
                    <label className="field-row field-row--stack">
                      <span className="field-row__label">{t("background.asset.path")}</span>
                      <span className="field-row__control">
                        <PathDisplay className="path-display--input" path={selectedImage.path} />
                      </span>
                    </label>
                    <label className="field-row field-row--stack">
                      <span className="field-row__label">{t("background.asset.tag")}</span>
                      <span className="field-row__control">
                        <TextInput
                          onChange={(event) => updateImageRowTag(selectedImageIndex, event.target.value)}
                          value={imageRowTags[selectedImageIndex] ?? ""}
                        />
                      </span>
                    </label>
                    <div className="asset-inspector__actions">
                      <AsyncButton
                        icon={<Save aria-hidden className="button__icon" />}
                        loading={imageTagsSaveMutation.isPending}
                        onClick={() => {
                          if (!currentBackgroundName) {
                            showToast({
                              kind: "error",
                              message: t("background.validation.nameRequired"),
                              title: t("background.action.saveImageTags"),
                            });
                            return;
                          }
                          imageTagsSaveMutation.mutate();
                        }}
                        variant="ghost"
                      >
                        {t("background.action.saveImageTags")}
                      </AsyncButton>
                      <AsyncButton
                        icon={<Trash2 aria-hidden className="button__icon" />}
                        loading={imageDeleteMutation.isPending}
                        onClick={() => handleImageDelete(selectedImageIndex)}
                        variant="ghost"
                      >
                        {t("common.remove")}
                      </AsyncButton>
                    </div>
                  </aside>
                </div>
              ) : null}
            </div>
          </section>

          <section className="section">
            <div className="section__header">
              <h2 className="section__title">{t("background.section.bgm")}</h2>
              <div className="page__actions">
                <AsyncButton
                  icon={<Upload aria-hidden className="button__icon" />}
                  loading={bgmUploadMutation.isPending}
                  onClick={() => {
                    if (!currentBackgroundName) {
                      showToast({
                        kind: "error",
                        message: t("background.validation.nameRequired"),
                        title: t("background.asset.uploadBgm"),
                      });
                      return;
                    }
                    if (!pendingBgmPaths.length) {
                      showToast({ kind: "error", title: t("background.asset.selectBgm") });
                      return;
                    }
                    bgmUploadMutation.mutate();
                  }}
                  variant="ghost"
                >
                  {t("background.asset.uploadBgm")}
                </AsyncButton>
                <AsyncButton
                  icon={<Trash2 aria-hidden className="button__icon" />}
                  loading={bgmBatchDeleteMutation.isPending}
                  onClick={() => {
                    const validSelectedBgmIndexes = selectedBgmIndexes.filter(
                      (index) => index >= 0 && index < draft.bgm_list.length,
                    );
                    if (!validSelectedBgmIndexes.length) {
                      showToast({ kind: "error", title: t("background.asset.noSelectedBgm") });
                      return;
                    }
                    setPendingDelete({
                      count: validSelectedBgmIndexes.length,
                      indexes: validSelectedBgmIndexes,
                      kind: "selected-bgm",
                      name: currentBackgroundName,
                    });
                  }}
                  variant="ghost"
                >
                  {t("background.asset.deleteSelectedBgm")}
                </AsyncButton>
                <Button
                  icon={<Trash2 aria-hidden className="button__icon" />}
                  onClick={() => {
                    if (!currentBackgroundName || !draft.bgm_list.length) {
                      showToast({ kind: "error", title: t("background.asset.clearBgm") });
                      return;
                    }
                    setPendingDelete({
                      count: draft.bgm_list.length,
                      kind: "all-bgm",
                      name: currentBackgroundName,
                    });
                  }}
                  variant="ghost"
                >
                  {t("background.asset.clearBgm")}
                </Button>
              </div>
            </div>
            <div className="asset-editor">
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("background.asset.selectBgm")}</span>
                <span className="field-row__control">
                  <FilePicker
                    acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
                    multiple
                    onPathsChange={(paths) => {
                      if (paths.length) {
                        setPendingBgmPaths(paths);
                      }
                    }}
                    pickLabel={t("common.chooseFile")}
                    pickerTitle={t("background.asset.selectBgm")}
                    value={
                      pendingBgmPaths.length
                        ? t("background.asset.selectedFiles", { count: pendingBgmPaths.length })
                        : ""
                    }
                  />
                </span>
              </label>
              {!draft.bgm_list.length ? <EmptyState title={t("background.asset.emptyBgm")} /> : null}
              {draft.bgm_list.length ? (
                <BackgroundBgmRows
                  allSelected={allBgmSelected}
                  clearSelectionLabel={t("background.asset.clearBgmSelection")}
                  deleting={bgmDeleteMutation.isPending}
                  filenameLabel={t("background.asset.filename")}
                  items={sortedBgmItems}
                  indexLabel={t("background.asset.index")}
                  onDelete={handleBgmDelete}
                  onSort={toggleBgmSort}
                  onTagChange={updateBgmRowTag}
                  onToggleAllSelection={toggleAllBgmSelection}
                  onToggleSelection={toggleBgmSelection}
                  pathLabel={t("background.asset.path")}
                  previewLabel={t("background.asset.preview")}
                  removeLabel={t("common.remove")}
                  rowTags={bgmRowTags}
                  selectLabel={t("background.asset.select")}
                  selectAllLabel={t("background.asset.selectAllBgm")}
                  selectedIndexes={selectedBgmIndexSet}
                  sortDirection={bgmSort.direction}
                  sortKey={bgmSort.key}
                  tagLabel={t("background.asset.tag")}
                />
              ) : null}
            </div>
          </section>
        </section>
      </div>

      <AlertDialog
        body={pendingDeleteCopy?.body ?? ""}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={pendingDeleteCopy?.confirmLabel ?? t("common.delete")}
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmPendingDelete}
        open={Boolean(pendingDelete)}
        title={pendingDeleteCopy?.title ?? t("common.delete")}
      />
    </div>
  );
}
