import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, Music, Palette, Plus, Save, Trash2, Upload } from "lucide-react";

import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";

import {
  effectsQueryKey,
  deleteAllEffectAudio,
  deleteEffect,
  deleteEffectAudio,
  exportEffect,
  importEffects,
  listEffects,
  saveEffect,
  saveEffectAudioTags,
  uploadEffectAudio,
} from "../../entities/effect/repository";
import type { Effect } from "../../entities/config/types";
import type { MessageKey } from "../../shared/i18n";
import { useI18n } from "../../shared/i18n";
import { baseName, numberedTags, tagContents } from "../../shared/assets/assetText";
import { openExternal } from "../../entities/files/repository";
import {
  AlertDialog,
  AsyncButton,
  Button,
  EmptyState,
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
  };
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
  const [importPickerOpen, setImportPickerOpen] = useState(false);
  const [audioUploadPickerOpen, setAudioUploadPickerOpen] = useState(false);
  const [nameError, setNameError] = useState("");
  const colorInputRef = useRef<HTMLInputElement | null>(null);
  const colorPickerValue = /^#[0-9a-fA-F]{6}$/.test(draft.color || "") ? draft.color : DEFAULT_CHARACTER_COLOR;
  const openColorPicker = useCallback(() => {
    colorInputRef.current?.click();
  }, []);

  const selected = useMemo(
    () => (isCreating ? undefined : (data.find((ef) => ef.name === selectedName) ?? data[0])),
    [data, isCreating, selectedName],
  );
  const currentEffectName = isCreating ? "" : selectedName;

  useEffect(() => {
    if (selected) {
      setSelectedName(selected.name);
      setDraft(structuredClone(selected));
      setSelectedAudioIndexes([]);
      setNameError("");
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
    onSuccess(effect) {
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setIsCreating(false);
      setSelectedName(effect.name);
      showToast({ kind: "success", title: t("effect.toast.saved") });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteEffect,
    onSuccess() {
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      showToast({ kind: "success", title: t("effect.toast.deleted") });
    },
    onError(error) {
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
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      const lastImported = imported[imported.length - 1];
      if (lastImported) {
        setIsCreating(false);
        setSelectedName(lastImported.name);
        setDraft(lastImported);
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
      queryClient.invalidateQueries({ queryKey: effectsQueryKey });
      setDraft((current) => ({ ...current, audio_tags: effect.audio_tags }));
      showToast({ kind: "success", title: t("effect.action.saveAudioTags") });
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
      const tags = tagContents(current.audio_tags, current.audio_list.length);
      tags[index] = value;
      return { ...current, audio_tags: numberedTags("特效", tags) };
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

  const saveDraft = useCallback(
    (forceNew = false) => {
      const trimmed = draft.name.trim();
      if (!trimmed) {
        setNameError(t("effect.validation.nameRequired"));
        showToast({
          kind: "error",
          message: t("common.fixInvalidFields"),
          title: t("common.validationFailed"),
        });
        return;
      }
      saveMutation.mutate({
        effect: { ...draft, name: trimmed },
        originalName: forceNew || isCreating ? undefined : selectedName,
      });
    },
    [draft, isCreating, selectedName, saveMutation, showToast, t],
  );

  /* 上传音频：如果方案尚未保存，先自动保存再打开文件选择器 */
  const handleUploadAudio = useCallback(() => {
    const trimmed = draft.name.trim();
    if (!trimmed) {
      setNameError(t("effect.validation.nameRequired"));
      showToast({
        kind: "error",
        message: t("common.fixInvalidFields"),
        title: t("effect.asset.uploadAudio"),
      });
      return;
    }
    if (!currentEffectName) {
      saveMutation.mutate(
        { effect: { ...draft, name: trimmed }, originalName: undefined },
        {
          onSuccess: () => {
            setAudioUploadPickerOpen(true);
          },
        },
      );
      return;
    }
    setAudioUploadPickerOpen(true);
  }, [currentEffectName, draft, saveMutation, showToast, t]);

  const audioRowTags = useMemo(
    () => tagContents(draft.audio_tags, draft.audio_list.length),
    [draft.audio_list.length, draft.audio_tags],
  );

  const selectedAudioIndexSet = useMemo(() => new Set(selectedAudioIndexes), [selectedAudioIndexes]);

  const allAudioSelected = draft.audio_list.length > 0 && selectedAudioIndexes.length === draft.audio_list.length;

  const canDeleteSelected = currentEffectName && selectedAudioIndexes.length > 0;

  return (
    <div className="page effect-page">
      <header className="page__header effect-page__header">
        <div className="effect-page__heading">
          <h1 className="page__title">{t("effect.title")}</h1>
          <p className="page__description">{t("effect.description")}</p>
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
                setIsCreating(false);
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
              variant="ghost"
            >
              {t("common.export")}
            </AsyncButton>
          </div>
          <Button icon={<Plus aria-hidden className="button__icon" />} onClick={() => saveDraft(true)}>
            {t("common.new")}
          </Button>
          <AsyncButton
            icon={<Save aria-hidden className="button__icon" />}
            loading={saveMutation.isPending}
            onClick={() => saveDraft()}
            variant="primary"
          >
            {t("common.save")}
          </AsyncButton>
        </div>
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
        <section className="section">
          <div className="section__header">
            <h2 className="section__title">{t("effect.section.info")}</h2>
            <div className="page__actions">
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
            <label className="field-row">
              <span className="field-row__label">{t("effect.field.name")}</span>
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

        {/* Audio section */}
        <section className="section">
          <div className="section__header">
            <h2 className="section__title">{t("effect.section.audio")}</h2>
            <div className="page__actions">
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
