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
  PathPickerDialog,
  PageSectionNav,
  QueryErrorState,
  Select,
  TextInput,
  useToast,
} from "../../shared/ui";
import { BackgroundMusicSection } from "./BackgroundMusicSection";
import { BackgroundSpriteGallery } from "./BackgroundSpriteGallery";
import { BackgroundTagsDialog } from "./BackgroundTagsDialog";
import {
  backgroundDeleteDialogCopy,
  createBackground,
  runBackgroundDeleteTarget,
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
  const [draftSourceName, setDraftSourceName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<BackgroundDeleteTarget | null>(null);
  const [selectedBgmIndexes, setSelectedBgmIndexes] = useState<number[]>([]);
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);
  const [importPickerOpen, setImportPickerOpen] = useState(false);
  const [bulkImageTagsOpen, setBulkImageTagsOpen] = useState(false);
  const [bulkImageTagsDraft, setBulkImageTagsDraft] = useState("");
  const [bulkBgmTagsOpen, setBulkBgmTagsOpen] = useState(false);
  const [bulkBgmTagsDraft, setBulkBgmTagsDraft] = useState("");
  const [bgmSort, setBgmSort] = useState<{ direction: BgmSortDirection; key: BgmSortKey }>({
    direction: "asc",
    key: "index",
  });
  const [nameError, setNameError] = useState("");

  const selected = useMemo(() => {
    if (isCreating) {
      return undefined;
    }
    if (selectedName) {
      return data.find((bg) => bg.name === selectedName);
    }
    return data[0];
  }, [data, isCreating, selectedName]);
  const currentBackgroundName = isCreating ? "" : selected?.name || selectedName;
  const draftMatchesSelection = isCreating || !selected || draftSourceName === selected.name;
  const currentDraft = draftMatchesSelection ? draft : selected;
  const isSavedBackground = Boolean(
    currentBackgroundName && data.some((background) => background.name === currentBackgroundName),
  );

  useEffect(() => {
    if (selected) {
      setSelectedName(selected.name);
      setDraft(structuredClone(selected));
      setDraftSourceName(selected.name);
      setSelectedBgmIndexes([]);
      setSelectedImageIndex(0);
      setNameError("");
    }
  }, [selected]);

  useEffect(() => {
    setSelectedImageIndex((current) => Math.min(current, Math.max(0, currentDraft.sprites.length - 1)));
  }, [currentDraft.sprites.length]);

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
    onSuccess(background, variables) {
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) => {
        const targetNames = new Set([variables.originalName, background.name].filter(Boolean));
        const next = current.filter((item) => !targetNames.has(item.name));
        return [...next, background];
      });
      setIsCreating(false);
      setSelectedName(background.name);
      setDraft(structuredClone(background));
      setDraftSourceName(background.name);
      setSelectedBgmIndexes([]);
      setSelectedImageIndex(0);
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
      const lastImported = imported[imported.length - 1];
      if (lastImported) {
        setIsCreating(false);
        setSelectedName(lastImported.name);
        setDraft(structuredClone(lastImported));
        setDraftSourceName(lastImported.name);
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
        bgTags: currentDraft.bg_tags,
        bgmRowTags: tagContents(currentDraft.bgm_tags, currentDraft.bgm_list.length),
        bgmTags: currentDraft.bgm_tags,
        name: currentDraft.name,
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
    mutationFn: (paths: string[]) =>
      uploadBackgroundImages({ bgTags: currentDraft.bg_tags, name: currentBackgroundName, paths }),
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
      showToast({ kind: "success", title: t("background.asset.uploadImages") });
    },
  });

  const imageTagsSaveMutation = useMutation({
    mutationFn: (bgTags: string) => saveBackgroundImageTags({ bgTags, name: currentBackgroundName }),
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
    mutationFn: (paths: string[]) =>
      uploadBackgroundBgm({ bgmTags: currentDraft.bgm_tags, name: currentBackgroundName, paths }),
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
      showToast({ kind: "success", title: t("background.asset.uploadBgm") });
    },
  });

  const bgmTagsSaveMutation = useMutation({
    mutationFn: (bgmTags: string) => saveBackgroundBgmTags({ bgmTags, name: currentBackgroundName }),
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
    setDraft((current) => ({ ...(draftMatchesSelection ? current : structuredClone(currentDraft)), [name]: value }));
    setDraftSourceName(currentBackgroundName);
    if (name === "name" && String(value).trim()) {
      setNameError("");
    }
  };

  const updateBgmRowTag = useCallback(
    (index: number, value: string) => {
      setDraft((current) => {
        const baseDraft = draftMatchesSelection ? current : currentDraft;
        const tags = tagContents(baseDraft.bgm_tags, baseDraft.bgm_list.length);
        tags[index] = value;
        return { ...baseDraft, bgm_tags: numberedTags("音乐", tags) };
      });
      setDraftSourceName(currentBackgroundName);
    },
    [currentBackgroundName, currentDraft, draftMatchesSelection],
  );

  const updateImageRowTag = useCallback(
    (index: number, value: string) => {
      setDraft((current) => {
        const baseDraft = draftMatchesSelection ? current : currentDraft;
        const tags = tagContents(baseDraft.bg_tags, baseDraft.sprites.length);
        tags[index] = value;
        return { ...baseDraft, bg_tags: numberedTags("场景", tags) };
      });
      setDraftSourceName(currentBackgroundName);
    },
    [currentBackgroundName, currentDraft, draftMatchesSelection],
  );

  const openBulkImageTagsDialog = () => {
    setBulkImageTagsDraft(currentDraft.bg_tags);
    setBulkImageTagsOpen(true);
  };

  const confirmBulkImageTags = () => {
    const nextTags = bulkImageTagsDraft;
    update("bg_tags", nextTags);
    setBulkImageTagsOpen(false);
    if (nextTags.trim() && !saveMutation.isPending) {
      const input = buildBackgroundSaveInput({ bg_tags: nextTags });
      if (input) {
        saveMutation.mutate(input);
      }
    }
  };

  const openBulkBgmTagsDialog = () => {
    setBulkBgmTagsDraft(currentDraft.bgm_tags);
    setBulkBgmTagsOpen(true);
  };

  const confirmBulkBgmTags = () => {
    const nextTags = bulkBgmTagsDraft;
    update("bgm_tags", nextTags);
    setBulkBgmTagsOpen(false);
    if (nextTags.trim() && !saveMutation.isPending) {
      const input = buildBackgroundSaveInput({ bgm_tags: nextTags });
      if (input) {
        saveMutation.mutate(input);
      }
    }
  };

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
      const validSelection = current.filter((index) => index >= 0 && index < currentDraft.bgm_list.length);
      const allSelected = currentDraft.bgm_list.length > 0 && validSelection.length === currentDraft.bgm_list.length;
      return allSelected ? [] : currentDraft.bgm_list.map((_, index) => index);
    });
  }, [currentDraft.bgm_list]);

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
      const image = currentDraft.sprites[index];
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
    [currentBackgroundName, currentDraft.sprites, showToast, t],
  );

  const handleBgmDelete = useCallback(
    (index: number) => {
      const path = currentDraft.bgm_list[index];
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
    [currentBackgroundName, currentDraft.bgm_list, showToast, t],
  );

  const confirmPendingDelete = () => {
    if (!pendingDelete) {
      return;
    }
    const target = pendingDelete;
    setPendingDelete(null);
    runBackgroundDeleteTarget(target, {
      deleteAllBgm: bgmDeleteAllMutation.mutate,
      deleteAllImages: imageDeleteAllMutation.mutate,
      deleteBackground: deleteMutation.mutate,
      deleteBgm: bgmDeleteMutation.mutate,
      deleteImage: imageDeleteMutation.mutate,
      deleteSelectedBgm: bgmBatchDeleteMutation.mutate,
    });
  };

  const pendingDeleteCopy = pendingDelete ? backgroundDeleteDialogCopy(pendingDelete, t) : null;

  const buildBackgroundSaveInput = (overrides: Partial<Background> = {}) => {
    const nextDraft = { ...currentDraft, ...overrides };
    if (!nextDraft.name.trim()) {
      setNameError(t("background.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return null;
    }
    return {
      background: {
        ...nextDraft,
        name: nextDraft.name.trim(),
        sprite_prefix: nextDraft.sprite_prefix.trim() || "temp",
      },
      originalName: isSavedBackground ? currentBackgroundName : undefined,
    };
  };

  const saveDraft = () => {
    const input = buildBackgroundSaveInput();
    if (!input) {
      return;
    }
    saveMutation.mutate(input);
  };

  const bgmRowTags = useMemo(
    () => tagContents(currentDraft.bgm_tags, currentDraft.bgm_list.length),
    [currentDraft.bgm_list.length, currentDraft.bgm_tags],
  );
  const sortedBgmItems = useMemo(() => {
    const direction = bgmSort.direction === "asc" ? 1 : -1;
    return currentDraft.bgm_list
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
  }, [bgmSort.direction, bgmSort.key, currentDraft.bgm_list]);
  const imageRowTags = useMemo(
    () => tagContents(currentDraft.bg_tags, currentDraft.sprites.length),
    [currentDraft.bg_tags, currentDraft.sprites.length],
  );
  const selectedBgmIndexSet = useMemo(() => new Set(selectedBgmIndexes), [selectedBgmIndexes]);
  const backgroundSectionNavItems = [
    { id: "background-info", label: t("background.section.info") },
    { id: "background-images", label: t("background.section.images") },
    { id: "background-bgm", label: t("background.section.bgm") },
  ];

  return (
    <div className="page background-page">
      <header className="page__header background-page__header">
        <div className="background-page__heading">
          <h1 className="page__title">{t("background.title")}</h1>
        </div>
        <div className="page__actions background-page__primary-actions">
          <div className="background-page__resource-actions">
            <Button
              icon={<ExternalLink aria-hidden className="button__icon" />}
              onClick={() => openExternal("https://shinsekai.end0rph1n.icu/resources")}
              variant="ghost"
            >
              {t("background.action.community")}
            </Button>
            <Button
              icon={<ExternalLink aria-hidden className="button__icon" />}
              onClick={() => openExternal("https://shinsekai.end0rph1n.icu/resources")}
              variant="ghost"
            >
              {t("background.action.uploadContribution")}
            </Button>
          </div>
          <label className="background-page__group-select">
            <span className="visually-hidden">{t("background.groupListTitle")}</span>
            <Select
              disabled={isLoading || (!isCreating && !data.length)}
              onChange={(event) => {
                setIsCreating(false);
                setSelectedName(event.target.value);
              }}
              value={isCreating ? "" : selectedName || data[0]?.name || ""}
            >
              {isCreating ? <option value="">{t("common.new")}</option> : null}
              {!isCreating && !data.length ? <option value="">{t("background.emptyTitle")}</option> : null}
              {data.map((background) => (
                <option key={background.name} value={background.name}>
                  {background.name}
                </option>
              ))}
            </Select>
          </label>
          <div className="background-page__package-actions">
            <AsyncButton
              icon={<Upload aria-hidden className="button__icon" />}
              loading={importMutation.isPending}
              onClick={() => setImportPickerOpen(true)}
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
              variant="ghost"
            >
              {t("common.export")}
            </AsyncButton>
          </div>
          <Button
            icon={<Plus aria-hidden className="button__icon" />}
            onClick={() => {
              setIsCreating(true);
              setSelectedName("");
              setDraft(createBackground());
              setDraftSourceName("");
              setSelectedBgmIndexes([]);
              setSelectedImageIndex(0);
              setNameError("");
            }}
          >
            {t("common.new")}
          </Button>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={saveMutation.isPending}
            onClick={saveDraft}
            variant="primary"
          >
            {t("common.save")}
          </AsyncButton>
        </div>
        <PageSectionNav ariaLabel={t("background.title")} items={backgroundSectionNavItems} />
        <PathPickerDialog
          acceptedExtensions={[".bg"]}
          multiple
          onClose={() => setImportPickerOpen(false)}
          onSelect={(path) => importMutation.mutate([path])}
          onSelectMany={(paths) => importMutation.mutate(paths)}
          open={importPickerOpen}
          title={t("common.import")}
        />
      </header>

      {isLoading || backgroundsQuery.isError || (!isLoading && !backgroundsQuery.isError && !data.length) ? (
        <div className="background-page__status">
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
        </div>
      ) : null}

      <section className="settings-grid background-page__content">
        {/* Info section */}
        <section className="section page-section-anchor" id="background-info">
          <div className="section__header">
            <h2 className="section__title">{t("background.section.info")}</h2>
            <div className="page__actions">
              <AsyncButton
                icon={<Languages aria-hidden className="button__icon" />}
                loading={translateMutation.isPending}
                onClick={() => {
                  if (!currentDraft.name.trim() && !currentDraft.bg_tags.trim() && !currentDraft.bgm_tags.trim()) {
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
                  value={currentDraft.name}
                />
                {nameError ? <span className="field-error">{nameError}</span> : null}
              </span>
            </label>
            <label className="field-row">
              <span className="field-row__label">{t("background.field.spritePrefix")}</span>
              <span className="field-row__control">
                <TextInput
                  onChange={(event) => update("sprite_prefix", event.target.value)}
                  value={currentDraft.sprite_prefix}
                />
              </span>
            </label>
          </div>
        </section>

        {/* Sprite gallery */}
        <BackgroundSpriteGallery
          currentBackgroundName={currentBackgroundName}
          deletePending={imageDeleteMutation.isPending}
          id="background-images"
          imageRowTags={imageRowTags}
          onClearImages={() => {
            if (!currentBackgroundName || !currentDraft.sprites.length) {
              showToast({ kind: "error", title: t("background.asset.clearImages") });
              return;
            }
            setPendingDelete({ count: currentDraft.sprites.length, kind: "all-images", name: currentBackgroundName });
          }}
          onDeleteImage={handleImageDelete}
          onOpenBulkTags={openBulkImageTagsDialog}
          onSaveImageTags={() => {
            if (!currentBackgroundName) {
              showToast({
                kind: "error",
                message: t("background.validation.nameRequired"),
                title: t("background.action.saveImageTags"),
              });
              return;
            }
            imageTagsSaveMutation.mutate(currentDraft.bg_tags);
          }}
          onSelectImage={setSelectedImageIndex}
          onUpdateImageTag={updateImageRowTag}
          onUploadImages={(paths) => imageUploadMutation.mutate(paths)}
          saveTagsPending={imageTagsSaveMutation.isPending}
          selectedImageIndex={selectedImageIndex}
          sprites={currentDraft.sprites}
          uploadPending={imageUploadMutation.isPending}
        />

        {/* BGM section */}
        <BackgroundMusicSection
          batchDeletePending={bgmBatchDeleteMutation.isPending}
          bgmList={currentDraft.bgm_list}
          bgmRowTags={bgmRowTags}
          currentBackgroundName={currentBackgroundName}
          deletePending={bgmDeleteMutation.isPending}
          id="background-bgm"
          onBatchDelete={() => {
            const validIndexes = selectedBgmIndexes.filter((i) => i >= 0 && i < currentDraft.bgm_list.length);
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
            if (!currentBackgroundName || !currentDraft.bgm_list.length) {
              showToast({ kind: "error", title: t("background.asset.clearBgm") });
              return;
            }
            setPendingDelete({ count: currentDraft.bgm_list.length, kind: "all-bgm", name: currentBackgroundName });
          }}
          onDelete={handleBgmDelete}
          onOpenBulkTags={openBulkBgmTagsDialog}
          onSortToggle={toggleBgmSort}
          onTagChange={updateBgmRowTag}
          onToggleAllSelection={toggleAllBgmSelection}
          onToggleSelection={toggleBgmSelection}
          onUpload={(paths) => bgmUploadMutation.mutate(paths)}
          selectedBgmIndexSet={selectedBgmIndexSet}
          sortDirection={bgmSort.direction}
          sortKey={bgmSort.key}
          sortedBgmItems={sortedBgmItems}
          uploadPending={bgmUploadMutation.isPending}
        />
      </section>

      <BackgroundTagsDialog
        draft={bulkImageTagsDraft}
        fieldLabel={t("background.field.bgTags")}
        help={t("background.asset.batchImageTagsHelp")}
        onChange={setBulkImageTagsDraft}
        onClose={() => setBulkImageTagsOpen(false)}
        onConfirm={confirmBulkImageTags}
        open={bulkImageTagsOpen}
        title={t("background.asset.batchImageTagsTitle")}
      />
      <BackgroundTagsDialog
        draft={bulkBgmTagsDraft}
        fieldLabel={t("background.field.bgmTags")}
        help={t("background.asset.batchBgmTagsHelp")}
        onChange={setBulkBgmTagsDraft}
        onClose={() => setBulkBgmTagsOpen(false)}
        onConfirm={confirmBulkBgmTags}
        open={bulkBgmTagsOpen}
        title={t("background.asset.batchBgmTagsTitle")}
      />

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
