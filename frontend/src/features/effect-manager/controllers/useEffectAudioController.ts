import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import type { Effect } from "../../../entities/config/types";
import {
  deleteAllEffectAudio,
  deleteEffectAudio,
  saveEffectAudioTags,
  uploadEffectAudio,
} from "../../../entities/effect/repository";
import { numberedTags, tagContents } from "../../../shared/assets/assetText";
import { TAG_PREFIX_EFFECT } from "../../../shared/constants";
import { useI18n } from "../../../shared/i18n";
import { useToast, withSectionBusy } from "../../../shared/ui";
import type { EffectPageContext } from "../effectContext";

type AudioDeleteTarget =
  | { count: number; indexes: number[]; kind: "selected-audio"; name: string }
  | { count: number; kind: "all-audio"; name: string };

export function useEffectAudioController(ctx: EffectPageContext) {
  const { showToast } = useToast();
  const { t } = useI18n();
  const [selectedAudioIndexes, setSelectedAudioIndexes] = useState<number[]>([]);
  const [audioUploadPickerOpen, setAudioUploadPickerOpen] = useState(false);
  const [pendingAudioDelete, setPendingAudioDelete] = useState<AudioDeleteTarget | null>(null);

  useEffect(() => {
    setSelectedAudioIndexes([]);
  }, [ctx.selectedEffectKey]);

  const audioUploadMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-audio", {
      mutationFn: (paths: string[]) =>
        uploadEffectAudio({ audioTags: ctx.draft.audio_tags, name: ctx.currentEffectName, paths }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.asset.uploadError"),
          title: t("effect.asset.uploadAudio"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({
          ...current,
          audio_list: saved.audio_list,
          audio_tags: saved.audio_tags,
        }));
        showToast({ kind: "success", title: t("effect.asset.uploadAudio") });
      },
    }),
  );

  const audioTagsSaveMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-audio", {
      mutationFn: () => saveEffectAudioTags({ audioTags: ctx.draft.audio_tags, name: ctx.currentEffectName }),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
          title: t("common.saveFailed"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({ ...current, audio_tags: saved.audio_tags }));
        showToast({ kind: "success", title: t("effect.action.saveAudioTags") });
      },
    }),
  );

  const audioBatchDeleteMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-audio", {
      mutationFn: async ({ indexes, name }: { indexes: number[]; name: string }) => {
        let effect: Effect | null = null;
        for (const index of [...indexes].sort((a, b) => b - a)) {
          effect = await deleteEffectAudio(name, index);
        }
        if (!effect) {
          throw new Error(t("effect.asset.noSelectedAudio"));
        }
        return effect;
      },
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.error.deleteFallback"),
          title: t("effect.asset.deleteSelectedAudio"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({
          ...current,
          audio_list: saved.audio_list,
          audio_tags: saved.audio_tags,
        }));
        setSelectedAudioIndexes([]);
        showToast({ kind: "success", title: t("effect.asset.deleteSelectedAudio") });
      },
    }),
  );

  const audioDeleteAllMutation = useMutation(
    withSectionBusy(ctx.beginSectionBusy, "effect-audio", {
      mutationFn: (name: string) => deleteAllEffectAudio(name),
      onError(error) {
        showToast({
          kind: "error",
          message: error instanceof Error ? error.message : t("effect.error.deleteFallback"),
          title: t("effect.asset.clearAudio"),
        });
      },
      onSuccess(effect) {
        ctx.syncSavedEffect(effect, (current, saved) => ({
          ...current,
          audio_list: saved.audio_list,
          audio_tags: saved.audio_tags,
        }));
        setSelectedAudioIndexes([]);
        showToast({ kind: "success", title: t("effect.asset.clearAudio") });
      },
    }),
  );

  const updateAudioRowTag = useCallback(
    (index: number, value: string) => {
      ctx.patchDraft((current) => {
        const tags = tagContents(current.audio_tags, current.audio_list.length, true);
        tags[index] = value;
        return { ...current, audio_tags: numberedTags(TAG_PREFIX_EFFECT, tags) };
      });
    },
    [ctx.patchDraft],
  );

  const toggleAudioSelection = useCallback((index: number, checked: boolean) => {
    setSelectedAudioIndexes((current) => {
      if (checked) {
        return current.includes(index) ? current : [...current, index];
      }
      return current.filter((item) => item !== index);
    });
  }, []);

  const toggleAllAudioSelection = useCallback(() => {
    setSelectedAudioIndexes((current) => {
      const validSelection = current.filter((index) => index >= 0 && index < ctx.draft.audio_list.length);
      const allSelected = ctx.draft.audio_list.length > 0 && validSelection.length === ctx.draft.audio_list.length;
      return allSelected ? [] : ctx.draft.audio_list.map((_, index) => index);
    });
  }, [ctx.draft.audio_list]);

  // Auto-save the effect first before opening the file picker for uploading audio.
  const handleUploadAudio = useCallback(() => {
    ctx.ensureSavedForAction(() => setAudioUploadPickerOpen(true), {
      toastTitle: t("effect.asset.uploadAudio"),
    });
  }, [ctx.ensureSavedForAction, t]);

  const saveAudioTags = useCallback(() => {
    if (!ctx.currentEffectName) {
      showToast({
        kind: "error",
        message: t("effect.validation.nameRequired"),
        title: t("effect.action.saveAudioTags"),
      });
      return;
    }
    audioTagsSaveMutation.mutate();
  }, [audioTagsSaveMutation, ctx.currentEffectName, showToast, t]);

  const requestDeleteSelectedAudio = useCallback(() => {
    const validIndexes = selectedAudioIndexes.filter((i) => i >= 0 && i < ctx.draft.audio_list.length);
    if (!validIndexes.length) {
      showToast({ kind: "error", title: t("effect.asset.noSelectedAudio") });
      return;
    }
    setPendingAudioDelete({
      count: validIndexes.length,
      indexes: validIndexes,
      kind: "selected-audio",
      name: ctx.currentEffectName,
    });
  }, [ctx.currentEffectName, ctx.draft.audio_list.length, selectedAudioIndexes, showToast, t]);

  const requestClearAllAudio = useCallback(() => {
    if (!ctx.currentEffectName || !ctx.draft.audio_list.length) {
      showToast({ kind: "error", title: t("effect.asset.clearAudio") });
      return;
    }
    setPendingAudioDelete({ count: ctx.draft.audio_list.length, kind: "all-audio", name: ctx.currentEffectName });
  }, [ctx.currentEffectName, ctx.draft.audio_list.length, showToast, t]);

  const confirmPendingAudioDelete = useCallback(() => {
    if (!pendingAudioDelete) {
      return;
    }
    const target = pendingAudioDelete;
    setPendingAudioDelete(null);
    if (target.kind === "selected-audio") {
      audioBatchDeleteMutation.mutate({ indexes: target.indexes, name: target.name });
    } else {
      audioDeleteAllMutation.mutate(target.name);
    }
  }, [audioBatchDeleteMutation, audioDeleteAllMutation, pendingAudioDelete]);

  const audioRowTags = useMemo(
    () => tagContents(ctx.draft.audio_tags, ctx.draft.audio_list.length, true),
    [ctx.draft.audio_list.length, ctx.draft.audio_tags],
  );
  const selectedAudioIndexSet = useMemo(() => new Set(selectedAudioIndexes), [selectedAudioIndexes]);
  const allAudioSelected =
    ctx.draft.audio_list.length > 0 && selectedAudioIndexes.length === ctx.draft.audio_list.length;
  const canDeleteSelected = Boolean(ctx.currentEffectName && selectedAudioIndexes.length > 0);

  const pendingDeleteCopy = pendingAudioDelete
    ? pendingAudioDelete.kind === "selected-audio"
      ? {
          body: t("effect.asset.deleteSelectedAudioConfirmBody", { count: pendingAudioDelete.count }),
          confirmLabel: t("common.delete"),
          title: t("effect.asset.deleteSelectedAudio"),
        }
      : {
          body: t("effect.asset.clearAudioConfirmBody", { count: pendingAudioDelete.count }),
          confirmLabel: t("common.delete"),
          title: t("effect.asset.clearAudio"),
        }
    : null;

  return {
    allAudioSelected,
    audioRowTags,
    audioUploadPickerOpen,
    batchDeletePending: audioBatchDeleteMutation.isPending,
    cancelPendingAudioDelete: () => setPendingAudioDelete(null),
    canDeleteSelected,
    confirmPendingAudioDelete,
    handleUploadAudio,
    pendingAudioDeleteOpen: Boolean(pendingAudioDelete),
    pendingDeleteCopy,
    requestClearAllAudio,
    requestDeleteSelectedAudio,
    saveAudioTags,
    saveAudioTagsPending: audioTagsSaveMutation.isPending,
    selectedAudioIndexSet,
    setAudioUploadPickerOpen,
    toggleAllAudioSelection,
    toggleAudioSelection,
    updateAudioRowTag,
    uploadAudio: (paths: string[]) => audioUploadMutation.mutate(paths),
    uploadAudioPending: audioUploadMutation.isPending,
  };
}
