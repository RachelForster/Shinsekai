import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, Languages, Plus, Save, Trash2, Upload } from "lucide-react";

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
import { openExternal } from "../../entities/files/repository";
import { baseName, numberedTags, tagContents } from "../../shared/assets/assetText";
import { useI18n } from "../../shared/i18n";
import {
  AlertDialog,
  AsyncButton,
  Button,
  EmptyState,
  FilePicker,
  QueryErrorState,
  TextArea,
  TextInput,
  useToast,
} from "../../shared/ui";
import { BackgroundMusicSection } from "./BackgroundMusicSection";
import { BackgroundSpriteGallery } from "./BackgroundSpriteGallery";
import {
  createBackground,
  type BackgroundBgmItem,
  type BackgroundDeleteTarget,
  type BgmSortDirection,
  type BgmSortKey,
} from "./backgroundUtils";
import "./BackgroundManagerPage.css";

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
    () => (isCreating ? undefined : (data.find((bg) => bg.name === selectedName) ?? data[0])),
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
      uploadBackgroundImages({ bgTags: draft.bg_tags, name: currentBackgroundName, paths: pendingImagePaths }),
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
      uploadBackgroundBgm({ bgmTags: draft.bgm_tags, name: currentBackgroundName, paths: pendingBgmPaths }),
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
                ? t("background.asset.clearImagesConfirmBody", { count: pendingDelete.count, name: pendingDelete.name })
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
      .map((path, originalIndex) => ({ filename: baseName(path), originalIndex, path }))
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
  const selectedBgmIndexSet = useMemo(() => new Set(selectedBgmIndexes), [selectedBgmIndexes]);

  return (
    <div className="page background-page">
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
            onClick={() => importMutation.mutate(pendingImportFiles)}
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
          {/* Info section */}
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

          {/* Tags section */}
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

          {/* Sprite gallery */}
          <BackgroundSpriteGallery
            currentBackgroundName={currentBackgroundName}
            deletePending={imageDeleteMutation.isPending}
            imageRowTags={imageRowTags}
            onClearImages={() => {
              if (!currentBackgroundName || !draft.sprites.length) {
                showToast({ kind: "error", title: t("background.asset.clearImages") });
                return;
              }
              setPendingDelete({ count: draft.sprites.length, kind: "all-images", name: currentBackgroundName });
            }}
            onDeleteImage={handleImageDelete}
            onPendingImagePathsChange={setPendingImagePaths}
            onSaveImageTags={() => {
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
            onSelectImage={setSelectedImageIndex}
            onUpdateImageTag={updateImageRowTag}
            onUploadImages={() => imageUploadMutation.mutate()}
            pendingImagePaths={pendingImagePaths}
            saveTagsPending={imageTagsSaveMutation.isPending}
            selectedImageIndex={selectedImageIndex}
            sprites={draft.sprites}
            uploadPending={imageUploadMutation.isPending}
          />

          {/* BGM section */}
          <BackgroundMusicSection
            batchDeletePending={bgmBatchDeleteMutation.isPending}
            bgmList={draft.bgm_list}
            bgmRowTags={bgmRowTags}
            currentBackgroundName={currentBackgroundName}
            deletePending={bgmDeleteMutation.isPending}
            onBatchDelete={() => {
              const validIndexes = selectedBgmIndexes.filter((i) => i >= 0 && i < draft.bgm_list.length);
              if (!validIndexes.length) {
                showToast({ kind: "error", title: t("background.asset.noSelectedBgm") });
                return;
              }
              setPendingDelete({
                count: validIndexes.length,
                indexes: validIndexes,
                kind: "selected-bgm",
                name: currentBackgroundName,
              });
            }}
            onClearAll={() => {
              if (!currentBackgroundName || !draft.bgm_list.length) {
                showToast({ kind: "error", title: t("background.asset.clearBgm") });
                return;
              }
              setPendingDelete({ count: draft.bgm_list.length, kind: "all-bgm", name: currentBackgroundName });
            }}
            onDelete={handleBgmDelete}
            onPendingBgmPathsChange={setPendingBgmPaths}
            onSortToggle={toggleBgmSort}
            onTagChange={updateBgmRowTag}
            onToggleAllSelection={toggleAllBgmSelection}
            onToggleSelection={toggleBgmSelection}
            onUpload={() => bgmUploadMutation.mutate()}
            pendingBgmPaths={pendingBgmPaths}
            selectedBgmIndexSet={selectedBgmIndexSet}
            sortDirection={bgmSort.direction}
            sortKey={bgmSort.key}
            sortedBgmItems={sortedBgmItems}
            uploadPending={bgmUploadMutation.isPending}
          />
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
