import { memo, useCallback, useEffect, useMemo, useState } from "react";
import type { ChangeEvent, UIEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, Image as ImageIcon, Languages, Music, Plus, Save, Trash2, Upload } from "lucide-react";

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
import type { Background, Sprite } from "../../entities/config/types";
import { fileUrl, openExternal } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import {
  AsyncButton,
  Button,
  EmptyState,
  FilePicker,
  QueryErrorState,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";

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

function baseName(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function extractTagContent(line: string) {
  const fullWidth = line.indexOf("：");
  const ascii = line.indexOf(":");
  const index = fullWidth >= 0 && ascii >= 0 ? Math.min(fullWidth, ascii) : Math.max(fullWidth, ascii);
  return index >= 0 ? line.slice(index + 1).trim() : line.trim();
}

function numberedTags(prefix: string, tags: string[]) {
  return tags.map((tag, index) => `${prefix} ${index + 1}：${tag}`).join("\n") + (tags.length ? "\n" : "");
}

function tagContents(block: string, count: number) {
  const lines = block.split(/\r?\n/).filter(Boolean);
  return Array.from({ length: count }, (_, index) => extractTagContent(lines[index] ?? ""));
}

const IMAGE_ROW_HEIGHT = 82;
const BGM_ROW_HEIGHT = 58;
const VIRTUAL_OVERSCAN_ROWS = 4;
const VIRTUAL_IMAGE_ROWS = 8;
const VIRTUAL_BGM_ROWS = 10;

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

interface BackgroundImageRowsProps {
  deleting: boolean;
  onDelete: (index: number) => void;
  pathLabel: string;
  removeLabel: string;
  sprites: Sprite[];
}

interface BackgroundImageRowProps {
  deleting: boolean;
  index: number;
  onDelete: (index: number) => void;
  path: string;
  pathLabel: string;
  removeLabel: string;
}

const BackgroundImageRow = memo(function BackgroundImageRow({
  deleting,
  index,
  onDelete,
  path,
  pathLabel,
  removeLabel,
}: BackgroundImageRowProps) {
  const handleDelete = useCallback(() => onDelete(index), [index, onDelete]);

  return (
    <div className="asset-row asset-row--compact">
      <div className="asset-row__index">
        {path ? (
          <img alt="" className="asset-thumb" decoding="async" loading="lazy" src={fileUrl(path)} />
        ) : (
          <ImageIcon aria-hidden className="asset-row__icon" />
        )}
        <span>{index + 1}</span>
      </div>
      <label className="field-row field-row--stack">
        <span className="field-row__label">{pathLabel}</span>
        <span className="field-row__control">
          <TextInput readOnly value={path} />
        </span>
      </label>
      <AsyncButton
        icon={<Trash2 aria-hidden className="button__icon" />}
        loading={deleting}
        onClick={handleDelete}
        variant="ghost"
      >
        {removeLabel}
      </AsyncButton>
    </div>
  );
});

const BackgroundImageRows = memo(function BackgroundImageRows({
  deleting,
  onDelete,
  pathLabel,
  removeLabel,
  sprites,
}: BackgroundImageRowsProps) {
  const virtual = useVirtualRange(sprites.length, IMAGE_ROW_HEIGHT, VIRTUAL_IMAGE_ROWS);
  const visibleSprites = sprites.slice(virtual.startIndex, virtual.endIndex);

  return (
    <div className="background-virtual-list" onScroll={virtual.onScroll} style={{ maxHeight: virtual.maxHeight }}>
      {virtual.paddingTop ? (
        <div aria-hidden className="background-virtual-list__spacer" style={{ height: virtual.paddingTop }} />
      ) : null}
      {visibleSprites.map((sprite, offset) => {
        const index = virtual.startIndex + offset;
        return (
          <BackgroundImageRow
            deleting={deleting}
            index={index}
            key={`${sprite.path}-${index}`}
            onDelete={onDelete}
            path={sprite.path}
            pathLabel={pathLabel}
            removeLabel={removeLabel}
          />
        );
      })}
      {virtual.paddingBottom ? (
        <div aria-hidden className="background-virtual-list__spacer" style={{ height: virtual.paddingBottom }} />
      ) : null}
    </div>
  );
});

interface BackgroundBgmRowsProps {
  deleting: boolean;
  filenameLabel: string;
  indexLabel: string;
  onDelete: (index: number) => void;
  onTagChange: (index: number, value: string) => void;
  onToggleSelection: (index: number, checked: boolean) => void;
  pathLabel: string;
  paths: string[];
  previewLabel: string;
  removeLabel: string;
  rowTags: string[];
  selectLabel: string;
  selectedIndexes: Set<number>;
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
        <Music aria-hidden className="asset-row__icon" />
        <span>{filename}</span>
      </td>
      <td>
        <span className="background-bgm-table__path" title={path}>
          {path}
        </span>
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
  deleting,
  filenameLabel,
  indexLabel,
  onDelete,
  onTagChange,
  onToggleSelection,
  pathLabel,
  paths,
  previewLabel,
  removeLabel,
  rowTags,
  selectLabel,
  selectedIndexes,
  tagLabel,
}: BackgroundBgmRowsProps) {
  const virtual = useVirtualRange(paths.length, BGM_ROW_HEIGHT, VIRTUAL_BGM_ROWS);
  const visiblePaths = paths.slice(virtual.startIndex, virtual.endIndex);

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
            <th>{selectLabel}</th>
            <th>{indexLabel}</th>
            <th>{filenameLabel}</th>
            <th>{pathLabel}</th>
            <th>{tagLabel}</th>
            <th>{previewLabel}</th>
            <th>{removeLabel}</th>
          </tr>
        </thead>
        <tbody>
          <BgmSpacerRow height={virtual.paddingTop} />
          {visiblePaths.map((path, offset) => {
            const index = virtual.startIndex + offset;
            return (
              <BackgroundBgmRow
                deleting={deleting}
                index={index}
                key={`${path}-${index}`}
                onDelete={onDelete}
                onTagChange={onTagChange}
                onToggleSelection={onToggleSelection}
                path={path}
                removeLabel={removeLabel}
                selected={selectedIndexes.has(index)}
                tag={rowTags[index] ?? ""}
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
  const [selectedBgmIndexes, setSelectedBgmIndexes] = useState<number[]>([]);
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
      setNameError("");
    }
  }, [selected]);

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
    mutationFn: (index: number) => deleteBackgroundImage(currentBackgroundName, index),
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
    mutationFn: () => deleteAllBackgroundImages(currentBackgroundName),
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
    mutationFn: (index: number) => deleteBackgroundBgm(currentBackgroundName, index),
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
    mutationFn: async (indexes: number[]) => {
      let background: Background | null = null;
      for (const index of [...indexes].sort((a, b) => b - a)) {
        background = await deleteBackgroundBgm(currentBackgroundName, index);
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
    mutationFn: () => deleteAllBackgroundBgm(currentBackgroundName),
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

  const toggleBgmSelection = useCallback((index: number, checked: boolean) => {
    setSelectedBgmIndexes((current) => {
      if (checked) {
        return current.includes(index) ? current : [...current, index];
      }
      return current.filter((item) => item !== index);
    });
  }, []);

  const handleImageDelete = useCallback(
    (index: number) => imageDeleteMutation.mutate(index),
    [imageDeleteMutation.mutate],
  );
  const handleBgmDelete = useCallback((index: number) => bgmDeleteMutation.mutate(index), [bgmDeleteMutation.mutate]);

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
  const selectedBgmIndexSet = useMemo(() => new Set(selectedBgmIndexes), [selectedBgmIndexes]);

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
                    deleteMutation.mutate(currentBackgroundName);
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
                    imageDeleteAllMutation.mutate();
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
              {draft.sprites.length ? (
                <BackgroundImageRows
                  deleting={imageDeleteMutation.isPending}
                  onDelete={handleImageDelete}
                  pathLabel={t("background.asset.path")}
                  removeLabel={t("common.remove")}
                  sprites={draft.sprites}
                />
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
                    if (!selectedBgmIndexes.length) {
                      showToast({ kind: "error", title: t("background.asset.noSelectedBgm") });
                      return;
                    }
                    bgmBatchDeleteMutation.mutate(selectedBgmIndexes);
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
                    bgmDeleteAllMutation.mutate();
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
                  deleting={bgmDeleteMutation.isPending}
                  filenameLabel={t("background.asset.filename")}
                  indexLabel={t("background.asset.index")}
                  onDelete={handleBgmDelete}
                  onTagChange={updateBgmRowTag}
                  onToggleSelection={toggleBgmSelection}
                  pathLabel={t("background.asset.path")}
                  paths={draft.bgm_list}
                  previewLabel={t("background.asset.preview")}
                  removeLabel={t("common.remove")}
                  rowTags={bgmRowTags}
                  selectLabel={t("background.asset.select")}
                  selectedIndexes={selectedBgmIndexSet}
                  tagLabel={t("background.asset.tag")}
                />
              ) : null}
            </div>
          </section>
        </section>
      </div>
    </div>
  );
}
