import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import type { Effect } from "../../../entities/config/types";
import {
  deleteEffectImage,
  saveEffectImageTags,
  uploadEffectImageAudio,
  uploadEffectImages,
} from "../../../entities/effect/repository";
import { numberedTags, tagContents } from "../../../shared/assets/assetText";
import { TAG_PREFIX_IMAGE } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import { useToast, withSectionBusy } from "../../../shared/ui";
import type { EffectPageContext } from "../effectContext";

export function useEffectImagesController(ctx: EffectPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [selectedImageIndexes, setSelectedImageIndexes] = useState<number[]>([]);
  const [imageUploadPickerOpen, setImageUploadPickerOpen] = useState(false);
  const [imageAudioBatchPickerOpen, setImageAudioBatchPickerOpen] = useState(false);
  const [imageAudioTargetIndex, setImageAudioTargetIndex] = useState<number | null>(null);

  useEffect(() => {
    setSelectedImageIndexes([]);
  }, [ctx.selectedEffectKey]);

  const imageUploadMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-images", {
      mutationFn: (paths: string[]) =>
        uploadEffectImages({ imageTags: ctx.draft.image_tags, name: ctx.currentEffectName, paths }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.asset.uploadError"),
          title: t("effect.asset.uploadImage"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({
          ...current,
          image_audio_list: saved.image_audio_list,
          image_list: saved.image_list,
          image_tags: saved.image_tags,
        }));
        showToast({ kind: "success", title: t("effect.asset.uploadImage") });
      },
    }),
  );

  const imageTagsSaveMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-images", {
      mutationFn: () => saveEffectImageTags({ imageTags: ctx.draft.image_tags, name: ctx.currentEffectName }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
          title: t("common.saveFailed"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({ ...current, image_tags: saved.image_tags }));
        showToast({ kind: "success", title: t("effect.action.saveImageTags") });
      },
    }),
  );

  const imageDeleteMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-images", {
      mutationFn: (index: number) => deleteEffectImage(ctx.currentEffectName, index),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.error.deleteFallback"),
          title: t("common.deleteFailed"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({
          ...current,
          image_audio_list: saved.image_audio_list,
          image_list: saved.image_list,
          image_tags: saved.image_tags,
        }));
        setSelectedImageIndexes([]);
      },
    }),
  );

  const imageAudioUploadMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-images", {
      mutationFn: ({ index, path }: { index: number; path: string }) =>
        uploadEffectImageAudio({ index, name: ctx.currentEffectName, path }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.asset.uploadError"),
          title: t("effect.asset.insertAudio"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({ ...current, image_audio_list: saved.image_audio_list }));
        setImageAudioTargetIndex(null);
      },
    }),
  );

  const imageAudioBatchUploadMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-images", {
      mutationFn: async ({ indexes, path }: { indexes: number[]; path: string }) => {
        let effect: Effect | null = null;
        for (const index of indexes) {
          effect = await uploadEffectImageAudio({ index, name: ctx.currentEffectName, path });
        }
        if (!effect) throw new Error(t("effect.asset.noSelectedImage"));
        return effect;
      },
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.asset.uploadError"),
          title: t("effect.asset.batchInsertAudio"),
        });
      },
      onSuccess(effect, variables) {
        ctx.syncSavedEffect(effect, (current, saved) => ({ ...current, image_audio_list: saved.image_audio_list }), {
          invalidate: false,
        });
        setSelectedImageIndexes([]);
        setImageAudioBatchPickerOpen(false);
        showToast({
          kind: "success",
          title: t("effect.asset.batchInsertAudioComplete", { count: variables.indexes.length }),
        });
      },
      onSettled() {
        ctx.invalidateEffects();
      },
    }),
  );

  const updateImageRowTag = useCallback(
    (index: number, value: string) => {
      ctx.patchDraft((current) => {
        const tags = tagContents(current.image_tags, current.image_list.length, true);
        tags[index] = value;
        return { ...current, image_tags: numberedTags(TAG_PREFIX_IMAGE, tags) };
      });
    },
    [ctx.patchDraft],
  );

  const toggleImageSelection = useCallback((index: number, checked: boolean) => {
    setSelectedImageIndexes((current) => {
      if (checked) return current.includes(index) ? current : [...current, index];
      return current.filter((item) => item !== index);
    });
  }, []);

  const toggleAllImageSelection = useCallback(() => {
    setSelectedImageIndexes((current) => {
      const validSelection = current.filter((index) => index >= 0 && index < ctx.draft.image_list.length);
      const allSelected = ctx.draft.image_list.length > 0 && validSelection.length === ctx.draft.image_list.length;
      return allSelected ? [] : ctx.draft.image_list.map((_, index) => index);
    });
  }, [ctx.draft.image_list]);

  const handleUploadImage = useCallback(() => {
    ctx.ensureSavedForAction(() => setImageUploadPickerOpen(true));
  }, [ctx.ensureSavedForAction]);

  const imageRowTags = useMemo(
    () => tagContents(ctx.draft.image_tags, ctx.draft.image_list.length, true),
    [ctx.draft.image_list.length, ctx.draft.image_tags],
  );
  const selectedImageIndexSet = useMemo(() => new Set(selectedImageIndexes), [selectedImageIndexes]);
  const allImagesSelected =
    ctx.draft.image_list.length > 0 && selectedImageIndexes.length === ctx.draft.image_list.length;

  return {
    allImagesSelected,
    batchAudioPending: imageAudioBatchUploadMutation.isPending,
    deleteImage: (index: number) => imageDeleteMutation.mutate(index),
    deleteImagePending: imageDeleteMutation.isPending,
    handleUploadImage,
    imageAudioBatchPickerOpen,
    imageAudioTargetIndex,
    imageRowTags,
    imageUploadPickerOpen,
    saveImageTags: () => imageTagsSaveMutation.mutate(),
    saveImageTagsPending: imageTagsSaveMutation.isPending,
    selectedImageIndexes,
    selectedImageIndexSet,
    setImageAudioBatchPickerOpen,
    setImageAudioTargetIndex,
    setImageUploadPickerOpen,
    toggleAllImageSelection,
    toggleImageSelection,
    updateImageRowTag,
    uploadBatchAudio: (path: string) => {
      const indexes = selectedImageIndexes.filter((index) => index >= 0 && index < ctx.draft.image_list.length);
      if (indexes.length) imageAudioBatchUploadMutation.mutate({ indexes, path });
    },
    uploadImagePending: imageUploadMutation.isPending,
    uploadImages: (paths: string[]) => imageUploadMutation.mutate(paths),
    uploadSingleImageAudio: (path: string) => {
      if (imageAudioTargetIndex !== null) {
        imageAudioUploadMutation.mutate({ index: imageAudioTargetIndex, path });
      }
    },
  };
}
