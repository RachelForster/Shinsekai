import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  deleteAllBackgroundBgm,
  deleteBackgroundBgm,
  saveBackgroundBgmTags,
  uploadBackgroundBgm,
} from "../../../entities/background/repository";
import type { Background } from "../../../entities/config/types";
import { baseName, numberedTags, removeTagRows, tagContents } from "../../../shared/assets/assetText";
import { TAG_PREFIX_MUSIC } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import { useToast, withSectionBusy } from "../../../shared/ui";
import type { BackgroundPageContext } from "../backgroundContext";
import {
  backgroundDeleteDialogCopy,
  type BackgroundDeleteTarget,
  type BgmSortDirection,
  type BgmSortKey,
} from "../backgroundUtils";

type BgmDeleteTarget = Extract<BackgroundDeleteTarget, { kind: "bgm" | "selected-bgm" | "all-bgm" }>;

export function useBackgroundBgmController(ctx: BackgroundPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [selectedBgmIndexes, setSelectedBgmIndexes] = useState<number[]>([]);
  const [bulkBgmTagsOpen, setBulkBgmTagsOpen] = useState(false);
  const [bulkBgmTagsDraft, setBulkBgmTagsDraft] = useState("");
  const [bgmSort, setBgmSort] = useState<{ direction: BgmSortDirection; key: BgmSortKey }>({
    direction: "asc",
    key: "index",
  });
  const [pendingDelete, setPendingDelete] = useState<BgmDeleteTarget | null>(null);

  useEffect(() => {
    setSelectedBgmIndexes([]);
  }, [ctx.selectedBackgroundKey]);

  useEffect(() => () => ctx.setSectionBusy("background-bgm:bulk-tags", false), [ctx.setSectionBusy]);

  const bgmUploadMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-bgm", {
      mutationFn: (paths: string[]) =>
        uploadBackgroundBgm({ bgmTags: ctx.currentDraft.bgm_tags, name: ctx.currentBackgroundName, paths }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("background.asset.uploadError"),
          title: t("background.asset.uploadBgm"),
        });
      },
      onSuccess(background) {
        ctx.syncSavedBackground(background, (current, saved) => ({
          ...current,
          bgm_list: saved.bgm_list,
          bgm_tags: saved.bgm_tags,
        }));
        showToast({ kind: "success", title: t("background.asset.uploadBgm") });
      },
    }),
  );

  const bgmTagsSaveMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-bgm", {
      mutationFn: (bgmTags: string) => saveBackgroundBgmTags({ bgmTags, name: ctx.currentBackgroundName }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("background.error.saveFallback"),
          title: t("common.saveFailed"),
        });
      },
      onSuccess(background) {
        ctx.syncSavedBackground(background, (current, saved) => ({
          ...current,
          bgm_tags: saved.bgm_tags,
        }));
        showToast({ kind: "success", title: t("background.action.saveBgmTags") });
      },
    }),
  );

  const bgmDeleteMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-bgm", {
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
        ctx.syncSavedBackground(
          { ...background, bgm_tags: bgmTags },
          (current, saved) => ({
            ...current,
            bgm_list: saved.bgm_list,
            bgm_tags: removeTagRows(current.bgm_tags, current.bgm_list.length, [variables.index], TAG_PREFIX_MUSIC),
          }),
          { invalidate: false, mode: "replace" },
        );
        setSelectedBgmIndexes([]);
        showToast({ kind: "success", title: t("common.remove") });
      },
    }),
  );

  const bgmBatchDeleteMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-bgm", {
      mutationFn: async ({
        indexes,
        name,
      }: {
        indexes: number[];
        itemCount: number;
        name: string;
        tagBlock: string;
      }) => {
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
        ctx.syncSavedBackground(
          { ...background, bgm_tags: bgmTags },
          (current, saved) => ({
            ...current,
            bgm_list: saved.bgm_list,
            bgm_tags: removeTagRows(current.bgm_tags, current.bgm_list.length, variables.indexes, TAG_PREFIX_MUSIC),
          }),
          { invalidate: false, mode: "replace" },
        );
        setSelectedBgmIndexes([]);
        showToast({ kind: "success", title: t("background.asset.deleteSelectedBgm") });
      },
    }),
  );

  const bgmDeleteAllMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-bgm", {
      mutationFn: (name: string) => deleteAllBackgroundBgm(name),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("background.asset.uploadError"),
          title: t("background.asset.clearBgm"),
        });
      },
      onSuccess(background) {
        ctx.syncSavedBackground(
          background,
          (current, saved) => ({ ...current, bgm_list: saved.bgm_list, bgm_tags: saved.bgm_tags }),
          { mode: "none" },
        );
        setSelectedBgmIndexes([]);
        showToast({ kind: "success", title: t("background.asset.clearBgm") });
      },
    }),
  );

  // Reference kept so TypeScript knows bgmTagsSaveMutation stays part of BGM capabilities if wired later
  void bgmTagsSaveMutation;

  const updateBgmRowTag = useCallback(
    (index: number, value: string) => {
      ctx.patchActiveDraft((baseDraft) => {
        const tags = tagContents(baseDraft.bgm_tags, baseDraft.bgm_list.length);
        tags[index] = value;
        return { ...baseDraft, bgm_tags: numberedTags(TAG_PREFIX_MUSIC, tags) };
      });
    },
    [ctx.patchActiveDraft],
  );

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
      const validSelection = current.filter((index) => index >= 0 && index < ctx.currentDraft.bgm_list.length);
      const allSelected =
        ctx.currentDraft.bgm_list.length > 0 && validSelection.length === ctx.currentDraft.bgm_list.length;
      return allSelected ? [] : ctx.currentDraft.bgm_list.map((_, index) => index);
    });
  }, [ctx.currentDraft.bgm_list]);

  const toggleBgmSort = useCallback((key: BgmSortKey) => {
    setBgmSort((current) => {
      if (current.key === key) {
        return { ...current, direction: current.direction === "asc" ? "desc" : "asc" };
      }
      return { direction: "asc", key };
    });
  }, []);

  const openBulkBgmTagsDialog = useCallback(() => {
    ctx.setSectionBusy("background-bgm:bulk-tags", true);
    setBulkBgmTagsDraft(ctx.currentDraft.bgm_tags);
    setBulkBgmTagsOpen(true);
  }, [ctx.currentDraft.bgm_tags, ctx.setSectionBusy]);

  const confirmBulkBgmTags = useCallback(() => {
    const nextTags = bulkBgmTagsDraft;
    ctx.setSectionBusy("background-bgm:bulk-tags", false);
    setBulkBgmTagsOpen(false);
    ctx.saveBulkTags("bgm_tags", nextTags);
  }, [bulkBgmTagsDraft, ctx.saveBulkTags, ctx.setSectionBusy]);

  const handleBgmDelete = useCallback(
    (index: number) => {
      const path = ctx.currentDraft.bgm_list[index];
      if (!ctx.currentBackgroundName || !path) {
        showToast({ kind: "error", title: t("common.remove") });
        return;
      }
      setPendingDelete({
        filename: baseName(path) || `${index + 1}`,
        index,
        kind: "bgm",
        name: ctx.currentBackgroundName,
      });
    },
    [ctx.currentBackgroundName, ctx.currentDraft.bgm_list, showToast, t],
  );

  const requestBatchDelete = useCallback(() => {
    const validIndexes = selectedBgmIndexes.filter((i) => i >= 0 && i < ctx.currentDraft.bgm_list.length);
    if (!validIndexes.length) {
      showToast({ kind: "error", title: t("background.asset.noSelectedBgm") });
      return;
    }
    setPendingDelete({
      count: validIndexes.length,
      indexes: validIndexes,
      kind: "selected-bgm",
      name: ctx.currentBackgroundName,
    });
  }, [ctx.currentBackgroundName, ctx.currentDraft.bgm_list.length, selectedBgmIndexes, showToast, t]);

  const requestClearAll = useCallback(() => {
    if (!ctx.currentBackgroundName || !ctx.currentDraft.bgm_list.length) {
      showToast({ kind: "error", title: t("background.asset.clearBgm") });
      return;
    }
    setPendingDelete({ count: ctx.currentDraft.bgm_list.length, kind: "all-bgm", name: ctx.currentBackgroundName });
  }, [ctx.currentBackgroundName, ctx.currentDraft.bgm_list.length, showToast, t]);

  const confirmPendingDelete = useCallback(() => {
    if (!pendingDelete) {
      return;
    }
    const target = pendingDelete;
    setPendingDelete(null);
    if (target.kind === "bgm") {
      bgmDeleteMutation.mutate({
        index: target.index,
        itemCount: ctx.currentDraft.bgm_list.length,
        name: target.name,
        tagBlock: ctx.currentDraft.bgm_tags,
      });
    } else if (target.kind === "selected-bgm") {
      bgmBatchDeleteMutation.mutate({
        indexes: target.indexes,
        itemCount: ctx.currentDraft.bgm_list.length,
        name: target.name,
        tagBlock: ctx.currentDraft.bgm_tags,
      });
    } else {
      bgmDeleteAllMutation.mutate(target.name);
    }
  }, [
    bgmBatchDeleteMutation,
    bgmDeleteAllMutation,
    bgmDeleteMutation,
    ctx.currentDraft.bgm_list.length,
    ctx.currentDraft.bgm_tags,
    pendingDelete,
  ]);

  const bgmRowTags = useMemo(
    () => tagContents(ctx.currentDraft.bgm_tags, ctx.currentDraft.bgm_list.length),
    [ctx.currentDraft.bgm_list.length, ctx.currentDraft.bgm_tags],
  );
  const sortedBgmItems = useMemo(() => {
    const direction = bgmSort.direction === "asc" ? 1 : -1;
    return ctx.currentDraft.bgm_list
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
  }, [bgmSort.direction, bgmSort.key, ctx.currentDraft.bgm_list]);
  const selectedBgmIndexSet = useMemo(() => new Set(selectedBgmIndexes), [selectedBgmIndexes]);
  const pendingDeleteCopy = pendingDelete ? backgroundDeleteDialogCopy(pendingDelete, t) : null;

  return {
    batchDeletePending: bgmBatchDeleteMutation.isPending,
    bgmRowTags,
    bulkBgmTagsDraft,
    bulkBgmTagsOpen,
    cancelPendingDelete: () => setPendingDelete(null),
    closeBulkBgmTags: () => {
      ctx.setSectionBusy("background-bgm:bulk-tags", false);
      setBulkBgmTagsOpen(false);
    },
    confirmBulkBgmTags,
    confirmPendingDelete,
    deletePending: bgmDeleteMutation.isPending,
    handleBgmDelete,
    openBulkBgmTagsDialog,
    pendingDeleteCopy,
    pendingDeleteOpen: Boolean(pendingDelete),
    requestBatchDelete,
    requestClearAll,
    selectedBgmIndexSet,
    setBulkBgmTagsDraft,
    sortDirection: bgmSort.direction,
    sortKey: bgmSort.key,
    sortedBgmItems,
    toggleAllBgmSelection,
    toggleBgmSelection,
    toggleBgmSort,
    updateBgmRowTag,
    uploadBgm: (paths: string[]) => bgmUploadMutation.mutate(paths),
    uploadPending: bgmUploadMutation.isPending,
  };
}
