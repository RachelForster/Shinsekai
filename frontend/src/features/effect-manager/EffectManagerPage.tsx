import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FolderInput, FolderOutput, Music, Palette, Plus, Save, Trash2, Upload, X } from "lucide-react";

import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";

import {
  effectsQueryKey,
  deleteAllEffectAudio,
  deleteEffect,
  deleteEffectAudio,
  deleteEffectImage,
  exportEffect,
  importEffects,
  listEffects,
  saveEffect,
  saveEffectAudioTags,
  saveEffectImageTags,
  uploadEffectAudio,
  uploadEffectImages,
  uploadEffectImageAudio,
} from "../../entities/effect/repository";
import type { Effect } from "../../entities/config/types";
import type { MessageKey } from "../../shared/i18n";
import { useI18n } from "../../shared/i18n";
import { baseName, numberedTags, tagContents } from "../../shared/assets/assetText";
import { isValidEffectStorageName } from "../../shared/assets/spritePrefix";
import { openExternal } from "../../entities/files/repository";
import { useDebouncedAutoSave } from "../../shared/hooks/useDebouncedAutoSave";
import {
  AlertDialog,
  AsyncButton,
  AutoSaveStatus,
  Button,
  EmptyState,
  handleIdentityKeyDown,
  InlineIdentityConfirm,
  PageSectionNav,
  PathPickerDialog,
  Select,
  TextInput,
  useToast,
} from "../../shared/ui";
import { AudioPlayer } from "../../shared/ui/AudioPlayer";
import { fileUrl } from "../../entities/files/repository";
import "./EffectManagerPage.css";

const EFFECT_RESOURCES_URL = "https://shinsekai.end0rph1n.icu/resources";

function createEffect(): Effect {
  return {
    name: "",
    color: "#5b8def",
    prompt_text: "",
    audio_list: [],
    audio_tags: "",
    image_list: [],
    image_tags: "",
    image_audio_list: [],
  };
}

function upsertCatalogEffect(current: Effect[], effect: Effect, originalName?: string): Effect[] {
  const targetNames = new Set([originalName, effect.name].filter(Boolean).map((item) => String(item).toLowerCase()));
  const next: Effect[] = [];
  let replaced = false;
  for (const item of current) {
    const matchedById = Boolean(effect.id && item.id && item.id === effect.id);
    if (matchedById || targetNames.has(item.name.toLowerCase())) {
      if (!replaced) {
        next.push(effect);
        replaced = true;
      }
      continue;
    }
    next.push(item);
  }
  if (!replaced) {
    next.push(effect);
  }
  return next;
}

function serializeEffectNonIdentity(
  effect: Pick<Effect, "audio_tags" | "color" | "image_tags" | "prompt_text">,
): string {
  return JSON.stringify({
    audio_tags: effect.audio_tags ?? "",
    color: (effect.color ?? "").trim() || "#5b8def",
    image_tags: effect.image_tags ?? "",
    prompt_text: effect.prompt_text ?? "",
  });
}

type EffectDeleteTarget =
  | { kind: "effect"; name: string }
  | { count: number; indexes: number[]; kind: "selected-audio"; name: string }
  | { count: number; kind: "all-audio"; name: string };

interface EffectDeleteDialogCopy {
  body: string;
  confirmLabel: string;
  title: string;
}

function effectDeleteDialogCopy(
  target: EffectDeleteTarget,
  t: (key: MessageKey, values?: Record<string, number | string>) => string,
): EffectDeleteDialogCopy {
  switch (target.kind) {
    case "effect":
      return {
        body: t("effect.delete.confirmBody", { name: target.name }),
        confirmLabel: t("common.delete"),
        title: t("effect.delete.confirmTitle"),
      };
    case "selected-audio":
      return {
        body: t("effect.asset.deleteSelectedAudioConfirmBody", { count: target.count }),
        confirmLabel: t("common.delete"),
        title: t("effect.asset.deleteSelectedAudio"),
      };
    case "all-audio":
      return {
        body: t("effect.asset.clearAudioConfirmBody", { count: target.count }),
        confirmLabel: t("common.delete"),
        title: t("effect.asset.clearAudio"),
      };
  }
}

export function EffectManagerPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { t } = useI18n();
  const effectsQuery = useQuery({ queryFn: listEffects, queryKey: effectsQueryKey });
  const data = Array.isArray(effectsQuery.data) ? effectsQuery.data : [];
  const isLoading = effectsQuery.isLoading;
  const [selectedName, setSelectedName] = useState("");
  const [draft, setDraft] = useState<Effect>(createEffect());
  const [isCreating, setIsCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<EffectDeleteTarget | null>(null);
  const [selectedAudioIndexes, setSelectedAudioIndexes] = useState<number[]>([]);
  const [selectedImageIndexes, setSelectedImageIndexes] = useState<number[]>([]);
  const [importPickerOpen, setImportPickerOpen] = useState(false);
  const [audioUploadPickerOpen, setAudioUploadPickerOpen] = useState(false);
  const [imageUploadPickerOpen, setImageUploadPickerOpen] = useState(false);
  const [imageAudioBatchPickerOpen, setImageAudioBatchPickerOpen] = useState(false);
  const [imageAudioTargetIndex, setImageAudioTargetIndex] = useState<number | null>(null);
  const [nameError, setNameError] = useState("");
  const [syncedEffectKey, setSyncedEffectKey] = useState("");
  const isCreatingRef = useRef(isCreating);
  isCreatingRef.current = isCreating;
  const deletedEffectKeysRef = useRef<Set<string>>(new Set());
  const cancelAutoSaveRef = useRef<(targetKey?: string) => Promise<void>>(() => Promise.resolve());
  const previousSelectedNameRef = useRef("");
  const activeEffectKeyRef = useRef("");
  const colorInputRef = useRef<HTMLInputElement | null>(null);
  const colorPickerValue = /^#[0-9a-fA-F]{6}$/.test(draft.color || "") ? draft.color : DEFAULT_CHARACTER_COLOR;
  const openColorPicker = useCallback(() => {
    colorInputRef.current?.click();
  }, []);

  const inCreateMode = isCreating || data.length === 0;

  const selected = useMemo(() => {
    if (isCreating) {
      return undefined;
    }
    if (selectedName) {
      return data.find((ef) => ef.name === selectedName);
    }
    return data[0];
  }, [data, isCreating, selectedName]);
  const currentEffectName = isCreating ? "" : selected?.name || selectedName;

  useEffect(() => {
    if (!selected) {
      activeEffectKeyRef.current = "";
      setSyncedEffectKey("");
      return;
    }
    const selectedKey = selected.id || `name:${selected.name}`;
    if (selectedKey !== activeEffectKeyRef.current) {
      activeEffectKeyRef.current = selectedKey;
      setSyncedEffectKey(selectedKey);
      setSelectedName(selected.name);
      setDraft(structuredClone(selected));
      setSelectedAudioIndexes([]);
      setSelectedImageIndexes([]);
      setNameError("");
    } else if (selected.id) {
      setDraft((current) => (current.id ? current : { ...current, id: selected.id }));
    }
  }, [selected]);

  const saveMutation = useMutation({
    mutationFn: ({ effect, originalName }: { effect: Effect; originalName?: string }) =>
      saveEffect(effect, originalName),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(effect, variables) {
      const nextKey = effect.id || `name:${effect.name}`;
      deletedEffectKeysRef.current.delete(nextKey);
      deletedEffectKeysRef.current.delete(`name:${effect.name}`);
      isCreatingRef.current = false;
      activeEffectKeyRef.current = nextKey;
      setSyncedEffectKey(nextKey);
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) =>
        upsertCatalogEffect(current, effect, variables.originalName),
      );
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setIsCreating(false);
      setNameError("");
      setSelectedName(effect.name);
      setDraft(structuredClone(effect));
      showToast({ kind: "success", title: t("effect.toast.saved") });
    },
  });

  const identityMutation = useMutation({
    mutationFn: ({ effect, originalName }: { effect: Effect; originalName: string; sourceKey: string }) =>
      saveEffect(effect, originalName),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(effect, variables) {
      if (
        deletedEffectKeysRef.current.has(variables.sourceKey) ||
        deletedEffectKeysRef.current.has(`name:${variables.originalName}`)
      ) {
        return;
      }
      const nextKey = effect.id || `name:${effect.name}`;
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) =>
        upsertCatalogEffect(current, effect, variables.originalName),
      );
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      if (!isCreatingRef.current && activeEffectKeyRef.current === variables.sourceKey) {
        activeEffectKeyRef.current = nextKey;
        setSyncedEffectKey(nextKey);
        setNameError("");
        setSelectedName(effect.name);
        setDraft((current) => ({
          ...current,
          ...(effect.id ? { id: effect.id } : {}),
          audio_list: effect.audio_list,
          image_audio_list: effect.image_audio_list,
          image_list: effect.image_list,
          name: effect.name,
        }));
      }
      showToast({ kind: "success", title: t("effect.toast.saved") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (targetName: string) => {
      const target = data.find((item) => item.name === targetName);
      const targetKey = target ? target.id || `name:${target.name}` : `name:${targetName}`;
      deletedEffectKeysRef.current.add(targetKey);
      deletedEffectKeysRef.current.add(`name:${targetName}`);
      await cancelAutoSaveRef.current(targetKey);
      return deleteEffect(targetName);
    },
    onSuccess(_result, deletedName) {
      setSelectedName((current) => (current === deletedName ? "" : current));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      showToast({ kind: "success", title: t("effect.toast.deleted") });
    },
    onError(error, deletedName) {
      const target = data.find((item) => item.name === deletedName);
      if (target?.id) {
        deletedEffectKeysRef.current.delete(target.id);
      }
      deletedEffectKeysRef.current.delete(`name:${deletedName}`);
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.deleteFallback"),
        title: t("common.deleteFailed"),
      });
    },
  });

  const importMutation = useMutation({
    mutationFn: importEffects,
    onSuccess(imported) {
      for (const item of imported) {
        if (item.id) {
          deletedEffectKeysRef.current.delete(item.id);
        }
        deletedEffectKeysRef.current.delete(`name:${item.name}`);
      }
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => [...current, ...imported]);
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      const lastImported = imported[imported.length - 1];
      if (lastImported) {
        isCreatingRef.current = false;
        activeEffectKeyRef.current = lastImported.id || `name:${lastImported.name}`;
        setIsCreating(false);
        setSelectedName(lastImported.name);
        setDraft(structuredClone(lastImported));
      }
      showToast({ kind: "success", title: t("effect.toast.importComplete", { count: imported.length }) });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.importFallback"),
        title: t("common.importFailed"),
      });
    },
  });

  const exportMutation = useMutation({
    mutationFn: exportEffect,
    onSuccess(path) {
      showToast({ kind: "success", message: path, title: t("effect.toast.exportComplete") });
    },
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.exportFallback"),
        title: t("common.exportFailed"),
      });
    },
  });

  const audioUploadMutation = useMutation({
    mutationFn: (paths: string[]) => uploadEffectAudio({ audioTags: draft.audio_tags, name: currentEffectName, paths }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.asset.uploadError"),
        title: t("effect.asset.uploadAudio"),
      });
    },
    onSuccess(effect) {
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setDraft((current) => ({ ...current, audio_list: effect.audio_list, audio_tags: effect.audio_tags }));
      showToast({ kind: "success", title: t("effect.asset.uploadAudio") });
    },
  });

  const audioTagsSaveMutation = useMutation({
    mutationFn: () => saveEffectAudioTags({ audioTags: draft.audio_tags, name: currentEffectName }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(effect) {
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setDraft((current) => ({ ...current, audio_tags: effect.audio_tags }));
      showToast({ kind: "success", title: t("effect.action.saveAudioTags") });
    },
  });

  const imageUploadMutation = useMutation({
    mutationFn: (paths: string[]) =>
      uploadEffectImages({ imageTags: draft.image_tags, name: currentEffectName, paths }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.asset.uploadError"),
        title: t("effect.asset.uploadImage"),
      });
    },
    onSuccess(effect) {
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setDraft((current) => ({
        ...current,
        image_list: effect.image_list,
        image_tags: effect.image_tags,
        image_audio_list: effect.image_audio_list,
      }));
      showToast({ kind: "success", title: t("effect.asset.uploadImage") });
    },
  });

  const imageTagsSaveMutation = useMutation({
    mutationFn: () => saveEffectImageTags({ imageTags: draft.image_tags, name: currentEffectName }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    onSuccess(effect) {
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setDraft((current) => ({ ...current, image_tags: effect.image_tags }));
      showToast({ kind: "success", title: t("effect.action.saveImageTags") });
    },
  });

  const imageDeleteMutation = useMutation({
    mutationFn: (index: number) => deleteEffectImage(currentEffectName, index),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.deleteFallback"),
        title: t("common.deleteFailed"),
      });
    },
    onSuccess(effect) {
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setDraft((current) => ({
        ...current,
        image_list: effect.image_list,
        image_tags: effect.image_tags,
        image_audio_list: effect.image_audio_list,
      }));
      setSelectedImageIndexes([]);
    },
  });

  const imageAudioUploadMutation = useMutation({
    mutationFn: ({ index, path }: { index: number; path: string }) =>
      uploadEffectImageAudio({ index, name: currentEffectName, path }),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.asset.uploadError"),
        title: t("effect.asset.insertAudio"),
      });
    },
    onSuccess(effect) {
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setDraft((current) => ({ ...current, image_audio_list: effect.image_audio_list }));
      setImageAudioTargetIndex(null);
    },
  });

  const imageAudioBatchUploadMutation = useMutation({
    mutationFn: async ({ indexes, path }: { indexes: number[]; path: string }) => {
      let effect: Effect | null = null;
      for (const index of indexes) {
        effect = await uploadEffectImageAudio({ index, name: currentEffectName, path });
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
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      setDraft((current) => ({ ...current, image_audio_list: effect.image_audio_list }));
      setSelectedImageIndexes([]);
      setImageAudioBatchPickerOpen(false);
      showToast({
        kind: "success",
        title: t("effect.asset.batchInsertAudioComplete", { count: variables.indexes.length }),
      });
    },
    onSettled() {
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
    },
  });

  const audioBatchDeleteMutation = useMutation({
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
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setDraft((current) => ({ ...current, audio_list: effect.audio_list, audio_tags: effect.audio_tags }));
      setSelectedAudioIndexes([]);
      showToast({ kind: "success", title: t("effect.asset.deleteSelectedAudio") });
    },
  });

  const audioDeleteAllMutation = useMutation({
    mutationFn: (name: string) => deleteAllEffectAudio(name),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.deleteFallback"),
        title: t("effect.asset.clearAudio"),
      });
    },
    onSuccess(effect) {
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) => upsertCatalogEffect(current, effect));
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setDraft((current) => ({ ...current, audio_list: effect.audio_list, audio_tags: effect.audio_tags }));
      setSelectedAudioIndexes([]);
      showToast({ kind: "success", title: t("effect.asset.clearAudio") });
    },
  });

  const update = useCallback(<K extends keyof Effect>(name: K, value: Effect[K]) => {
    setDraft((current) => ({ ...current, [name]: value }));
    if (name === "name" && String(value).trim()) {
      setNameError("");
    }
  }, []);

  const updateAudioRowTag = useCallback((index: number, value: string) => {
    setDraft((current) => {
      const tags = tagContents(current.audio_tags, current.audio_list.length, true);
      tags[index] = value;
      return { ...current, audio_tags: numberedTags("特效", tags) };
    });
  }, []);

  const updateImageRowTag = useCallback((index: number, value: string) => {
    setDraft((current) => {
      const tags = tagContents(current.image_tags, current.image_list.length, true);
      tags[index] = value;
      return { ...current, image_tags: numberedTags("图片", tags) };
    });
  }, []);

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
      const validSelection = current.filter((index) => index >= 0 && index < draft.audio_list.length);
      const allSelected = draft.audio_list.length > 0 && validSelection.length === draft.audio_list.length;
      return allSelected ? [] : draft.audio_list.map((_, index) => index);
    });
  }, [draft.audio_list]);

  const toggleImageSelection = useCallback((index: number, checked: boolean) => {
    setSelectedImageIndexes((current) => {
      if (checked) return current.includes(index) ? current : [...current, index];
      return current.filter((item) => item !== index);
    });
  }, []);

  const toggleAllImageSelection = useCallback(() => {
    setSelectedImageIndexes((current) => {
      const validSelection = current.filter((index) => index >= 0 && index < draft.image_list.length);
      const allSelected = draft.image_list.length > 0 && validSelection.length === draft.image_list.length;
      return allSelected ? [] : draft.image_list.map((_, index) => index);
    });
  }, [draft.image_list]);

  const confirmPendingDelete = () => {
    if (!pendingDelete) {
      return;
    }
    const target = pendingDelete;
    setPendingDelete(null);
    switch (target.kind) {
      case "effect":
        deleteMutation.mutate(target.name);
        break;
      case "selected-audio":
        audioBatchDeleteMutation.mutate({ indexes: target.indexes, name: target.name });
        break;
      case "all-audio":
        audioDeleteAllMutation.mutate(target.name);
        break;
    }
  };

  const pendingDeleteCopy = pendingDelete ? effectDeleteDialogCopy(pendingDelete, t) : null;

  const selectedEffectKey = selected ? selected.id || `name:${selected.name}` : "";
  const isDraftSynced = Boolean(selected && syncedEffectKey === selectedEffectKey);
  const nameDirty = Boolean(!inCreateMode && isDraftSynced && draft.name !== selected!.name);
  const liveNameError = useMemo(() => {
    if (!nameDirty || !selected) {
      return nameError;
    }
    const trimmed = draft.name.trim();
    if (!trimmed) {
      return t("effect.validation.nameRequired");
    }
    if (!isValidEffectStorageName(trimmed)) {
      return t("identity.error.invalidEffectName");
    }
    const duplicate = data.some(
      (item) =>
        item !== selected &&
        (selected.id ? item.id !== selected.id : item.name !== selected.name) &&
        item.name.trim().toLowerCase() === trimmed.toLowerCase(),
    );
    return duplicate ? t("identity.error.duplicateName", { name: trimmed }) : "";
  }, [data, draft.name, nameDirty, nameError, selected, t]);

  const baselineAutoSaveKey = useMemo(() => (selected ? serializeEffectNonIdentity(selected) : ""), [selected]);
  const currentAutoSaveKey = useMemo(() => (selected ? serializeEffectNonIdentity(draft) : ""), [draft, selected]);

  const resolveLatestSelectedEffect = useCallback((): Effect | undefined => {
    if (!selected) {
      return undefined;
    }
    const catalog = queryClient.getQueryData<Effect[]>(effectsQueryKey) ?? data;
    return (
      (selected.id ? catalog.find((item) => item.id === selected.id) : undefined) ??
      catalog.find((item) => item.name === selected.name) ??
      selected
    );
  }, [data, queryClient, selected]);

  const autoSave = useDebouncedAutoSave<{ effect: Effect; originalName: string }>({
    baselineKey: baselineAutoSaveKey,
    buildPayload: () => {
      const latestSelected = resolveLatestSelectedEffect() ?? selected!;
      return {
        effect: {
          ...latestSelected,
          ...(latestSelected.id ? { id: latestSelected.id } : {}),
          audio_tags: draft.audio_tags,
          color: draft.color.trim() || "#5b8def",
          image_tags: draft.image_tags,
          name: latestSelected.name,
          prompt_text: draft.prompt_text,
        },
        originalName: latestSelected.name,
      };
    },
    currentKey: currentAutoSaveKey,
    enabled: Boolean(
      !inCreateMode &&
      isDraftSynced &&
      !identityMutation.isPending &&
      !saveMutation.isPending &&
      !deleteMutation.isPending &&
      !audioUploadMutation.isPending &&
      !imageUploadMutation.isPending &&
      !imageDeleteMutation.isPending &&
      !imageAudioUploadMutation.isPending &&
      !imageAudioBatchUploadMutation.isPending &&
      !audioBatchDeleteMutation.isPending &&
      !audioDeleteAllMutation.isPending &&
      pendingDelete?.kind !== "effect",
    ),
    onError(error) {
      showToast({
        kind: "error",
        message: error instanceof Error ? error.message : t("effect.error.saveFallback"),
        title: t("common.saveFailed"),
      });
    },
    async onSave({ effect, originalName }, { resetKey }) {
      const saved = await saveEffect(effect, originalName);
      if (deletedEffectKeysRef.current.has(resetKey) || deletedEffectKeysRef.current.has(`name:${originalName}`)) {
        return;
      }
      queryClient.setQueryData<Effect[]>(effectsQueryKey, (current = []) =>
        upsertCatalogEffect(current, saved, originalName),
      );
      if (saved.id && !isCreatingRef.current && activeEffectKeyRef.current === resetKey) {
        activeEffectKeyRef.current = saved.id;
        setSyncedEffectKey(saved.id);
        setDraft((current) => (current.id ? current : { ...current, id: saved.id }));
      }
    },
    resetKey: selected ? selected.id || `name:${selected.name}` : "__creating__",
  });
  cancelAutoSaveRef.current = autoSave.cancel;

  const confirmIdentityName = () => {
    if (!selected || identityMutation.isPending) {
      return;
    }
    if (liveNameError) {
      showToast({
        kind: "error",
        message: liveNameError,
        title: t("common.validationFailed"),
      });
      return;
    }
    autoSave.discardPending();
    const latestSelected = resolveLatestSelectedEffect() ?? selected;
    identityMutation.mutate({
      effect: {
        ...latestSelected,
        ...(latestSelected.id ? { id: latestSelected.id } : {}),
        audio_tags: draft.audio_tags,
        color: draft.color.trim() || "#5b8def",
        image_tags: draft.image_tags,
        name: draft.name.trim(),
        prompt_text: draft.prompt_text,
      },
      originalName: latestSelected.name,
      sourceKey: selectedEffectKey,
    });
  };

  const cancelIdentityName = () => {
    if (!selected) {
      return;
    }
    setDraft((current) => ({ ...current, name: selected.name }));
    setNameError("");
  };

  const validateCreateName = useCallback(
    (rawName: string): string | null => {
      const trimmed = rawName.trim();
      if (!trimmed) {
        return t("effect.validation.nameRequired");
      }
      if (!isValidEffectStorageName(trimmed)) {
        return t("identity.error.invalidEffectName");
      }
      if (data.some((item) => item.name.trim().toLowerCase() === trimmed.toLowerCase())) {
        return t("identity.error.duplicateName", { name: trimmed });
      }
      return null;
    },
    [data, t],
  );

  const saveDraft = useCallback(() => {
    const error = validateCreateName(draft.name);
    if (error) {
      setNameError(error);
      showToast({
        kind: "error",
        message: error === t("effect.validation.nameRequired") ? t("common.fixInvalidFields") : error,
        title: t("common.validationFailed"),
      });
      return;
    }
    const { id: _omittedId, ...restDraft } = draft;
    saveMutation.mutate({
      effect: { ...restDraft, color: draft.color.trim() || "#5b8def", name: draft.name.trim() },
      originalName: undefined,
    });
  }, [draft, saveMutation, showToast, t, validateCreateName]);

  const startCreatingEffect = useCallback(() => {
    autoSave.flush();
    previousSelectedNameRef.current = currentEffectName || data[0]?.name || "";
    activeEffectKeyRef.current = "";
    isCreatingRef.current = true;
    setIsCreating(true);
    setSelectedName("");
    setDraft(createEffect());
    setSelectedAudioIndexes([]);
    setSelectedImageIndexes([]);
    setNameError("");
  }, [autoSave, currentEffectName, data]);

  const cancelCreatingEffect = useCallback(() => {
    if (!data.length) {
      return;
    }
    const targetName =
      (previousSelectedNameRef.current && data.some((item) => item.name === previousSelectedNameRef.current)
        ? previousSelectedNameRef.current
        : data[0]?.name) || "";
    activeEffectKeyRef.current = "";
    isCreatingRef.current = false;
    setIsCreating(false);
    setNameError("");
    setSelectedName(targetName);
  }, [data]);

  /* 上传音频：如果方案尚未保存，先自动保存再打开文件选择器 */
  const handleUploadAudio = useCallback(() => {
    if (!currentEffectName) {
      const error = validateCreateName(draft.name);
      if (error) {
        setNameError(error);
        showToast({
          kind: "error",
          message: error === t("effect.validation.nameRequired") ? t("common.fixInvalidFields") : error,
          title: t("effect.asset.uploadAudio"),
        });
        return;
      }
      const { id: _omittedId, ...restDraft } = draft;
      saveMutation.mutate(
        {
          effect: { ...restDraft, color: draft.color.trim() || "#5b8def", name: draft.name.trim() },
          originalName: undefined,
        },
        {
          onSuccess: () => {
            setAudioUploadPickerOpen(true);
          },
        },
      );
      return;
    }
    setAudioUploadPickerOpen(true);
  }, [currentEffectName, draft, saveMutation, showToast, t, validateCreateName]);

  const handleUploadImage = useCallback(() => {
    if (!currentEffectName) {
      const error = validateCreateName(draft.name);
      if (error) {
        setNameError(error);
        return;
      }
      const { id: _omittedId, ...restDraft } = draft;
      saveMutation.mutate(
        {
          effect: { ...restDraft, color: draft.color.trim() || "#5b8def", name: draft.name.trim() },
          originalName: undefined,
        },
        { onSuccess: () => setImageUploadPickerOpen(true) },
      );
      return;
    }
    setImageUploadPickerOpen(true);
  }, [currentEffectName, draft, saveMutation, validateCreateName]);

  const audioRowTags = useMemo(
    () => tagContents(draft.audio_tags, draft.audio_list.length, true),
    [draft.audio_list.length, draft.audio_tags],
  );
  const imageRowTags = useMemo(
    () => tagContents(draft.image_tags, draft.image_list.length, true),
    [draft.image_list.length, draft.image_tags],
  );

  const selectedAudioIndexSet = useMemo(() => new Set(selectedAudioIndexes), [selectedAudioIndexes]);
  const selectedImageIndexSet = useMemo(() => new Set(selectedImageIndexes), [selectedImageIndexes]);

  const allAudioSelected = draft.audio_list.length > 0 && selectedAudioIndexes.length === draft.audio_list.length;
  const allImagesSelected = draft.image_list.length > 0 && selectedImageIndexes.length === draft.image_list.length;

  const canDeleteSelected = currentEffectName && selectedAudioIndexes.length > 0;
  const effectSectionNavItems = [
    { id: "effect-info", label: t("effect.section.info") },
    { id: "effect-images", label: t("effect.section.image") },
    { id: "effect-audio", label: t("effect.section.audio") },
  ];

  return (
    <div className="page effect-page">
      <header className="page__header effect-page__header">
        <div className="effect-page__heading">
          <h1 className="page__title">{t("effect.title")}</h1>
        </div>
        <div className="page__actions effect-page__primary-actions">
          <div className="effect-page__resource-actions">
            <Button
              icon={<ExternalLink aria-hidden className="button__icon" />}
              onClick={() => openExternal(EFFECT_RESOURCES_URL)}
              variant="ghost"
            >
              {t("effect.action.community")}
            </Button>
            <Button
              icon={<ExternalLink aria-hidden className="button__icon" />}
              onClick={() => openExternal(EFFECT_RESOURCES_URL)}
              variant="ghost"
            >
              {t("effect.action.uploadContribution")}
            </Button>
          </div>
          <label className="effect-page__group-select">
            <span className="visually-hidden">{t("effect.groupListTitle")}</span>
            <Select
              disabled={isLoading || (!isCreating && !data.length)}
              onChange={(event) => {
                autoSave.flush();
                isCreatingRef.current = false;
                setIsCreating(false);
                setNameError("");
                setSelectedName(event.target.value);
              }}
              value={isCreating ? "" : selectedName || data[0]?.name || ""}
            >
              {isCreating ? <option value="">{t("common.new")}</option> : null}
              {!isCreating && !data.length ? <option value="">{t("effect.emptyTitle")}</option> : null}
              {data.map((effect) => (
                <option key={effect.name} value={effect.name}>
                  {effect.name}
                </option>
              ))}
            </Select>
          </label>
          <div className="effect-page__package-actions">
            <Button
              className="button--header-icon"
              data-tooltip={t("common.new")}
              icon={<Plus aria-hidden className="button__icon" />}
              onClick={startCreatingEffect}
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
                if (!currentEffectName) {
                  showToast({
                    kind: "error",
                    message: t("effect.validation.nameRequired"),
                    title: t("common.export"),
                  });
                  return;
                }
                exportMutation.mutate(currentEffectName);
              }}
            >
              {t("common.export")}
            </AsyncButton>
            {inCreateMode ? (
              <>
                {isCreating && data.length > 0 ? (
                  <Button
                    icon={<X aria-hidden className="button__icon" />}
                    onClick={cancelCreatingEffect}
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
                pendingIdentity={nameDirty}
                phase={autoSave.phase}
              />
            )}
          </div>
        </div>
        <PageSectionNav ariaLabel={t("effect.title")} items={effectSectionNavItems} />
        <PathPickerDialog
          acceptedExtensions={[".ef"]}
          multiple
          onClose={() => setImportPickerOpen(false)}
          onSelect={(path) => importMutation.mutate([path])}
          onSelectMany={(paths) => importMutation.mutate(paths)}
          open={importPickerOpen}
          title={t("common.import")}
        />
      </header>

      <section className="settings-grid effect-page__content">
        {/* Info section */}
        <section className="section page-section-anchor" id="effect-info">
          <div className="section__header">
            <h2 className="section__title">{t("effect.section.info")}</h2>
            <div className="section__actions">
              <Button
                icon={<Trash2 aria-hidden className="button__icon" />}
                onClick={() => {
                  if (!currentEffectName) {
                    showToast({
                      kind: "error",
                      message: t("effect.error.deleteFallback"),
                      title: t("common.deleteFailed"),
                    });
                    return;
                  }
                  setPendingDelete({ kind: "effect", name: currentEffectName });
                }}
                variant="danger"
              >
                {t("common.delete")}
              </Button>
            </div>
          </div>
          <div className="form-grid form-grid--two">
            <div className="field-row">
              <label className="field-row__label" htmlFor="effect-info-name-input">
                {t("effect.field.name")}
              </label>
              <span className="field-row__control">
                <div className="identity-field-group">
                  <TextInput
                    className={liveNameError ? "input--error" : ""}
                    id="effect-info-name-input"
                    onChange={(event) => update("name", event.target.value)}
                    onKeyDown={(event) =>
                      handleIdentityKeyDown(event, {
                        canConfirm: !liveNameError && !identityMutation.isPending,
                        disabled: identityMutation.isPending,
                        isDirty: nameDirty,
                        onCancel: cancelIdentityName,
                        onConfirm: confirmIdentityName,
                      })
                    }
                    value={draft.name}
                  />
                  <InlineIdentityConfirm
                    confirmDisabled={Boolean(liveNameError)}
                    fieldLabel={t("effect.field.name")}
                    loading={identityMutation.isPending}
                    onCancel={cancelIdentityName}
                    onConfirm={confirmIdentityName}
                    visible={nameDirty}
                  />
                </div>
                {liveNameError ? <span className="field-error">{liveNameError}</span> : null}
              </span>
            </div>
            <label className="field-row">
              <span className="field-row__label">{t("effect.field.color")}</span>
              <span className="field-row__control">
                <div className="input-group effect-color-control">
                  <TextInput onChange={(event) => update("color", event.target.value)} value={draft.color} />
                  <span aria-hidden className="swatch" style={{ background: colorPickerValue }} />
                  <Button
                    icon={<Palette aria-hidden className="button__icon" />}
                    onClick={openColorPicker}
                    variant="ghost"
                  >
                    {t("effect.action.pickColor")}
                  </Button>
                  <input
                    className="visually-hidden"
                    onChange={(event) => update("color", event.target.value)}
                    ref={colorInputRef}
                    type="color"
                    value={colorPickerValue}
                  />
                </div>
              </span>
            </label>
          </div>
        </section>

        <section className="section page-section-anchor" id="effect-images">
          <div className="section__header">
            <h2 className="section__title">{t("effect.section.image")}</h2>
            <div className="section__actions">
              <label className="effect-image-batch-select">
                <input
                  checked={allImagesSelected}
                  disabled={!draft.image_list.length}
                  onChange={toggleAllImageSelection}
                  type="checkbox"
                />
                <span>{t("effect.asset.selectAllImages")}</span>
              </label>
              <AsyncButton
                disabled={!selectedImageIndexes.length}
                icon={<Music aria-hidden className="button__icon" />}
                loading={imageAudioBatchUploadMutation.isPending}
                onClick={() => setImageAudioBatchPickerOpen(true)}
                variant="ghost"
              >
                {t("effect.asset.batchInsertAudio")}
              </AsyncButton>
              <AsyncButton
                icon={<Upload aria-hidden className="button__icon" />}
                loading={saveMutation.isPending || imageUploadMutation.isPending}
                onClick={handleUploadImage}
              >
                {t("effect.asset.uploadImage")}
              </AsyncButton>
            </div>
          </div>
          {draft.image_list.length === 0 ? (
            <EmptyState title={t("effect.asset.emptyImage")} />
          ) : (
            <div className="effect-image-list">
              {draft.image_list.map((path, index) => {
                const audioPath = draft.image_audio_list[index] ?? "";
                const imageName = baseName(path);
                const audioName = baseName(audioPath);
                const isSelected = selectedImageIndexSet.has(index);
                return (
                  <div className="effect-image-row" key={`${path}-${index}`}>
                    <label className="effect-image-row__check">
                      <input
                        aria-label={t("effect.asset.selectImage", { index: index + 1 })}
                        checked={isSelected}
                        onChange={(event) => toggleImageSelection(index, event.target.checked)}
                        type="checkbox"
                      />
                    </label>
                    <figure className="effect-image-row__image">
                      <img alt={imageRowTags[index] || imageName} src={fileUrl(path)} />
                      <figcaption title={path}>{imageName}</figcaption>
                    </figure>
                    <div className="effect-image-row__controls">
                      <TextInput
                        onChange={(event) => updateImageRowTag(index, event.target.value)}
                        value={imageRowTags[index] ?? ""}
                      />
                      <AsyncButton
                        icon={<Save aria-hidden className="button__icon" />}
                        loading={imageTagsSaveMutation.isPending}
                        onClick={() => imageTagsSaveMutation.mutate()}
                        variant="ghost"
                      >
                        {t("effect.action.saveImageTags")}
                      </AsyncButton>
                      <Button
                        icon={<Music aria-hidden className="button__icon" />}
                        onClick={() => setImageAudioTargetIndex(index)}
                        variant="ghost"
                      >
                        {t("effect.asset.insertAudio")}
                      </Button>
                      {audioPath ? (
                        <span className="effect-image-row__audio" title={audioPath}>
                          <small>{audioName}</small>
                          <AudioPlayer
                            compact
                            label={`${t("effect.asset.preview")} ${audioName}`}
                            src={fileUrl(audioPath)}
                          />
                        </span>
                      ) : null}
                      <AsyncButton
                        icon={<Trash2 aria-hidden className="button__icon" />}
                        loading={imageDeleteMutation.isPending}
                        onClick={() => imageDeleteMutation.mutate(index)}
                        variant="danger"
                      >
                        {t("common.delete")}
                      </AsyncButton>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Audio section */}
        <section className="section page-section-anchor" id="effect-audio">
          <div className="section__header">
            <h2 className="section__title">{t("effect.section.audio")}</h2>
            <div className="section__actions">
              <AsyncButton
                icon={<Upload aria-hidden className="button__icon" />}
                loading={saveMutation.isPending || audioUploadMutation.isPending}
                onClick={handleUploadAudio}
              >
                {t("effect.asset.uploadAudio")}
              </AsyncButton>
              <AsyncButton
                icon={<Save aria-hidden className="button__icon" />}
                loading={audioTagsSaveMutation.isPending}
                onClick={() => {
                  if (!currentEffectName) {
                    showToast({
                      kind: "error",
                      message: t("effect.validation.nameRequired"),
                      title: t("effect.action.saveAudioTags"),
                    });
                    return;
                  }
                  audioTagsSaveMutation.mutate();
                }}
                variant="ghost"
              >
                {t("effect.action.saveAudioTags")}
              </AsyncButton>
              <AsyncButton
                icon={<Trash2 aria-hidden className="button__icon" />}
                disabled={!canDeleteSelected}
                loading={audioBatchDeleteMutation.isPending}
                onClick={() => {
                  const validIndexes = selectedAudioIndexes.filter((i) => i >= 0 && i < draft.audio_list.length);
                  if (!validIndexes.length) {
                    showToast({ kind: "error", title: t("effect.asset.noSelectedAudio") });
                    return;
                  }
                  setPendingDelete({
                    count: validIndexes.length,
                    indexes: validIndexes,
                    kind: "selected-audio",
                    name: currentEffectName,
                  });
                }}
                variant="danger"
              >
                {t("effect.asset.deleteSelectedAudio")}
              </AsyncButton>
              <Button
                icon={<Trash2 aria-hidden className="button__icon" />}
                onClick={() => {
                  if (!currentEffectName || !draft.audio_list.length) {
                    showToast({ kind: "error", title: t("effect.asset.clearAudio") });
                    return;
                  }
                  setPendingDelete({ count: draft.audio_list.length, kind: "all-audio", name: currentEffectName });
                }}
                variant="danger"
              >
                {t("effect.asset.clearAudio")}
              </Button>
            </div>
          </div>
          {draft.audio_list.length === 0 ? (
            <EmptyState title={t("effect.asset.emptyAudio")} />
          ) : (
            <div className="effect-audio-list">
              <div className="effect-audio-list__header">
                <label className="effect-audio-list__check effect-audio-list__check--header">
                  <input
                    aria-label={t("effect.asset.selectAllAudio")}
                    checked={allAudioSelected}
                    onChange={toggleAllAudioSelection}
                    type="checkbox"
                  />
                </label>
                <span className="effect-audio-list__index">{t("effect.asset.index")}</span>
                <span className="effect-audio-list__filename">{t("effect.asset.filename")}</span>
                <span className="effect-audio-list__prompt">{t("effect.asset.prompt")}</span>
                <span className="effect-audio-list__preview">{t("effect.asset.preview")}</span>
              </div>
              <div className="effect-audio-list__rows">
                {draft.audio_list.map((path, index) => {
                  const filename = path ? baseName(path) || `${index + 1}` : `${index + 1}`;
                  const fileSrc = fileUrl(path);
                  const tagValue = audioRowTags[index] ?? "";
                  const isSelected = selectedAudioIndexSet.has(index);

                  return (
                    <div className="effect-audio-row" key={`${path || index}-${index}`}>
                      <label className="effect-audio-list__check">
                        <input
                          aria-label={t("effect.asset.selectAudio", { index: index + 1 })}
                          checked={isSelected}
                          onChange={(event) => toggleAudioSelection(index, event.target.checked)}
                          type="checkbox"
                        />
                      </label>
                      <span className="effect-audio-list__index">{index + 1}</span>
                      <span className="effect-audio-list__filename" title={path || undefined}>
                        <Music aria-hidden className="asset-row__icon" />
                        {filename}
                      </span>
                      <span className="effect-audio-list__prompt">
                        <TextInput
                          onChange={(event) => updateAudioRowTag(index, event.target.value)}
                          value={tagValue}
                        />
                      </span>
                      <span className="effect-audio-list__preview">
                        <AudioPlayer compact label={`${t("effect.asset.preview")} ${filename}`} src={fileSrc} />
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>
      </section>

      <PathPickerDialog
        acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
        multiple
        onClose={() => setAudioUploadPickerOpen(false)}
        onSelect={(path) => audioUploadMutation.mutate([path])}
        onSelectMany={(paths) => audioUploadMutation.mutate(paths)}
        open={audioUploadPickerOpen}
        title={t("effect.asset.uploadAudio")}
      />
      <PathPickerDialog
        acceptedExtensions={[".jpeg", ".jpg", ".png"]}
        multiple
        onClose={() => setImageUploadPickerOpen(false)}
        onSelect={(path) => imageUploadMutation.mutate([path])}
        onSelectMany={(paths) => imageUploadMutation.mutate(paths)}
        open={imageUploadPickerOpen}
        title={t("effect.asset.uploadImage")}
      />
      <PathPickerDialog
        acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
        onClose={() => setImageAudioBatchPickerOpen(false)}
        onSelect={(path) => {
          const indexes = selectedImageIndexes.filter((index) => index >= 0 && index < draft.image_list.length);
          if (indexes.length) imageAudioBatchUploadMutation.mutate({ indexes, path });
        }}
        open={imageAudioBatchPickerOpen}
        title={t("effect.asset.batchInsertAudio")}
      />
      <PathPickerDialog
        acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
        onClose={() => setImageAudioTargetIndex(null)}
        onSelect={(path) => {
          if (imageAudioTargetIndex !== null) imageAudioUploadMutation.mutate({ index: imageAudioTargetIndex, path });
        }}
        open={imageAudioTargetIndex !== null}
        title={t("effect.asset.insertAudio")}
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
