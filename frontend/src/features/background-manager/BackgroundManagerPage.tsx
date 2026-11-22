import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FolderInput, FolderOutput, Languages, Plus, Save, Trash2, X } from "lucide-react";

import {
  backgroundsQueryKey,
  autoLabelBackgroundImages,
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
import { baseName, numberedTags, removeTagRows, tagContents } from "../../shared/assets/assetText";
import { suggestUniqueSpritePrefix } from "../../shared/assets/spritePrefix";
import { TAG_PREFIX_MUSIC, TAG_PREFIX_SCENE } from "../../shared/constants";
import { useDebouncedAutoSave } from "../../shared/hooks/useDebouncedAutoSave";
import { useI18n } from "../../shared/i18n";
import type { ImageAutoLabelResult, TaskSnapshot } from "../../shared/platform/types";
import {
  AlertDialog,
  AsyncButton,
  AutoSaveStatus,
  Button,
  EmptyState,
  handleIdentityKeyDown,
  InlineIdentityConfirm,
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
import { KnowledgeManagerPage } from "../knowledge-manager/KnowledgeManagerPage";
import { MediaAutoLabelProgressDialog } from "../media-auto-label/MediaAutoLabelProgressDialog";
import { useVisionAvailability } from "../media-auto-label/useVisionAvailability";
import {
  backgroundDeleteDialogCopy,
  createBackground,
  runBackgroundDeleteTarget,
  serializeBackgroundNonIdentity,
  upsertCatalogBackground,
  type BackgroundDeleteTarget,
  type BgmSortDirection,
  type BgmSortKey,
} from "./backgroundUtils";
import "./BackgroundManagerPage.css";

export function BackgroundManagerPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const visionAvailable = useVisionAvailability();
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
  const [autoLabelDialogOpen, setAutoLabelDialogOpen] = useState(false);
  const [autoLabelTask, setAutoLabelTask] = useState<TaskSnapshot<ImageAutoLabelResult> | null>(null);
  const [bgmSort, setBgmSort] = useState<{ direction: BgmSortDirection; key: BgmSortKey }>({
    direction: "asc",
    key: "index",
  });
  const [nameError, setNameError] = useState("");
  const [spritePrefixError, setSpritePrefixError] = useState("");
  const [spritePrefixTouched, setSpritePrefixTouched] = useState(false);
  const [identitySavingField, setIdentitySavingField] = useState<"name" | "sprite_prefix" | null>(null);
  const [syncedBackgroundKey, setSyncedBackgroundKey] = useState("");
  const isCreatingRef = useRef(isCreating);
  isCreatingRef.current = isCreating;
  const deletedBackgroundKeysRef = useRef<Set<string>>(new Set());
  const cancelAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const discardAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const previousSelectedNameRef = useRef("");
  const activeBackgroundKeyRef = useRef("");

  const inCreateMode = isCreating || data.length === 0;
  const existingPrefixes = useMemo(() => data.map((bg) => bg.sprite_prefix), [data]);

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
    !isCreating && (selected || (currentBackgroundName && data.some((bg) => bg.name === currentBackgroundName))),
  );

  useEffect(() => {
    if (!selected) {
      activeBackgroundKeyRef.current = "";
      setSyncedBackgroundKey("");
      return;
    }
    const selectedKey = selected.id || `name:${selected.name}`;
    if (selectedKey !== activeBackgroundKeyRef.current) {
      activeBackgroundKeyRef.current = selectedKey;
      setSyncedBackgroundKey(selectedKey);
      setSelectedName(selected.name);
      setDraft(structuredClone(selected));
      setDraftSourceName(selected.name);
      setSelectedBgmIndexes([]);
      setSelectedImageIndex(0);
      setNameError("");
      setSpritePrefixError("");
      setSpritePrefixTouched(false);
    } else if (selected.id) {
      setDraft((current) => (current.id ? current : { ...current, id: selected.id }));
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
      const nextKey = background.id || `name:${background.name}`;
      deletedBackgroundKeysRef.current.delete(nextKey);
      deletedBackgroundKeysRef.current.delete(`name:${background.name}`);
      isCreatingRef.current = false;
      activeBackgroundKeyRef.current = nextKey;
      setSyncedBackgroundKey(nextKey);
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, background, variables.originalName),
      );
      setIsCreating(false);
      setSpritePrefixTouched(false);
      if (!variables.originalName) {
        setNameError("");
        setSpritePrefixError("");
      }
      setSelectedName(background.name);
      setDraft((current) =>
        variables.originalName
          ? {
              ...structuredClone(background),
              name: current.name,
              sprite_prefix: current.sprite_prefix,
            }
          : structuredClone(background),
      );
      setDraftSourceName(background.name);
      if (!variables.originalName) {
        setSelectedBgmIndexes([]);
        setSelectedImageIndex(0);
      }
      showToast({ kind: "success", title: t("background.toast.saved") });
    },
  });

  const identityMutation = useMutation({
    mutationFn: async ({
      background,
      originalName,
      sourceKey,
    }: {
      background: Background;
      field: "name" | "sprite_prefix";
      originalName: string;
      sourceKey: string;
    }) => {
      await discardAutoSaveRef.current(sourceKey);
      return saveBackground(background, originalName);
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSettled() {
      setIdentitySavingField(null);
    },
    onSuccess(background, variables) {
      if (
        deletedBackgroundKeysRef.current.has(variables.sourceKey) ||
        deletedBackgroundKeysRef.current.has(`name:${variables.originalName}`)
      ) {
        return;
      }
      const nextKey = background.id || `name:${background.name}`;
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, background, variables.originalName),
      );
      if (!isCreatingRef.current && activeBackgroundKeyRef.current === variables.sourceKey) {
        activeBackgroundKeyRef.current = nextKey;
        setSyncedBackgroundKey(nextKey);
        setSelectedName(background.name);
        setDraftSourceName(background.name);
        setDraft((current) => ({
          ...current,
          ...(background.id ? { id: background.id } : {}),
          bgm_list: background.bgm_list,
          name: variables.field === "name" ? background.name : current.name,
          sprite_prefix: variables.field === "sprite_prefix" ? background.sprite_prefix : current.sprite_prefix,
          sprites: background.sprites,
        }));
        if (variables.field === "name") {
          setNameError("");
        } else {
          setSpritePrefixError("");
        }
      }
      showToast({ kind: "success", title: t("background.toast.saved") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (targetName: string) => {
      const target = data.find((item) => item.name === targetName);
      const targetKey = target ? target.id || `name:${target.name}` : `name:${targetName}`;
      deletedBackgroundKeysRef.current.add(targetKey);
      deletedBackgroundKeysRef.current.add(`name:${targetName}`);
      await cancelAutoSaveRef.current(targetKey);
      return deleteBackground(targetName);
    },
    onSuccess(_result, deletedName) {
      setSelectedName((current) => (current === deletedName ? "" : current));
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      showToast({ kind: "success", title: t("background.toast.deleted") });
    },
    onError(error, deletedName) {
      const target = data.find((item) => item.name === deletedName);
      if (target?.id) {
        deletedBackgroundKeysRef.current.delete(target.id);
      }
      deletedBackgroundKeysRef.current.delete(`name:${deletedName}`);
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
      for (const item of imported) {
        if (item.id) {
          deletedBackgroundKeysRef.current.delete(item.id);
        }
        deletedBackgroundKeysRef.current.delete(`name:${item.name}`);
      }
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      const lastImported = imported[imported.length - 1];
      if (lastImported) {
        isCreatingRef.current = false;
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
            ? numberedTags(TAG_PREFIX_MUSIC, result.bgmRowTags)
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
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, background),
      );
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
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, background),
      );
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bg_tags: background.bg_tags }));
      showToast({ kind: "success", title: t("background.action.saveImageTags") });
    },
  });

  const autoLabelMutation = useMutation({
    mutationFn: () =>
      autoLabelBackgroundImages(currentBackgroundName, {
        onTaskUpdate: setAutoLabelTask,
      }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("mediaAutoLabel.error"),
        title: t("mediaAutoLabel.action"),
      });
    },
    onSuccess(result) {
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        current.map((item) => (item.name === currentBackgroundName ? { ...item, bg_tags: result.tags } : item)),
      );
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bg_tags: result.tags }));
      showToast({
        kind: result.failedCount ? "info" : "success",
        message: t("mediaAutoLabel.complete", {
          annotated: result.annotatedCount,
          failed: result.failedCount,
          skipped: result.skippedCount,
        }),
        title: t("mediaAutoLabel.action"),
      });
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
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, background),
      );
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
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, background),
      );
      queryClient.invalidateQueries({ queryKey: backgroundsQueryKey });
      setDraft((current) => ({ ...current, bgm_tags: background.bgm_tags }));
      showToast({ kind: "success", title: t("background.action.saveBgmTags") });
    },
  });

  const imageDeleteMutation = useMutation({
    mutationFn: ({ index, name }: { index: number; itemCount: number; name: string; tagBlock: string }) =>
      deleteBackgroundImage(name, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.asset.uploadError"),
        title: t("common.remove"),
      });
    },
    onSuccess(background, variables) {
      const bgTags = removeTagRows(variables.tagBlock, variables.itemCount, [variables.index], TAG_PREFIX_SCENE);
      const nextBackground = { ...background, bg_tags: bgTags };
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        current.map((item) => (item.name === nextBackground.name ? nextBackground : item)),
      );
      setDraft((current) => ({
        ...current,
        bg_tags: removeTagRows(current.bg_tags, current.sprites.length, [variables.index], TAG_PREFIX_SCENE),
        sprites: background.sprites,
      }));
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
    mutationFn: ({ index, name }: { index: number; itemCount: number; name: string; tagBlock: string }) =>
      deleteBackgroundBgm(name, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.asset.uploadError"),
        title: t("common.remove"),
      });
    },
    onSuccess(background, variables) {
      const bgmTags = removeTagRows(variables.tagBlock, variables.itemCount, [variables.index], TAG_PREFIX_MUSIC);
      const nextBackground = { ...background, bgm_tags: bgmTags };
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        current.map((item) => (item.name === nextBackground.name ? nextBackground : item)),
      );
      setDraft((current) => ({
        ...current,
        bgm_list: background.bgm_list,
        bgm_tags: removeTagRows(current.bgm_tags, current.bgm_list.length, [variables.index], TAG_PREFIX_MUSIC),
      }));
      setSelectedBgmIndexes([]);
      showToast({ kind: "success", title: t("common.remove") });
    },
  });

  const bgmBatchDeleteMutation = useMutation({
    mutationFn: async ({ indexes, name }: { indexes: number[]; itemCount: number; name: string; tagBlock: string }) => {
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
    onSuccess(background, variables) {
      const bgmTags = removeTagRows(variables.tagBlock, variables.itemCount, variables.indexes, TAG_PREFIX_MUSIC);
      const nextBackground = { ...background, bgm_tags: bgmTags };
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        current.map((item) => (item.name === nextBackground.name ? nextBackground : item)),
      );
      setDraft((current) => ({
        ...current,
        bgm_list: background.bgm_list,
        bgm_tags: removeTagRows(current.bgm_tags, current.bgm_list.length, variables.indexes, TAG_PREFIX_MUSIC),
      }));
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
    if (name === "sprite_prefix") {
      setSpritePrefixTouched(true);
      setSpritePrefixError("");
    }
    if (name === "name" && String(value).trim()) {
      setNameError("");
    }
    setDraft((current) => {
      const baseDraft = draftMatchesSelection ? current : structuredClone(currentDraft);
      const next = { ...baseDraft, [name]: value };
      if (name === "name" && inCreateMode && !spritePrefixTouched) {
        next.sprite_prefix = suggestUniqueSpritePrefix(String(value), existingPrefixes, "bg");
      }
      return next;
    });
    setDraftSourceName(currentBackgroundName);
  };

  const updateBgmRowTag = useCallback(
    (index: number, value: string) => {
      setDraft((current) => {
        const baseDraft = draftMatchesSelection ? current : currentDraft;
        const tags = tagContents(baseDraft.bgm_tags, baseDraft.bgm_list.length);
        tags[index] = value;
        return { ...baseDraft, bgm_tags: numberedTags(TAG_PREFIX_MUSIC, tags) };
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
        return { ...baseDraft, bg_tags: numberedTags(TAG_PREFIX_SCENE, tags) };
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
    if (selected && nextTags.trim() && !saveMutation.isPending) {
      saveMutation.mutate({
        background: {
          ...currentDraft,
          ...(selected.id ? { id: selected.id } : {}),
          bg_tags: nextTags,
          name: selected.name,
          sprite_prefix: selected.sprite_prefix,
        },
        originalName: selected.name,
      });
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
    if (selected && nextTags.trim() && !saveMutation.isPending) {
      saveMutation.mutate({
        background: {
          ...currentDraft,
          ...(selected.id ? { id: selected.id } : {}),
          bgm_tags: nextTags,
          name: selected.name,
          sprite_prefix: selected.sprite_prefix,
        },
        originalName: selected.name,
      });
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
      deleteBgm: (input) =>
        bgmDeleteMutation.mutate({
          ...input,
          itemCount: currentDraft.bgm_list.length,
          tagBlock: currentDraft.bgm_tags,
        }),
      deleteImage: (input) =>
        imageDeleteMutation.mutate({
          ...input,
          itemCount: currentDraft.sprites.length,
          tagBlock: currentDraft.bg_tags,
        }),
      deleteSelectedBgm: (input) =>
        bgmBatchDeleteMutation.mutate({
          ...input,
          itemCount: currentDraft.bgm_list.length,
          tagBlock: currentDraft.bgm_tags,
        }),
    });
  };

  const pendingDeleteCopy = pendingDelete ? backgroundDeleteDialogCopy(pendingDelete, t) : null;

  const selectedBackgroundKey = selected ? selected.id || `name:${selected.name}` : "";
  const isDraftSynced = Boolean(selected && syncedBackgroundKey === selectedBackgroundKey && draftMatchesSelection);
  const nameDirty = Boolean(!inCreateMode && isDraftSynced && currentDraft.name !== selected!.name);
  const spritePrefixDirty = Boolean(
    !inCreateMode && isDraftSynced && currentDraft.sprite_prefix !== selected!.sprite_prefix,
  );

  const liveNameError = useMemo(() => {
    if (!nameDirty || !selected) {
      return nameError;
    }
    const trimmed = currentDraft.name.trim();
    if (!trimmed) {
      return t("background.validation.nameRequired");
    }
    const duplicate = data.some(
      (item) =>
        item !== selected &&
        (selected.id ? item.id !== selected.id : item.name !== selected.name) &&
        item.name.trim().toLowerCase() === trimmed.toLowerCase(),
    );
    return duplicate ? t("identity.error.duplicateName", { name: trimmed }) : "";
  }, [currentDraft.name, data, nameDirty, nameError, selected, t]);

  const liveSpritePrefixError = useMemo(() => {
    if (!spritePrefixDirty || !selected) {
      return spritePrefixError;
    }
    const trimmed = currentDraft.sprite_prefix.trim();
    if (!trimmed) {
      return t("character.validation.spritePrefixRequired");
    }
    if (!/^[\x00-\x7F]+$/.test(trimmed)) {
      return t("character.validation.spritePrefixAscii");
    }
    const duplicate = data.some(
      (item) =>
        item !== selected &&
        (selected.id ? item.id !== selected.id : item.name !== selected.name) &&
        item.sprite_prefix.trim().toLowerCase() === trimmed.toLowerCase(),
    );
    return duplicate ? t("identity.error.duplicatePrefix", { prefix: trimmed }) : "";
  }, [currentDraft.sprite_prefix, data, selected, spritePrefixDirty, spritePrefixError, t]);

  const baselineAutoSaveKey = useMemo(() => (selected ? serializeBackgroundNonIdentity(selected) : ""), [selected]);
  const currentAutoSaveKey = useMemo(
    () => (selected ? serializeBackgroundNonIdentity(currentDraft) : ""),
    [currentDraft, selected],
  );

  const resolveLatestSelectedBackground = useCallback((): Background | undefined => {
    if (!selected) {
      return undefined;
    }
    const catalog = queryClient.getQueryData<Background[]>(backgroundsQueryKey) ?? data;
    return (
      (selected.id ? catalog.find((item) => item.id === selected.id) : undefined) ??
      catalog.find((item) => item.name === selected.name) ??
      selected
    );
  }, [data, queryClient, selected]);

  const autoSave = useDebouncedAutoSave<{ background: Background; originalName: string }>({
    baselineKey: baselineAutoSaveKey,
    buildPayload: () => {
      const latestSelected = resolveLatestSelectedBackground() ?? selected!;
      return {
        background: {
          ...latestSelected,
          ...(latestSelected.id ? { id: latestSelected.id } : {}),
          bg_tags: currentDraft.bg_tags,
          bgm_tags: currentDraft.bgm_tags,
          name: latestSelected.name,
          sprite_prefix: latestSelected.sprite_prefix,
        },
        originalName: latestSelected.name,
      };
    },
    currentKey: currentAutoSaveKey,
    enabled: Boolean(
      !inCreateMode &&
      isDraftSynced &&
      identitySavingField === null &&
      !identityMutation.isPending &&
      !saveMutation.isPending &&
      !deleteMutation.isPending &&
      !bulkImageTagsOpen &&
      !bulkBgmTagsOpen &&
      pendingDelete?.kind !== "background",
    ),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("background.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    async onSave({ background, originalName }, { isSuperseded, resetKey }) {
      const saved = await saveBackground(background, originalName);
      if (
        isSuperseded() ||
        deletedBackgroundKeysRef.current.has(resetKey) ||
        deletedBackgroundKeysRef.current.has(`name:${originalName}`)
      ) {
        return;
      }
      queryClient.setQueryData<Background[]>(backgroundsQueryKey, (current = []) =>
        upsertCatalogBackground(current, saved, originalName),
      );
      if (saved.id && !isCreatingRef.current && activeBackgroundKeyRef.current === resetKey) {
        activeBackgroundKeyRef.current = saved.id;
        setSyncedBackgroundKey(saved.id);
        setDraft((current) => (current.id ? current : { ...current, id: saved.id }));
      }
    },
    resetKey: selected ? selected.id || `name:${selected.name}` : "__creating__",
  });
  cancelAutoSaveRef.current = autoSave.cancel;
  discardAutoSaveRef.current = autoSave.discardPending;

  const confirmIdentityField = (field: "name" | "sprite_prefix") => {
    if (!selected || identitySavingField !== null || identityMutation.isPending) {
      return;
    }
    const fieldError = field === "name" ? liveNameError : liveSpritePrefixError;
    if (fieldError) {
      showToast({
        kind: "error",
        message: fieldError,
        title: t("common.validationFailed"),
      });
      return;
    }
    autoSave.discardPending();
    const latestSelected = resolveLatestSelectedBackground() ?? selected;
    setIdentitySavingField(field);
    identityMutation.mutate({
      background: {
        ...latestSelected,
        ...(latestSelected.id ? { id: latestSelected.id } : {}),
        bg_tags: currentDraft.bg_tags,
        bgm_tags: currentDraft.bgm_tags,
        name: field === "name" ? currentDraft.name.trim() : latestSelected.name,
        sprite_prefix: field === "sprite_prefix" ? currentDraft.sprite_prefix.trim() : latestSelected.sprite_prefix,
      },
      field,
      originalName: latestSelected.name,
      sourceKey: selectedBackgroundKey,
    });
  };

  const cancelIdentityField = (field: "name" | "sprite_prefix") => {
    if (!selected) {
      return;
    }
    if (field === "name") {
      setDraft((current) => ({ ...current, name: selected.name }));
      setNameError("");
    } else {
      setDraft((current) => ({ ...current, sprite_prefix: selected.sprite_prefix }));
      setSpritePrefixError("");
    }
  };

  const buildBackgroundCreateInput = () => {
    const trimmedName = currentDraft.name.trim();
    if (!trimmedName) {
      setNameError(t("background.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("common.validationFailed"),
      });
      return null;
    }
    if (data.some((item) => item.name.trim().toLowerCase() === trimmedName.toLowerCase())) {
      const duplicateError = t("identity.error.duplicateName", { name: trimmedName });
      setNameError(duplicateError);
      showToast({
        kind: "error",
        message: duplicateError,
        title: t("common.validationFailed"),
      });
      return null;
    }
    const spritePrefix = currentDraft.sprite_prefix.trim();
    const prefixError = !spritePrefix
      ? t("character.validation.spritePrefixRequired")
      : !/^[\x00-\x7F]+$/.test(spritePrefix)
        ? t("character.validation.spritePrefixAscii")
        : data.some((item) => item.sprite_prefix.trim().toLowerCase() === spritePrefix.toLowerCase())
          ? t("identity.error.duplicatePrefix", { prefix: spritePrefix })
          : "";
    if (prefixError) {
      setSpritePrefixError(prefixError);
      showToast({
        kind: "error",
        message: prefixError,
        title: t("common.validationFailed"),
      });
      return null;
    }
    const { id: _omittedId, ...restDraft } = currentDraft;
    return {
      background: {
        ...restDraft,
        name: trimmedName,
        sprite_prefix: spritePrefix,
      },
      originalName: undefined,
    };
  };

  const saveDraft = () => {
    const input = buildBackgroundCreateInput();
    if (!input) {
      return;
    }
    saveMutation.mutate(input);
  };

  const startCreatingBackground = () => {
    autoSave.flush();
    previousSelectedNameRef.current = currentBackgroundName || data[0]?.name || "";
    activeBackgroundKeyRef.current = "";
    isCreatingRef.current = true;
    setIsCreating(true);
    setSpritePrefixTouched(false);
    setSelectedName("");
    setDraft(createBackground(existingPrefixes));
    setDraftSourceName("");
    setSelectedBgmIndexes([]);
    setSelectedImageIndex(0);
    setNameError("");
    setSpritePrefixError("");
  };

  const cancelCreatingBackground = () => {
    if (!data.length) {
      return;
    }
    const targetName =
      (previousSelectedNameRef.current && data.some((item) => item.name === previousSelectedNameRef.current)
        ? previousSelectedNameRef.current
        : data[0]?.name) || "";
    activeBackgroundKeyRef.current = "";
    isCreatingRef.current = false;
    setIsCreating(false);
    setSpritePrefixTouched(false);
    setNameError("");
    setSpritePrefixError("");
    setSelectedName(targetName);
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
    { id: "background-knowledge", label: t("knowledge.title") },
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
                autoSave.flush();
                isCreatingRef.current = false;
                setIsCreating(false);
                setSpritePrefixTouched(false);
                setNameError("");
                setSpritePrefixError("");
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
            <Button
              className="button--header-icon"
              data-tooltip={t("common.new")}
              icon={<Plus aria-hidden className="button__icon" />}
              onClick={startCreatingBackground}
            >
              {t("common.new")}
            </Button>
            <AsyncButton
              className="button--header-icon"
              data-tooltip={t("common.import")}
              icon={<FolderInput aria-hidden className="button__icon" />}
              loading={importMutation.isPending}
              onClick={() => setImportPickerOpen(true)}
            >
              {t("common.import")}
            </AsyncButton>
            <AsyncButton
              className="button--header-icon"
              data-tooltip={t("common.export")}
              icon={<FolderOutput aria-hidden className="button__icon" />}
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
            {inCreateMode ? (
              <>
                {isCreating && data.length > 0 ? (
                  <Button
                    icon={<X aria-hidden className="button__icon" />}
                    onClick={cancelCreatingBackground}
                    variant="ghost"
                  >
                    {t("common.cancel")}
                  </Button>
                ) : null}
                <AsyncButton
                  icon={<Save aria-hidden className="button__icon" />}
                  loading={saveMutation.isPending}
                  onClick={saveDraft}
                  variant="primary"
                >
                  {t("common.create")}
                </AsyncButton>
              </>
            ) : (
              <AutoSaveStatus
                errorMessage={autoSave.errorMessage}
                onRetry={autoSave.retry}
                pendingIdentity={nameDirty || spritePrefixDirty}
                phase={autoSave.phase}
              />
            )}
          </div>
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
            <div className="field-row">
              <label className="field-row__label" htmlFor="background-info-name-input">
                {t("background.field.name")}
              </label>
              <span className="field-row__control">
                <div className="identity-field-group">
                  <TextInput
                    className={liveNameError ? "input--error" : ""}
                    id="background-info-name-input"
                    onChange={(event) => update("name", event.target.value)}
                    onKeyDown={(event) =>
                      handleIdentityKeyDown(event, {
                        canConfirm: !liveNameError && identitySavingField === null,
                        disabled: identitySavingField !== null,
                        isDirty: nameDirty,
                        onCancel: () => cancelIdentityField("name"),
                        onConfirm: () => confirmIdentityField("name"),
                      })
                    }
                    value={currentDraft.name}
                  />
                  <InlineIdentityConfirm
                    confirmDisabled={Boolean(liveNameError)}
                    disabled={identitySavingField !== null && identitySavingField !== "name"}
                    fieldLabel={t("background.field.name")}
                    loading={identitySavingField === "name"}
                    onCancel={() => cancelIdentityField("name")}
                    onConfirm={() => confirmIdentityField("name")}
                    visible={nameDirty}
                  />
                </div>
                {liveNameError ? <span className="field-error">{liveNameError}</span> : null}
              </span>
            </div>
            <div className="field-row">
              <label className="field-row__label" htmlFor="background-info-prefix-input">
                {t("background.field.spritePrefix")}
              </label>
              <span className="field-row__control">
                <div className="identity-field-group">
                  <TextInput
                    className={liveSpritePrefixError ? "input--error" : ""}
                    id="background-info-prefix-input"
                    onChange={(event) => update("sprite_prefix", event.target.value)}
                    onKeyDown={(event) =>
                      handleIdentityKeyDown(event, {
                        canConfirm: !liveSpritePrefixError && identitySavingField === null,
                        disabled: identitySavingField !== null,
                        isDirty: spritePrefixDirty,
                        onCancel: () => cancelIdentityField("sprite_prefix"),
                        onConfirm: () => confirmIdentityField("sprite_prefix"),
                      })
                    }
                    value={currentDraft.sprite_prefix}
                  />
                  <InlineIdentityConfirm
                    confirmDisabled={Boolean(liveSpritePrefixError)}
                    disabled={identitySavingField !== null && identitySavingField !== "sprite_prefix"}
                    fieldLabel={t("background.field.spritePrefix")}
                    loading={identitySavingField === "sprite_prefix"}
                    onCancel={() => cancelIdentityField("sprite_prefix")}
                    onConfirm={() => confirmIdentityField("sprite_prefix")}
                    visible={spritePrefixDirty}
                  />
                </div>
                {liveSpritePrefixError ? <span className="field-error">{liveSpritePrefixError}</span> : null}
              </span>
            </div>
          </div>
        </section>

        {/* Sprite gallery */}
        <BackgroundSpriteGallery
          autoLabelAvailable={visionAvailable}
          autoLabelDisabled={
            !isSavedBackground || !currentDraft.sprites.length || !imageRowTags.some((tag) => !tag.trim())
          }
          autoLabelPending={autoLabelMutation.isPending}
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
          onAutoLabel={() => {
            setAutoLabelTask(null);
            setAutoLabelDialogOpen(true);
            autoLabelMutation.mutate();
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
        <section aria-label={t("knowledge.title")} className="section page-section-anchor" id="background-knowledge">
          <KnowledgeManagerPage embedded />
        </section>
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
      <MediaAutoLabelProgressDialog
        onClose={() => setAutoLabelDialogOpen(false)}
        open={autoLabelDialogOpen}
        pending={autoLabelMutation.isPending}
        result={autoLabelMutation.data ?? null}
        task={autoLabelTask}
      />
    </div>
  );
}
