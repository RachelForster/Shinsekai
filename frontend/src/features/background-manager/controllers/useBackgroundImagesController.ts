import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  autoLabelBackgroundImages,
  deleteAllBackgroundImages,
  deleteBackgroundImage,
  saveBackgroundImageTags,
  uploadBackgroundImages,
} from "../../../entities/background/repository";
import { baseName, numberedTags, removeTagRows, tagContents } from "../../../shared/assets/assetText";
import { TAG_PREFIX_SCENE } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import type { ImageAutoLabelResult, TaskSnapshot } from "../../../shared/platform/types";
import { useToast, withSectionBusy } from "../../../shared/ui";
import type { BackgroundPageContext } from "../backgroundContext";
import { backgroundDeleteDialogCopy, type BackgroundDeleteTarget } from "../backgroundUtils";

type ImageDeleteTarget = Extract<BackgroundDeleteTarget, { kind: "image" | "all-images" }>;

export function useBackgroundImagesController(ctx: BackgroundPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);
  const [bulkImageTagsOpen, setBulkImageTagsOpen] = useState(false);
  const [bulkImageTagsDraft, setBulkImageTagsDraft] = useState("");
  const [autoLabelDialogOpen, setAutoLabelDialogOpen] = useState(false);
  const [autoLabelTask, setAutoLabelTask] = useState<TaskSnapshot<ImageAutoLabelResult> | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ImageDeleteTarget | null>(null);

  useEffect(() => {
    setSelectedImageIndex(0);
  }, [ctx.selectedBackgroundKey]);

  useEffect(() => {
    setSelectedImageIndex((current) => Math.min(current, Math.max(0, ctx.currentDraft.sprites.length - 1)));
  }, [ctx.currentDraft.sprites.length]);

  useEffect(() => () => ctx.setSectionBusy("background-images:bulk-tags", false), [ctx.setSectionBusy]);

  const imageUploadMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-images", {
      mutationFn: (paths: string[]) =>
        uploadBackgroundImages({ bgTags: ctx.currentDraft.bg_tags, name: ctx.currentBackgroundName, paths }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("background.asset.uploadError"),
          title: t("background.asset.uploadImages"),
        });
      },
      onSuccess(background) {
        ctx.syncSavedBackground(background, (current, saved) => ({
          ...current,
          bg_tags: saved.bg_tags,
          sprites: saved.sprites,
        }));
        showToast({ kind: "success", title: t("background.asset.uploadImages") });
      },
    }),
  );

  const imageTagsSaveMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-images", {
      mutationFn: (bgTags: string) => saveBackgroundImageTags({ bgTags, name: ctx.currentBackgroundName }),
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
          bg_tags: saved.bg_tags,
        }));
        showToast({ kind: "success", title: t("background.action.saveImageTags") });
      },
    }),
  );

  const autoLabelMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-images", {
      mutationFn: () =>
        autoLabelBackgroundImages(ctx.currentBackgroundName, {
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
        ctx.syncSavedBackground(
          {
            ...(ctx.selected ?? ctx.currentDraft),
            bg_tags: result.tags,
            name: ctx.currentBackgroundName,
          },
          (current) => ({ ...current, bg_tags: result.tags }),
          { mode: "replace" },
        );
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
    }),
  );

  const imageDeleteMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-images", {
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
        ctx.syncSavedBackground(
          { ...background, bg_tags: bgTags },
          (current, saved) => ({
            ...current,
            bg_tags: removeTagRows(current.bg_tags, current.sprites.length, [variables.index], TAG_PREFIX_SCENE),
            sprites: saved.sprites,
          }),
          { invalidate: false, mode: "replace" },
        );
        showToast({ kind: "success", title: t("common.remove") });
      },
    }),
  );

  const imageDeleteAllMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "background-images", {
      mutationFn: (name: string) => deleteAllBackgroundImages(name),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("background.asset.uploadError"),
          title: t("background.asset.clearImages"),
        });
      },
      onSuccess(background) {
        ctx.syncSavedBackground(
          background,
          (current, saved) => ({ ...current, bg_tags: saved.bg_tags, sprites: saved.sprites }),
          { mode: "none" },
        );
        showToast({ kind: "success", title: t("background.asset.clearImages") });
      },
    }),
  );

  const updateImageRowTag = useCallback(
    (index: number, value: string) => {
      ctx.patchActiveDraft((baseDraft) => {
        const tags = tagContents(baseDraft.bg_tags, baseDraft.sprites.length);
        tags[index] = value;
        return { ...baseDraft, bg_tags: numberedTags(TAG_PREFIX_SCENE, tags) };
      });
    },
    [ctx.patchActiveDraft],
  );

  const openBulkImageTagsDialog = useCallback(() => {
    ctx.setSectionBusy("background-images:bulk-tags", true);
    setBulkImageTagsDraft(ctx.currentDraft.bg_tags);
    setBulkImageTagsOpen(true);
  }, [ctx.currentDraft.bg_tags, ctx.setSectionBusy]);

  const confirmBulkImageTags = useCallback(() => {
    const nextTags = bulkImageTagsDraft;
    ctx.setSectionBusy("background-images:bulk-tags", false);
    setBulkImageTagsOpen(false);
    ctx.saveBulkTags("bg_tags", nextTags);
  }, [bulkImageTagsDraft, ctx.saveBulkTags, ctx.setSectionBusy]);

  const handleImageDelete = useCallback(
    (index: number) => {
      const image = ctx.currentDraft.sprites[index];
      if (!ctx.currentBackgroundName || !image) {
        showToast({ kind: "error", title: t("common.remove") });
        return;
      }
      setPendingDelete({
        filename: baseName(image.path) || `${index + 1}`,
        index,
        kind: "image",
        name: ctx.currentBackgroundName,
      });
    },
    [ctx.currentBackgroundName, ctx.currentDraft.sprites, showToast, t],
  );

  const requestClearImages = useCallback(() => {
    if (!ctx.currentBackgroundName || !ctx.currentDraft.sprites.length) {
      showToast({ kind: "error", title: t("background.asset.clearImages") });
      return;
    }
    setPendingDelete({
      count: ctx.currentDraft.sprites.length,
      kind: "all-images",
      name: ctx.currentBackgroundName,
    });
  }, [ctx.currentBackgroundName, ctx.currentDraft.sprites.length, showToast, t]);

  const handleSaveImageTags = useCallback(() => {
    if (!ctx.currentBackgroundName) {
      showToast({
        kind: "error",
        message: t("background.validation.nameRequired"),
        title: t("background.action.saveImageTags"),
      });
      return;
    }
    imageTagsSaveMutation.mutate(ctx.currentDraft.bg_tags);
  }, [ctx.currentBackgroundName, ctx.currentDraft.bg_tags, imageTagsSaveMutation, showToast, t]);

  const handleAutoLabel = useCallback(() => {
    setAutoLabelTask(null);
    setAutoLabelDialogOpen(true);
    autoLabelMutation.mutate();
  }, [autoLabelMutation]);

  const confirmPendingDelete = useCallback(() => {
    if (!pendingDelete) {
      return;
    }
    const target = pendingDelete;
    setPendingDelete(null);
    if (target.kind === "image") {
      imageDeleteMutation.mutate({
        index: target.index,
        itemCount: ctx.currentDraft.sprites.length,
        name: target.name,
        tagBlock: ctx.currentDraft.bg_tags,
      });
    } else {
      imageDeleteAllMutation.mutate(target.name);
    }
  }, [
    ctx.currentDraft.bg_tags,
    ctx.currentDraft.sprites.length,
    imageDeleteAllMutation,
    imageDeleteMutation,
    pendingDelete,
  ]);

  const imageRowTags = useMemo(
    () => tagContents(ctx.currentDraft.bg_tags, ctx.currentDraft.sprites.length),
    [ctx.currentDraft.bg_tags, ctx.currentDraft.sprites.length],
  );
  const autoLabelDisabled =
    !ctx.isSavedBackground || !ctx.currentDraft.sprites.length || !imageRowTags.some((tag) => !tag.trim());
  const pendingDeleteCopy = pendingDelete ? backgroundDeleteDialogCopy(pendingDelete, t) : null;

  return {
    autoLabelData: autoLabelMutation.data ?? null,
    autoLabelDialogOpen,
    autoLabelDisabled,
    autoLabelPending: autoLabelMutation.isPending,
    autoLabelTask,
    bulkImageTagsDraft,
    bulkImageTagsOpen,
    cancelPendingDelete: () => setPendingDelete(null),
    closeAutoLabelDialog: () => setAutoLabelDialogOpen(false),
    closeBulkImageTags: () => {
      ctx.setSectionBusy("background-images:bulk-tags", false);
      setBulkImageTagsOpen(false);
    },
    confirmBulkImageTags,
    confirmPendingDelete,
    deletePending: imageDeleteMutation.isPending,
    handleAutoLabel,
    handleImageDelete,
    handleSaveImageTags,
    imageRowTags,
    openBulkImageTagsDialog,
    pendingDeleteCopy,
    pendingDeleteOpen: Boolean(pendingDelete),
    requestClearImages,
    saveTagsPending: imageTagsSaveMutation.isPending,
    selectedImageIndex,
    setBulkImageTagsDraft,
    setSelectedImageIndex,
    updateImageRowTag,
    uploadImages: (paths: string[]) => imageUploadMutation.mutate(paths),
    uploadPending: imageUploadMutation.isPending,
  };
}
