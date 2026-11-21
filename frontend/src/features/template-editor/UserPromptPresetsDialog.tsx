import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  FolderCog,
  GripVertical,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";

import { useI18n } from "../../shared/i18n";
import type { AppliedUserPromptPreset, UserPromptPreset, UserPromptPresetLibrary } from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, Select, TextArea, TextInput, useToast } from "../../shared/ui";
import { getCharacterChipStyle } from "./templateFlow";
import {
  PRESET_COLOR_SWATCHES,
  composeScenarioWithPresets,
  createUserPromptPresetId,
  normalizeUserPromptPresetLibrary,
  reorderPresetIds,
  reorderPresetIdsById,
  resolveSelectedPresets,
  toAppliedPresets,
} from "./userPromptPresets";

export interface UserPromptCommit {
  selectedPresetIds: string[];
  appliedPresets: AppliedUserPromptPreset[];
}

interface UserPromptPresetsDialogProps {
  open: boolean;
  baseScenario: string;
  selectedPresetIds: string[];
  appliedPresets: AppliedUserPromptPreset[];
  library: UserPromptPresetLibrary;
  libraryReady?: boolean;
  libraryLoading?: boolean;
  libraryError?: string;
  savingLibrary?: boolean;
  onRetryLibrary?: () => void;
  onSaveLibrary: (nextLibrary: UserPromptPresetLibrary) => Promise<UserPromptPresetLibrary>;
  onClose: () => void;
  onConfirm: (next: UserPromptCommit) => void;
}

const GROUP_ALL = "__all__";
const GROUP_UNGROUPED = "__ungrouped__";
const NEW_GROUP_SENTINEL = "__new_group__";

export function UserPromptPresetsDialog({
  open,
  baseScenario,
  selectedPresetIds,
  appliedPresets,
  library,
  libraryReady = true,
  libraryLoading = false,
  libraryError = "",
  savingLibrary = false,
  onRetryLibrary,
  onSaveLibrary,
  onClose,
  onConfirm,
}: UserPromptPresetsDialogProps) {
  const { t } = useI18n();
  const { showToast } = useToast();
  const effectiveLibraryReady = libraryReady && !libraryLoading && !libraryError;
  const mutationDisabled = savingLibrary || !effectiveLibraryReady;

  const [draftSelectedIds, setDraftSelectedIds] = useState<string[]>([]);
  const [draftSnapshots, setDraftSnapshots] = useState<AppliedUserPromptPreset[]>([]);
  const [activeGroup, setActiveGroup] = useState<string>(GROUP_ALL);

  // Preset inline create/edit form
  const [presetEditorMode, setPresetEditorMode] = useState<"none" | "create" | "edit">("none");
  const [editingPresetId, setEditingPresetId] = useState("");
  const [formName, setFormName] = useState("");
  const [formGroupChoice, setFormGroupChoice] = useState("");
  const [formNewGroup, setFormNewGroup] = useState("");
  const [formColor, setFormColor] = useState<string>(PRESET_COLOR_SWATCHES[0]);
  const [formContent, setFormContent] = useState("");
  const [formError, setFormError] = useState("");

  // Group manager inline panel
  const [manageGroupsOpen, setManageGroupsOpen] = useState(false);
  const [newGroupInput, setNewGroupInput] = useState("");
  const [renamingGroup, setRenamingGroup] = useState("");
  const [renameGroupValue, setRenameGroupValue] = useState("");
  const [groupError, setGroupError] = useState("");

  // Final composed preview & drag state
  const [previewOpen, setPreviewOpen] = useState(false);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false;
      return;
    }
    if (wasOpenRef.current) {
      return;
    }
    wasOpenRef.current = true;
    setDraftSelectedIds([...selectedPresetIds]);
    setDraftSnapshots(appliedPresets.map((item) => ({ ...item })));
    setActiveGroup(GROUP_ALL);
    setPresetEditorMode("none");
    setEditingPresetId("");
    setFormError("");
    setManageGroupsOpen(false);
    setRenamingGroup("");
    setGroupError("");
    setPreviewOpen(false);
    setDraggedId(null);
    setDragOverId(null);
  }, [appliedPresets, open, selectedPresetIds]);

  const normalizedLibrary = useMemo(() => normalizeUserPromptPresetLibrary(library), [library]);

  const resolvedSelected = useMemo(
    () =>
      resolveSelectedPresets(draftSelectedIds, normalizedLibrary, draftSnapshots, {
        libraryLoaded: effectiveLibraryReady,
      }),
    [draftSelectedIds, draftSnapshots, effectiveLibraryReady, normalizedLibrary],
  );
  const selectedIdSet = useMemo(() => new Set(draftSelectedIds), [draftSelectedIds]);

  const visiblePresets = useMemo(() => {
    if (activeGroup === GROUP_ALL) {
      return normalizedLibrary.presets;
    }
    if (activeGroup === GROUP_UNGROUPED) {
      return normalizedLibrary.presets.filter((preset) => !preset.group);
    }
    return normalizedLibrary.presets.filter((preset) => preset.group === activeGroup);
  }, [activeGroup, normalizedLibrary.presets]);

  const groupCounts = useMemo(() => {
    const counts = new Map<string, number>();
    let ungrouped = 0;
    for (const preset of normalizedLibrary.presets) {
      if (!preset.group) {
        ungrouped += 1;
      } else {
        counts.set(preset.group, (counts.get(preset.group) ?? 0) + 1);
      }
    }
    return { counts, ungrouped };
  }, [normalizedLibrary.presets]);

  const composedPreview = useMemo(
    () => composeScenarioWithPresets(baseScenario, resolvedSelected),
    [baseScenario, resolvedSelected],
  );

  const togglePresetSelection = (presetId: string) => {
    setDraftSelectedIds((current) =>
      current.includes(presetId) ? current.filter((id) => id !== presetId) : [...current, presetId],
    );
    setDraftSnapshots((current) => current.filter((item) => item.id !== presetId));
  };

  const openCreatePreset = () => {
    if (!effectiveLibraryReady) return;
    setManageGroupsOpen(false);
    setPresetEditorMode("create");
    setEditingPresetId("");
    setFormName("");
    setFormGroupChoice(activeGroup !== GROUP_ALL && activeGroup !== GROUP_UNGROUPED ? activeGroup : "");
    setFormNewGroup("");
    setFormColor(PRESET_COLOR_SWATCHES[normalizedLibrary.presets.length % PRESET_COLOR_SWATCHES.length]);
    setFormContent("");
    setFormError("");
  };

  const openEditPreset = (preset: UserPromptPreset) => {
    if (!effectiveLibraryReady) return;
    setManageGroupsOpen(false);
    setPresetEditorMode("edit");
    setEditingPresetId(preset.id);
    setFormName(preset.name);
    setFormGroupChoice(preset.group || "");
    setFormNewGroup("");
    setFormColor(preset.color || PRESET_COLOR_SWATCHES[0]);
    setFormContent(preset.content);
    setFormError("");
  };

  const handleSavePreset = async () => {
    if (!effectiveLibraryReady) return;
    const trimmedName = formName.trim();
    const trimmedContent = formContent.trim();
    const targetGroup = formGroupChoice === NEW_GROUP_SENTINEL ? formNewGroup.trim() : formGroupChoice.trim();

    if (!trimmedName) {
      setFormError(t("template.presets.validationNameRequired"));
      return;
    }
    if (!trimmedContent) {
      setFormError(t("template.presets.validationContentRequired"));
      return;
    }
    if (formGroupChoice === NEW_GROUP_SENTINEL && !targetGroup) {
      setFormError(t("template.presets.groupValidationRequired"));
      return;
    }

    const duplicate = normalizedLibrary.presets.some(
      (preset) =>
        preset.id !== editingPresetId &&
        preset.group.toLowerCase() === targetGroup.toLowerCase() &&
        preset.name.toLowerCase() === trimmedName.toLowerCase(),
    );
    if (duplicate) {
      setFormError(t("template.presets.validationDuplicateName"));
      return;
    }

    const nextGroups =
      targetGroup && !normalizedLibrary.groups.includes(targetGroup)
        ? [...normalizedLibrary.groups, targetGroup]
        : [...normalizedLibrary.groups];

    let savedId = editingPresetId;
    let nextPresets: UserPromptPreset[];
    if (presetEditorMode === "create") {
      savedId = createUserPromptPresetId();
      const created: UserPromptPreset = {
        id: savedId,
        name: trimmedName,
        group: targetGroup,
        color: formColor,
        content: formContent.replace(/\r\n/g, "\n"),
      };
      nextPresets = [...normalizedLibrary.presets, created];
    } else {
      nextPresets = normalizedLibrary.presets.map((preset) =>
        preset.id === editingPresetId
          ? {
              ...preset,
              name: trimmedName,
              group: targetGroup,
              color: formColor,
              content: formContent.replace(/\r\n/g, "\n"),
            }
          : preset,
      );
    }

    try {
      await onSaveLibrary(normalizeUserPromptPresetLibrary({ groups: nextGroups, presets: nextPresets }));
      if (presetEditorMode === "create" && savedId) {
        setDraftSelectedIds((current) => (current.includes(savedId) ? current : [...current, savedId]));
      } else if (presetEditorMode === "edit" && editingPresetId) {
        setDraftSnapshots((current) => current.filter((item) => item.id !== editingPresetId));
      }
      setPresetEditorMode("none");
      setEditingPresetId("");
      setFormError("");
      showToast({ kind: "success", title: t("template.presets.toastSaved") });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : t("template.presets.saveFailed"));
    }
  };

  const handleDeletePreset = async (preset: UserPromptPreset) => {
    if (!effectiveLibraryReady) return;
    if (!window.confirm(t("template.presets.deleteConfirm", { name: preset.name }))) {
      return;
    }
    const nextPresets = normalizedLibrary.presets.filter((item) => item.id !== preset.id);
    try {
      await onSaveLibrary(normalizeUserPromptPresetLibrary({ groups: normalizedLibrary.groups, presets: nextPresets }));
      setDraftSelectedIds((current) => current.filter((id) => id !== preset.id));
      setDraftSnapshots((current) => current.filter((item) => item.id !== preset.id));
      setPresetEditorMode("none");
      setEditingPresetId("");
      showToast({ kind: "success", title: t("template.presets.toastDeleted") });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : t("template.presets.saveFailed"));
    }
  };

  const handleAddGroup = async () => {
    if (!effectiveLibraryReady) return;
    const trimmed = newGroupInput.trim();
    if (!trimmed) {
      setGroupError(t("template.presets.groupValidationRequired"));
      return;
    }
    if (normalizedLibrary.groups.some((group) => group.toLowerCase() === trimmed.toLowerCase())) {
      setGroupError(t("template.presets.groupValidationDuplicate"));
      return;
    }
    try {
      await onSaveLibrary(
        normalizeUserPromptPresetLibrary({
          groups: [...normalizedLibrary.groups, trimmed],
          presets: normalizedLibrary.presets,
        }),
      );
      setNewGroupInput("");
      setGroupError("");
    } catch (error) {
      setGroupError(error instanceof Error ? error.message : t("template.presets.saveFailed"));
    }
  };

  const handleConfirmRenameGroup = async (oldGroup: string) => {
    if (!effectiveLibraryReady) return;
    const trimmed = renameGroupValue.trim();
    if (!trimmed) {
      setGroupError(t("template.presets.groupValidationRequired"));
      return;
    }
    if (
      trimmed !== oldGroup &&
      normalizedLibrary.groups.some((group) => group.toLowerCase() === trimmed.toLowerCase())
    ) {
      setGroupError(t("template.presets.groupValidationDuplicate"));
      return;
    }
    const nextGroups = normalizedLibrary.groups.map((group) => (group === oldGroup ? trimmed : group));
    const nextPresets = normalizedLibrary.presets.map((preset) =>
      preset.group === oldGroup ? { ...preset, group: trimmed } : preset,
    );
    try {
      await onSaveLibrary(normalizeUserPromptPresetLibrary({ groups: nextGroups, presets: nextPresets }));
      setDraftSnapshots((current) =>
        current.map((item) => (item.group === oldGroup ? { ...item, group: trimmed } : item)),
      );
      if (activeGroup === oldGroup) {
        setActiveGroup(trimmed);
      }
      setRenamingGroup("");
      setRenameGroupValue("");
      setGroupError("");
    } catch (error) {
      setGroupError(error instanceof Error ? error.message : t("template.presets.saveFailed"));
    }
  };

  const handleDeleteGroup = async (groupName: string) => {
    if (!effectiveLibraryReady) return;
    const nextGroups = normalizedLibrary.groups.filter((group) => group !== groupName);
    const nextPresets = normalizedLibrary.presets.map((preset) =>
      preset.group === groupName ? { ...preset, group: "" } : preset,
    );
    try {
      await onSaveLibrary(normalizeUserPromptPresetLibrary({ groups: nextGroups, presets: nextPresets }));
      setDraftSnapshots((current) => current.map((item) => (item.group === groupName ? { ...item, group: "" } : item)));
      if (activeGroup === groupName) {
        setActiveGroup(GROUP_ALL);
      }
      setGroupError("");
    } catch (error) {
      setGroupError(error instanceof Error ? error.message : t("template.presets.saveFailed"));
    }
  };

  const handleMoveGroup = async (index: number, delta: number) => {
    if (!effectiveLibraryReady) return;
    const nextGroups = reorderPresetIds(normalizedLibrary.groups, index, index + delta);
    try {
      await onSaveLibrary(normalizeUserPromptPresetLibrary({ groups: nextGroups, presets: normalizedLibrary.presets }));
    } catch (error) {
      setGroupError(error instanceof Error ? error.message : t("template.presets.saveFailed"));
    }
  };

  const handleConfirm = () => {
    onConfirm({
      selectedPresetIds: resolvedSelected.map((preset) => preset.id),
      appliedPresets: toAppliedPresets(resolvedSelected),
    });
  };

  return (
    <Dialog
      bodyClassName="template-editor-dialog__body"
      className="template-editor-dialog template-editor-dialog--user-prompt"
      closeLabel={t("common.close")}
      dismissible={!savingLibrary}
      footer={
        <>
          <Button disabled={savingLibrary} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            disabled={mutationDisabled}
            icon={<Check aria-hidden className="button__icon" />}
            onClick={handleConfirm}
            variant="primary"
          >
            {t("common.confirm")}
          </Button>
        </>
      }
      onClose={onClose}
      open={open}
      title={t("template.presets.dialogTitle")}
    >
      <section className="template-dialog-subsection">
        <div className="template-dialog-subsection__header">
          <h3 className="template-dialog-subsection__title">{t("template.presets.sectionTitle")}</h3>
          <div className="template-dialog-toolbar__actions">
            <Button
              disabled={mutationDisabled}
              icon={<Plus aria-hidden className="button__icon" />}
              onClick={openCreatePreset}
              variant="ghost"
            >
              {t("template.presets.newPreset")}
            </Button>
            <Button
              disabled={mutationDisabled}
              icon={<FolderCog aria-hidden className="button__icon" />}
              onClick={() => {
                setPresetEditorMode("none");
                setManageGroupsOpen((current) => !current);
                setGroupError("");
              }}
              variant="ghost"
            >
              {t(manageGroupsOpen ? "template.presets.closeManageGroups" : "template.presets.manageGroups")}
            </Button>
          </div>
        </div>

        <div aria-label={t("template.presets.fieldGroup")} className="template-preset-group-tabs" role="tablist">
          <button
            aria-selected={activeGroup === GROUP_ALL}
            className={`template-preset-group-tab${activeGroup === GROUP_ALL ? " is-active" : ""}`}
            onClick={() => setActiveGroup(GROUP_ALL)}
            role="tab"
            type="button"
          >
            {t("template.presets.allGroups")} ({normalizedLibrary.presets.length})
          </button>
          <button
            aria-selected={activeGroup === GROUP_UNGROUPED}
            className={`template-preset-group-tab${activeGroup === GROUP_UNGROUPED ? " is-active" : ""}`}
            onClick={() => setActiveGroup(GROUP_UNGROUPED)}
            role="tab"
            type="button"
          >
            {t("template.presets.ungrouped")} ({groupCounts.ungrouped})
          </button>
          {normalizedLibrary.groups.map((group) => (
            <button
              aria-selected={activeGroup === group}
              className={`template-preset-group-tab${activeGroup === group ? " is-active" : ""}`}
              key={group}
              onClick={() => setActiveGroup(group)}
              role="tab"
              type="button"
            >
              {group} ({groupCounts.counts.get(group) ?? 0})
            </button>
          ))}
        </div>

        {manageGroupsOpen ? (
          <div className="template-preset-inline-panel">
            <p className="template-dialog-subsection__hint">{t("template.presets.groupDeletedMoved")}</p>
            {groupError ? <p className="field-error">{groupError}</p> : null}
            <div className="template-preset-group-add">
              <TextInput
                aria-label={t("template.presets.groupAddPlaceholder")}
                disabled={savingLibrary}
                onChange={(event) => setNewGroupInput(event.target.value)}
                placeholder={t("template.presets.groupAddPlaceholder")}
                value={newGroupInput}
              />
              <AsyncButton loading={savingLibrary} onClick={() => void handleAddGroup()}>
                {t("template.presets.groupAdd")}
              </AsyncButton>
            </div>
            {normalizedLibrary.groups.length === 0 ? (
              <p className="template-dialog-empty">{t("template.presets.groupEmpty")}</p>
            ) : (
              <ul className="template-preset-group-list">
                {normalizedLibrary.groups.map((group, index) => (
                  <li className="template-preset-group-row" key={group}>
                    {renamingGroup === group ? (
                      <div className="template-preset-group-row__edit">
                        <TextInput
                          aria-label={group}
                          disabled={savingLibrary}
                          onChange={(event) => setRenameGroupValue(event.target.value)}
                          value={renameGroupValue}
                        />
                        <Button
                          disabled={savingLibrary}
                          onClick={() => void handleConfirmRenameGroup(group)}
                          variant="primary"
                        >
                          {t("common.save")}
                        </Button>
                        <Button disabled={savingLibrary} onClick={() => setRenamingGroup("")}>
                          {t("common.cancel")}
                        </Button>
                      </div>
                    ) : (
                      <>
                        <span className="template-preset-group-row__name">
                          {group} ({groupCounts.counts.get(group) ?? 0})
                        </span>
                        <div className="template-preset-group-row__actions">
                          <Button
                            aria-label={`${t("template.presets.groupMoveLeft")} ${group}`}
                            disabled={savingLibrary || index === 0}
                            onClick={() => void handleMoveGroup(index, -1)}
                            variant="ghost"
                          >
                            <ArrowLeft aria-hidden className="button__icon" />
                          </Button>
                          <Button
                            aria-label={`${t("template.presets.groupMoveRight")} ${group}`}
                            disabled={savingLibrary || index === normalizedLibrary.groups.length - 1}
                            onClick={() => void handleMoveGroup(index, 1)}
                            variant="ghost"
                          >
                            <ArrowRight aria-hidden className="button__icon" />
                          </Button>
                          <Button
                            disabled={savingLibrary}
                            onClick={() => {
                              setRenamingGroup(group);
                              setRenameGroupValue(group);
                              setGroupError("");
                            }}
                            variant="ghost"
                          >
                            {t("template.presets.groupRename")}
                          </Button>
                          <Button
                            disabled={savingLibrary}
                            onClick={() => void handleDeleteGroup(group)}
                            variant="danger"
                          >
                            {t("template.presets.groupDelete")}
                          </Button>
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {presetEditorMode !== "none" ? (
          <div className="template-preset-inline-panel">
            <h4 className="template-preset-inline-panel__title">
              {t(presetEditorMode === "create" ? "template.presets.newPreset" : "template.presets.editPreset")}
            </h4>
            {formError ? <p className="field-error">{formError}</p> : null}
            <div className="template-preset-form-grid">
              <label className="template-stack-field">
                <span className="template-panel__label">{t("template.presets.fieldName")}</span>
                <TextInput
                  aria-label={t("template.presets.fieldName")}
                  disabled={savingLibrary}
                  maxLength={64}
                  onChange={(event) => setFormName(event.target.value)}
                  placeholder={t("template.presets.fieldNamePlaceholder")}
                  value={formName}
                />
              </label>
              <label className="template-stack-field">
                <span className="template-panel__label">{t("template.presets.fieldGroup")}</span>
                <Select
                  aria-label={t("template.presets.fieldGroup")}
                  disabled={savingLibrary}
                  onChange={(event) => setFormGroupChoice(event.target.value)}
                  value={formGroupChoice}
                >
                  <option value="">{t("template.presets.ungrouped")}</option>
                  {normalizedLibrary.groups.map((group) => (
                    <option key={group} value={group}>
                      {group}
                    </option>
                  ))}
                  <option value={NEW_GROUP_SENTINEL}>{t("template.presets.newGroupOption")}</option>
                </Select>
              </label>
            </div>
            {formGroupChoice === NEW_GROUP_SENTINEL ? (
              <label className="template-stack-field">
                <span className="template-panel__label">{t("template.presets.newGroupPlaceholder")}</span>
                <TextInput
                  aria-label={t("template.presets.newGroupPlaceholder")}
                  disabled={savingLibrary}
                  maxLength={64}
                  onChange={(event) => setFormNewGroup(event.target.value)}
                  placeholder={t("template.presets.newGroupPlaceholder")}
                  value={formNewGroup}
                />
              </label>
            ) : null}
            <div className="template-stack-field">
              <span className="template-panel__label">{t("template.presets.fieldColor")}</span>
              <div className="template-preset-color-row" role="group" aria-label={t("template.presets.fieldColor")}>
                {PRESET_COLOR_SWATCHES.map((swatch) => (
                  <button
                    aria-label={swatch}
                    aria-pressed={formColor === swatch}
                    className={`template-preset-color-swatch${formColor === swatch ? " is-selected" : ""}`}
                    disabled={savingLibrary}
                    key={swatch}
                    onClick={() => setFormColor(swatch)}
                    style={{ background: swatch }}
                    type="button"
                  />
                ))}
              </div>
            </div>
            <label className="template-stack-field">
              <span className="template-panel__label">{t("template.presets.fieldContent")}</span>
              <TextArea
                aria-label={t("template.presets.fieldContent")}
                disabled={savingLibrary}
                onChange={(event) => setFormContent(event.target.value)}
                placeholder={t("template.presets.fieldContentPlaceholder")}
                rows={4}
                value={formContent}
              />
            </label>
            <div className="template-preset-inline-panel__actions">
              {presetEditorMode === "edit" ? (
                <Button
                  disabled={savingLibrary}
                  icon={<Trash2 aria-hidden className="button__icon" />}
                  onClick={() => {
                    const target = normalizedLibrary.presets.find((item) => item.id === editingPresetId);
                    if (target) void handleDeletePreset(target);
                  }}
                  variant="danger"
                >
                  {t("template.presets.deletePreset")}
                </Button>
              ) : null}
              <div className="template-dialog-toolbar__actions">
                <Button disabled={savingLibrary} onClick={() => setPresetEditorMode("none")}>
                  {t("common.cancel")}
                </Button>
                <AsyncButton loading={savingLibrary} onClick={() => void handleSavePreset()} variant="primary">
                  {t("template.presets.savePreset")}
                </AsyncButton>
              </div>
            </div>
          </div>
        ) : null}

        <div aria-label={t("template.presets.sectionTitle")} className="template-dialog-chip-grid" role="group">
          {libraryLoading ? (
            <p className="template-dialog-empty">{t("template.presets.loading")}</p>
          ) : libraryError ? (
            <div className="template-dialog-empty">
              <p className="field-error">{libraryError}</p>
              {onRetryLibrary ? (
                <Button onClick={onRetryLibrary} variant="ghost">
                  {t("common.retry")}
                </Button>
              ) : null}
            </div>
          ) : visiblePresets.length === 0 ? (
            <p className="template-dialog-empty">{t("template.presets.empty")}</p>
          ) : (
            visiblePresets.map((preset) => {
              const isSelected = selectedIdSet.has(preset.id);
              return (
                <div className="template-preset-chip-group" key={preset.id}>
                  <button
                    aria-pressed={isSelected}
                    className={`template-character-card template-preset-card${
                      isSelected ? " template-character-card--selected" : ""
                    }`}
                    onClick={() => togglePresetSelection(preset.id)}
                    style={getCharacterChipStyle(preset.color ?? "")}
                    title={preset.content}
                    type="button"
                  >
                    <span aria-hidden className="template-character-card__dot" />
                    <span className="template-character-card__name">{preset.name}</span>
                  </button>
                  <button
                    aria-label={`${t("template.presets.editPreset")} ${preset.name}`}
                    className="template-preset-edit-btn"
                    disabled={mutationDisabled}
                    onClick={() => openEditPreset(preset)}
                    title={t("template.presets.editPreset")}
                    type="button"
                  >
                    <Pencil aria-hidden size={13} />
                  </button>
                </div>
              );
            })
          )}
        </div>

        {resolvedSelected.length > 0 ? (
          <div className="template-preset-order-box">
            <div className="template-preset-order-box__header">
              <span className="template-panel__label">{t("template.presets.orderLabel")}</span>
              <Button
                onClick={() => {
                  setDraftSelectedIds([]);
                  setDraftSnapshots([]);
                }}
                variant="ghost"
              >
                {t("template.presets.clearSelected")}
              </Button>
            </div>
            <ul aria-label={t("template.presets.orderLabel")} className="template-preset-order-list">
              {resolvedSelected.map((preset, index) => {
                const isDragging = draggedId === preset.id;
                const isDragOver = dragOverId === preset.id && draggedId !== preset.id;
                return (
                  <li
                    className={`template-preset-order-item${isDragging ? " is-dragging" : ""}${
                      isDragOver ? " is-drag-over" : ""
                    }${preset.isDeleted ? " is-deleted" : ""}`}
                    data-preset-id={preset.id}
                    draggable
                    key={preset.id}
                    onDragEnd={() => {
                      setDraggedId(null);
                      setDragOverId(null);
                    }}
                    onDragOver={(event) => {
                      event.preventDefault();
                      if (event.dataTransfer) {
                        event.dataTransfer.dropEffect = "move";
                      }
                      if (dragOverId !== preset.id) {
                        setDragOverId(preset.id);
                      }
                    }}
                    onDragStart={(event) => {
                      setDraggedId(preset.id);
                      if (event.dataTransfer) {
                        event.dataTransfer.effectAllowed = "move";
                        event.dataTransfer.setData("text/plain", preset.id);
                      }
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      const sourceId = draggedId || event.dataTransfer?.getData("text/plain") || "";
                      if (sourceId && sourceId !== preset.id) {
                        setDraftSelectedIds((current) => reorderPresetIdsById(current, sourceId, preset.id));
                      }
                      setDraggedId(null);
                      setDragOverId(null);
                    }}
                    style={getCharacterChipStyle(preset.color ?? "")}
                    title={
                      preset.isDeleted ? t("template.presets.deletedClickHint", { name: preset.name }) : preset.content
                    }
                  >
                    <GripVertical aria-hidden className="template-preset-order-item__grip" size={14} />
                    <span className="template-preset-order-item__index">{index + 1}.</span>
                    <span className="template-preset-order-item__name">{preset.name}</span>
                    {preset.isDeleted ? (
                      <span className="template-preset-order-item__deleted">{t("template.presets.deletedBadge")}</span>
                    ) : null}
                    <div className="template-preset-order-item__controls">
                      <button
                        aria-label={t("template.presets.moveLeft", { name: preset.name })}
                        className="template-preset-order-item__btn"
                        disabled={index === 0}
                        onClick={() => setDraftSelectedIds((current) => reorderPresetIds(current, index, index - 1))}
                        type="button"
                      >
                        <ArrowLeft aria-hidden size={12} />
                      </button>
                      <button
                        aria-label={t("template.presets.moveRight", { name: preset.name })}
                        className="template-preset-order-item__btn"
                        disabled={index === resolvedSelected.length - 1}
                        onClick={() => setDraftSelectedIds((current) => reorderPresetIds(current, index, index + 1))}
                        type="button"
                      >
                        <ArrowRight aria-hidden size={12} />
                      </button>
                      <button
                        aria-label={t("template.presets.removeSelected", { name: preset.name })}
                        className="template-preset-order-item__btn template-preset-order-item__remove"
                        onClick={() => {
                          setDraftSelectedIds((current) => current.filter((id) => id !== preset.id));
                          setDraftSnapshots((current) => current.filter((item) => item.id !== preset.id));
                        }}
                        type="button"
                      >
                        <X aria-hidden size={13} />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="template-dialog-subsection">
        <button
          aria-expanded={previewOpen}
          className="template-presets-preview-toggle"
          onClick={() => setPreviewOpen((current) => !current)}
          type="button"
        >
          <span>
            {previewOpen
              ? t("template.presets.previewHide")
              : t("template.presets.previewToggle", { count: resolvedSelected.length })}
          </span>
          {previewOpen ? <ChevronUp aria-hidden size={16} /> : <ChevronDown aria-hidden size={16} />}
        </button>
        {previewOpen ? (
          <pre className="template-presets-preview">
            {composedPreview.trim() ? composedPreview : t("template.presets.previewEmpty")}
          </pre>
        ) : null}
      </section>
    </Dialog>
  );
}
