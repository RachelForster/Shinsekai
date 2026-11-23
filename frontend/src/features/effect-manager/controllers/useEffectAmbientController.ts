import { useCallback, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  deleteEffectAmbient,
  saveEffectAmbientLayers,
  saveEffectAmbientTags,
  uploadEffectAmbient,
  uploadEffectAmbientAudio,
} from "../../../entities/effect/repository";
import { numberedTags, tagContents } from "../../../shared/assets/assetText";
import { TAG_PREFIX_AMBIENT } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import { useToast, withSectionBusy } from "../../../shared/ui";
import type { EffectPageContext } from "../effectContext";

export function useEffectAmbientController(ctx: EffectPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [ambientUploadPickerOpen, setAmbientUploadPickerOpen] = useState(false);
  const [ambientAudioTargetIndex, setAmbientAudioTargetIndex] = useState<number | null>(null);

  const ambientUploadMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-ambient", {
      mutationFn: (paths: string[]) =>
        uploadEffectAmbient({ ambientTags: ctx.draft.ambient_tags, name: ctx.currentEffectName, paths }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.asset.uploadError"),
          title: t("effect.asset.uploadAmbient"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({
          ...current,
          ambient_audio_list: saved.ambient_audio_list,
          ambient_layers: saved.ambient_layers,
          ambient_list: saved.ambient_list,
          ambient_tags: saved.ambient_tags,
        }));
        showToast({ kind: "success", title: t("effect.asset.uploadAmbient") });
      },
    }),
  );

  const ambientTagsSaveMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-ambient", {
      mutationFn: () => saveEffectAmbientTags({ ambientTags: ctx.draft.ambient_tags, name: ctx.currentEffectName }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
          title: t("common.saveFailed"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({ ...current, ambient_tags: saved.ambient_tags }));
        showToast({ kind: "success", title: t("effect.action.saveAmbientTags") });
      },
    }),
  );

  const ambientLayersSaveMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-ambient", {
      mutationFn: (layers: string[]) => saveEffectAmbientLayers({ layers, name: ctx.currentEffectName }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
          title: t("common.saveFailed"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({ ...current, ambient_layers: saved.ambient_layers }));
      },
    }),
  );

  const ambientAudioUploadMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-ambient", {
      mutationFn: ({ index, path }: { index: number; path: string }) =>
        uploadEffectAmbientAudio({ index, name: ctx.currentEffectName, path }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.asset.uploadError"),
          title: t("effect.asset.insertAudio"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({ ...current, ambient_audio_list: saved.ambient_audio_list }));
        setAmbientAudioTargetIndex(null);
      },
    }),
  );

  const ambientDeleteMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-ambient", {
      mutationFn: (index: number) => deleteEffectAmbient(ctx.currentEffectName, index),
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
          ambient_audio_list: saved.ambient_audio_list,
          ambient_layers: saved.ambient_layers,
          ambient_list: saved.ambient_list,
          ambient_tags: saved.ambient_tags,
        }));
      },
    }),
  );

  const updateAmbientRowTag = useCallback(
    (index: number, value: string) => {
      ctx.patchDraft((current) => {
        const tags = tagContents(current.ambient_tags, current.ambient_list.length, true);
        tags[index] = value;
        return { ...current, ambient_tags: numberedTags(TAG_PREFIX_AMBIENT, tags) };
      });
    },
    [ctx.patchDraft],
  );

  const updateAmbientLayer = useCallback(
    (index: number, layer: string) => {
      const layers = [...ctx.draft.ambient_layers];
      while (layers.length < ctx.draft.ambient_list.length) layers.push("back");
      layers[index] = layer === "front" ? "front" : "back";
      ctx.patchDraft((current) => ({ ...current, ambient_layers: layers }));
      ambientLayersSaveMutation.mutate(layers);
    },
    [ambientLayersSaveMutation, ctx.draft.ambient_layers, ctx.draft.ambient_list.length, ctx.patchDraft],
  );

  const handleUploadAmbient = useCallback(() => {
    ctx.ensureSavedForAction(() => setAmbientUploadPickerOpen(true), {
      requireNonEmptyNameWhenSaved: true,
    });
  }, [ctx.ensureSavedForAction]);

  const saveAmbientTags = useCallback(() => {
    if (!ctx.currentEffectName) {
      showToast({
        kind: "error",
        message: t("effect.validation.nameRequired"),
        title: t("effect.action.saveAmbientTags"),
      });
      return;
    }
    ambientTagsSaveMutation.mutate();
  }, [ambientTagsSaveMutation, ctx.currentEffectName, showToast, t]);

  const ambientRowTags = useMemo(
    () => tagContents(ctx.draft.ambient_tags, ctx.draft.ambient_list.length, true),
    [ctx.draft.ambient_list.length, ctx.draft.ambient_tags],
  );

  return {
    ambientAudioTargetIndex,
    ambientRowTags,
    ambientUploadPickerOpen,
    deleteAmbient: (index: number) => ambientDeleteMutation.mutate(index),
    deletingAmbient: ambientDeleteMutation.isPending,
    handleUploadAmbient,
    saveAmbientTags,
    saveRowAmbientTags: () => ambientTagsSaveMutation.mutate(),
    savingTags: ambientTagsSaveMutation.isPending,
    setAmbientAudioTargetIndex,
    setAmbientUploadPickerOpen,
    updateAmbientLayer,
    updateAmbientRowTag,
    uploadAmbient: (paths: string[]) => ambientUploadMutation.mutate(paths),
    uploadAmbientAudio: (path: string) => {
      if (ambientAudioTargetIndex !== null) {
        ambientAudioUploadMutation.mutate({ index: ambientAudioTargetIndex, path });
      }
    },
    uploadingAmbient: ambientUploadMutation.isPending,
  };
}
