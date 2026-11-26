import { useEffect, useMemo, useState } from "react";
import {
  CheckSquare,
  Crop,
  FolderPlus,
  Image as ImageIcon,
  Pencil,
  Sparkles,
  Star,
  Tags,
  Trash2,
  Upload,
  Volume2,
} from "lucide-react";

import type { Character, Sprite } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import { VISUAL_MEDIA_EXTENSIONS } from "../../shared/assets/visualMedia";
import { useI18n } from "../../shared/i18n";
import type { SpriteVoiceType } from "../../shared/platform/types";
import type { ImageAssetGalleryItem } from "../../shared/ui";
import {
  AlertDialog,
  AsyncButton,
  AudioPlayer,
  Button,
  EmptyState,
  FilePicker,
  ImageAssetGallery,
  PathPickerDialog,
  PathDisplay,
  SegmentedRadio,
  Select,
  Switch,
  TextInput,
  VisualMedia,
} from "../../shared/ui";
import { DEFAULT_SPRITE_GROUP, normalizeSpriteGroupName, resolveCharacterSpriteGroups } from "./characterEditorUtils";

export interface SpriteGroupsPatch {
  assignments?: Record<string, string>;
  defaultSpriteGroup?: string;
  deleteGroup?: string;
  fallbackToDefaultGroup?: boolean;
  spriteGroups?: string[];
}

interface CharacterSpritesSectionProps {
  activeSpriteGroup?: string;
  autoLabelAvailable?: boolean;
  autoLabelDisabled?: boolean;
  autoLabelPending?: boolean;
  draft: Character;
  emotionTagsPending: boolean;
  generateDisabled?: boolean;
  generateHint?: string;
  id?: string;
  isSavedCharacter?: boolean;
  onActiveSpriteGroupChange?: (group: string) => void;
  onApplySpriteGroups?: (patch: SpriteGroupsPatch) => void;
  onAutoLabel?: () => void;
  onClearSprites: () => void;
  onGenerate?: () => void;
  onOpenBulkTags: () => void;
  onOpenPortraitCrop?: () => void;
  onOpenSmartGroup?: () => void;
  onPendingVoicePathChange: (path: string) => void;
  onSaveTags: () => void;
  onSelectSprite: (index: number) => void;
  onSpriteDelete: () => void;
  onSpriteTagChange: (value: string) => void;
  onSpriteUpload: (paths: string[]) => void;
  onSpriteVoiceDelete: () => void;
  onSpriteVoiceTextBlur: (text: string) => void;
  onSpriteVoiceTextChange: (value: string) => void;
  onSpriteVoiceTypeChange: (value: SpriteVoiceType) => void;
  onSpriteVoiceUpload: () => void;
  pendingVoicePath: string;
  selectedSprite?: Sprite;
  selectedSpriteIndex: number;
  selectedSpriteTag: string;
  spriteDeletePending: boolean;
  spriteGalleryItems: ImageAssetGalleryItem[];
  spriteGroupsPending?: boolean;
  spriteUploadPending: boolean;
  voiceDeletePending: boolean;
  voiceUploadPending: boolean;
}

export function CharacterSpritesSection({
  activeSpriteGroup: controlledActiveGroup,
  autoLabelAvailable = false,
  autoLabelDisabled = true,
  autoLabelPending = false,
  draft,
  emotionTagsPending,
  generateDisabled = false,
  generateHint,
  id,
  isSavedCharacter = false,
  onActiveSpriteGroupChange,
  onApplySpriteGroups,
  onAutoLabel,
  onClearSprites,
  onGenerate,
  onOpenBulkTags,
  onOpenPortraitCrop,
  onOpenSmartGroup,
  onPendingVoicePathChange,
  onSaveTags,
  onSelectSprite,
  onSpriteDelete,
  onSpriteTagChange,
  onSpriteUpload,
  onSpriteVoiceDelete,
  onSpriteVoiceTextBlur,
  onSpriteVoiceTextChange,
  onSpriteVoiceTypeChange,
  onSpriteVoiceUpload,
  pendingVoicePath,
  selectedSprite,
  selectedSpriteIndex,
  selectedSpriteTag,
  spriteDeletePending,
  spriteGalleryItems,
  spriteGroupsPending = false,
  spriteUploadPending,
  voiceDeletePending,
  voiceUploadPending,
}: CharacterSpritesSectionProps) {
  const { t } = useI18n();
  const [spritePickerOpen, setSpritePickerOpen] = useState(false);
  const [internalActiveGroup, setInternalActiveGroup] = useState("__all__");
  const activeSpriteGroup = controlledActiveGroup ?? internalActiveGroup;
  const setActiveSpriteGroup = (nextGroup: string) => {
    if (onActiveSpriteGroupChange) {
      onActiveSpriteGroupChange(nextGroup);
    } else {
      setInternalActiveGroup(nextGroup);
    }
  };

  const [newGroupInput, setNewGroupInput] = useState("");
  const [creatingGroupOpen, setCreatingGroupOpen] = useState(false);
  const [renamingGroup, setRenamingGroup] = useState<string | null>(null);
  const [renameInput, setRenameInput] = useState("");
  const [pendingDeleteGroup, setPendingDeleteGroup] = useState<string | null>(null);
  const [batchSelectMode, setBatchSelectMode] = useState(false);
  const [checkedIndices, setCheckedIndices] = useState<Set<number>>(() => new Set());
  const [batchTargetGroup, setBatchTargetGroup] = useState("");

  useEffect(() => {
    setCreatingGroupOpen(false);
    setNewGroupInput("");
    setRenamingGroup(null);
    setRenameInput("");
    setPendingDeleteGroup(null);
    setBatchSelectMode(false);
    setCheckedIndices(new Set());
    setBatchTargetGroup("");
  }, [draft.name]);

  const spriteGroups = useMemo(() => resolveCharacterSpriteGroups(draft), [draft]);
  const defaultGroup = normalizeSpriteGroupName(draft.default_sprite_group);
  const fallbackToDefault = draft.fallback_to_default_group ?? true;

  useEffect(() => {
    if (activeSpriteGroup !== "__all__" && !spriteGroups.includes(activeSpriteGroup)) {
      setActiveSpriteGroup("__all__");
    }
  }, [activeSpriteGroup, spriteGroups]);

  const groupCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const group of spriteGroups) {
      counts[group] = 0;
    }
    for (const sprite of draft.sprites) {
      const group = normalizeSpriteGroupName(sprite.group);
      counts[group] = (counts[group] ?? 0) + 1;
    }
    return counts;
  }, [draft.sprites, spriteGroups]);

  const visibleGalleryItems = useMemo(() => {
    const indexed = spriteGalleryItems.map((item, index) => {
      const globalIndex = item.globalIndex ?? index;
      const spriteGroup = normalizeSpriteGroupName(draft.sprites[globalIndex]?.group);
      return {
        ...item,
        globalIndex,
        secondaryBadge: activeSpriteGroup === "__all__" && spriteGroups.length > 1 ? spriteGroup : item.secondaryBadge,
        spriteGroup,
      };
    });
    if (activeSpriteGroup === "__all__") {
      return indexed;
    }
    return indexed.filter((item) => item.spriteGroup === activeSpriteGroup);
  }, [activeSpriteGroup, draft.sprites, spriteGalleryItems, spriteGroups.length]);

  const handleSelectGroupTab = (group: string) => {
    setActiveSpriteGroup(group);
    setRenamingGroup(null);
    if (group !== "__all__") {
      const currentGroup = normalizeSpriteGroupName(draft.sprites[selectedSpriteIndex]?.group);
      if (currentGroup !== group) {
        const firstInGroup = draft.sprites.findIndex((sprite) => normalizeSpriteGroupName(sprite.group) === group);
        if (firstInGroup >= 0) {
          onSelectSprite(firstInGroup);
        }
      }
    }
  };

  const handleCreateGroup = () => {
    const trimmed = newGroupInput.trim();
    if (!trimmed || !onApplySpriteGroups) {
      return;
    }
    const nextGroups = spriteGroups.includes(trimmed) ? spriteGroups : [...spriteGroups, trimmed];
    onApplySpriteGroups({ spriteGroups: nextGroups });
    setNewGroupInput("");
    setCreatingGroupOpen(false);
    setActiveSpriteGroup(trimmed);
  };

  const handleConfirmRename = () => {
    const target = renamingGroup;
    const trimmed = renameInput.trim();
    if (!target || !trimmed || trimmed === target || !onApplySpriteGroups) {
      setRenamingGroup(null);
      return;
    }
    const nextGroups = Array.from(new Set(spriteGroups.map((group) => (group === target ? trimmed : group))));
    const assignments: Record<string, string> = {};
    draft.sprites.forEach((sprite, index) => {
      if (normalizeSpriteGroupName(sprite.group) === target) {
        assignments[String(index)] = trimmed;
      }
    });
    onApplySpriteGroups({
      assignments,
      defaultSpriteGroup: defaultGroup === target ? trimmed : defaultGroup,
      spriteGroups: nextGroups,
    });
    setRenamingGroup(null);
    setRenameInput("");
    setActiveSpriteGroup(trimmed);
  };

  const handleConfirmDeleteGroup = () => {
    if (!pendingDeleteGroup || !onApplySpriteGroups) {
      setPendingDeleteGroup(null);
      return;
    }
    const target = pendingDeleteGroup;
    setPendingDeleteGroup(null);
    onApplySpriteGroups({ deleteGroup: target });
    if (activeSpriteGroup === target) {
      setActiveSpriteGroup("__all__");
    }
  };

  const toggleCheckedSprite = (globalIndex: number) => {
    setCheckedIndices((current) => {
      const next = new Set(current);
      if (next.has(globalIndex)) {
        next.delete(globalIndex);
      } else {
        next.add(globalIndex);
      }
      return next;
    });
  };

  const handleSelectVisible = () => {
    setCheckedIndices((current) => {
      const next = new Set(current);
      for (const item of visibleGalleryItems) {
        next.add(item.globalIndex);
      }
      return next;
    });
  };

  const handleBatchMove = () => {
    if (!onApplySpriteGroups || !batchTargetGroup || checkedIndices.size === 0) {
      return;
    }
    const assignments: Record<string, string> = {};
    for (const index of checkedIndices) {
      assignments[String(index)] = batchTargetGroup;
    }
    onApplySpriteGroups({ assignments });
    setCheckedIndices(new Set());
  };

  const voiceType = selectedSprite?.voice_type ?? "fallback";
  const voiceTypeHintKey =
    voiceType === "reference"
      ? "character.sprite.voiceRefHint"
      : voiceType === "preset"
        ? "character.sprite.voicePresetHint"
        : "character.sprite.voiceFallbackHint";

  const showOutfitGroupBar = Boolean(onApplySpriteGroups);
  const selectedSpriteGroup = normalizeSpriteGroupName(selectedSprite?.group);

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("character.section.sprites")}</h2>
        <div className="page__actions">
          <Button icon={<Trash2 aria-hidden className="button__icon" />} onClick={onClearSprites} variant="danger">
            {t("character.sprite.clear")}
          </Button>
          {autoLabelAvailable ? (
            <AsyncButton
              disabled={autoLabelDisabled}
              icon={<Sparkles aria-hidden className="button__icon" />}
              loading={autoLabelPending}
              onClick={onAutoLabel}
              variant="ghost"
            >
              {t("mediaAutoLabel.action")}
            </AsyncButton>
          ) : null}
          <Button
            disabled={!draft.sprites.length}
            icon={<Tags aria-hidden className="button__icon" />}
            onClick={onOpenBulkTags}
            variant="ghost"
          >
            {t("character.sprite.batchTags")}
          </Button>
          {onOpenPortraitCrop ? (
            <Button
              disabled={!draft.sprites.length}
              icon={<Crop aria-hidden className="button__icon" />}
              onClick={onOpenPortraitCrop}
              tooltip={t("character.sprite.portraitCropTitle")}
              variant="ghost"
            >
              {t("character.sprite.portraitCrop")}
            </Button>
          ) : null}
          <Button
            data-sprite-generation-trigger
            disabled={generateDisabled}
            icon={<Sparkles aria-hidden className="button__icon" />}
            onClick={onGenerate}
            tooltip={generateHint}
            variant="default"
          >
            {t("character.sprite.generate")}
          </Button>
          <AsyncButton
            icon={<Upload aria-hidden className="button__icon" />}
            loading={spriteUploadPending}
            onClick={() => setSpritePickerOpen(true)}
            variant="primary"
          >
            {t("character.sprite.uploadImages")}
          </AsyncButton>
        </div>
      </div>
      <PathPickerDialog
        acceptedExtensions={VISUAL_MEDIA_EXTENSIONS}
        multiple
        mode="file"
        onClose={() => setSpritePickerOpen(false)}
        onSelect={(path) => onSpriteUpload([path])}
        onSelectMany={onSpriteUpload}
        open={spritePickerOpen}
        title={t("character.sprite.selectImages")}
      />
      <div className="asset-editor">
        {showOutfitGroupBar ? (
          <div className="sprite-group-panel">
            <div className="sprite-group-bar">
              <div className="sprite-group-tabs" role="tablist">
                <button
                  aria-selected={activeSpriteGroup === "__all__"}
                  className="sprite-group-tab"
                  onClick={() => handleSelectGroupTab("__all__")}
                  role="tab"
                  type="button"
                >
                  {t("spriteGroup.all", { count: draft.sprites.length })}
                </button>
                {spriteGroups.map((group) => (
                  <button
                    aria-selected={activeSpriteGroup === group}
                    className="sprite-group-tab"
                    key={group}
                    onClick={() => handleSelectGroupTab(group)}
                    role="tab"
                    type="button"
                  >
                    <span>{t("spriteGroup.tabCount", { count: groupCounts[group] ?? 0, name: group })}</span>
                    {group === defaultGroup ? (
                      <span className="sprite-group-tab__badge">{t("spriteGroup.defaultBadge")}</span>
                    ) : null}
                  </button>
                ))}
              </div>
              <div className="sprite-group-actions">
                <Switch
                  checked={fallbackToDefault}
                  disabled={spriteGroupsPending}
                  id="sprite-group-fallback-default"
                  onChange={(event) => onApplySpriteGroups?.({ fallbackToDefaultGroup: event.currentTarget.checked })}
                >
                  {t("spriteGroup.fallbackToDefault")}
                </Switch>
                {onOpenSmartGroup ? (
                  <Button
                    disabled={!isSavedCharacter || !draft.sprites.length}
                    icon={<Sparkles aria-hidden className="button__icon" />}
                    onClick={onOpenSmartGroup}
                    variant="ghost"
                  >
                    {t("spriteGroup.autoGroup")}
                  </Button>
                ) : null}
                <Button
                  disabled={!draft.sprites.length}
                  icon={<CheckSquare aria-hidden className="button__icon" />}
                  onClick={() => {
                    setBatchSelectMode((current) => !current);
                    setCheckedIndices(new Set());
                  }}
                  variant={batchSelectMode ? "default" : "ghost"}
                >
                  {t(batchSelectMode ? "spriteGroup.batchExitSelectMode" : "spriteGroup.batchSelectMode")}
                </Button>
                <Button
                  icon={<FolderPlus aria-hidden className="button__icon" />}
                  onClick={() => setCreatingGroupOpen((current) => !current)}
                  variant="default"
                >
                  {t("spriteGroup.newGroup")}
                </Button>
              </div>
            </div>

            {creatingGroupOpen ? (
              <div className="sprite-group-inline-editor">
                <TextInput
                  aria-label={t("spriteGroup.newGroupPlaceholder")}
                  onChange={(event) => setNewGroupInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      handleCreateGroup();
                    }
                  }}
                  placeholder={t("spriteGroup.newGroupPlaceholder")}
                  value={newGroupInput}
                />
                <AsyncButton
                  disabled={!newGroupInput.trim()}
                  loading={spriteGroupsPending}
                  onClick={handleCreateGroup}
                  variant="primary"
                >
                  {t("spriteGroup.create")}
                </AsyncButton>
              </div>
            ) : null}

            {activeSpriteGroup !== "__all__" ? (
              <div className="sprite-group-manage-row">
                {activeSpriteGroup !== defaultGroup ? (
                  <AsyncButton
                    icon={<Star aria-hidden className="button__icon" />}
                    loading={spriteGroupsPending}
                    onClick={() => onApplySpriteGroups?.({ defaultSpriteGroup: activeSpriteGroup })}
                    variant="ghost"
                  >
                    {t("spriteGroup.setDefault")}
                  </AsyncButton>
                ) : null}
                {activeSpriteGroup !== DEFAULT_SPRITE_GROUP ? (
                  <>
                    <Button
                      icon={<Pencil aria-hidden className="button__icon" />}
                      onClick={() => {
                        setRenamingGroup(activeSpriteGroup);
                        setRenameInput(activeSpriteGroup);
                      }}
                      variant="ghost"
                    >
                      {t("spriteGroup.rename")}
                    </Button>
                    <Button
                      icon={<Trash2 aria-hidden className="button__icon" />}
                      onClick={() => setPendingDeleteGroup(activeSpriteGroup)}
                      variant="danger"
                    >
                      {t("spriteGroup.delete")}
                    </Button>
                  </>
                ) : null}
                {renamingGroup === activeSpriteGroup ? (
                  <div className="sprite-group-inline-editor">
                    <TextInput
                      aria-label={t("spriteGroup.renamePrompt")}
                      onChange={(event) => setRenameInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          handleConfirmRename();
                        }
                      }}
                      placeholder={t("spriteGroup.renamePrompt")}
                      value={renameInput}
                    />
                    <AsyncButton
                      disabled={!renameInput.trim() || renameInput.trim() === activeSpriteGroup}
                      loading={spriteGroupsPending}
                      onClick={handleConfirmRename}
                      variant="primary"
                    >
                      {t("common.save")}
                    </AsyncButton>
                  </div>
                ) : null}
              </div>
            ) : null}

            {batchSelectMode && draft.sprites.length > 0 ? (
              <div className="sprite-batch-bar">
                <div className="sprite-batch-bar__selection">
                  <Button onClick={handleSelectVisible} variant="ghost">
                    {t("spriteGroup.batchSelectVisible")}
                  </Button>
                  <Button
                    disabled={checkedIndices.size === 0}
                    onClick={() => setCheckedIndices(new Set())}
                    variant="ghost"
                  >
                    {t("spriteGroup.batchClearSelection")}
                  </Button>
                  <span className="inline-status">
                    {t("spriteGroup.batchSelectedCount", { count: checkedIndices.size })}
                  </span>
                </div>
                <div className="sprite-batch-bar__move">
                  <Select
                    aria-label={t("spriteGroup.batchMoveChoose")}
                    onChange={(event) => setBatchTargetGroup(event.target.value)}
                    value={batchTargetGroup}
                  >
                    <option value="">{t("spriteGroup.batchMoveChoose")}</option>
                    {spriteGroups.map((group) => (
                      <option key={group} value={group}>
                        {group}
                      </option>
                    ))}
                  </Select>
                  <AsyncButton
                    disabled={checkedIndices.size === 0 || !batchTargetGroup}
                    loading={spriteGroupsPending}
                    onClick={handleBatchMove}
                    variant="primary"
                  >
                    {t("spriteGroup.batchMoveTo")}
                  </AsyncButton>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {!draft.sprites.length ? <EmptyState title={t("character.sprite.empty")} /> : null}
        {selectedSprite ? (
          <div className="asset-gallery-layout asset-gallery-layout--character">
            {visibleGalleryItems.length > 0 ? (
              <ImageAssetGallery
                checkedIndices={batchSelectMode ? checkedIndices : undefined}
                items={visibleGalleryItems}
                onSelect={onSelectSprite}
                onToggleCheck={batchSelectMode ? toggleCheckedSprite : undefined}
                selectedIndex={selectedSpriteIndex}
              />
            ) : (
              <EmptyState title={t("character.sprite.empty")} />
            )}
            <aside className="asset-inspector">
              <div className="asset-inspector__preview asset-inspector__preview--character">
                {selectedSprite.path ? (
                  <VisualMedia alt="" errorMessage={t("visualMedia.videoError")} src={fileUrl(selectedSprite.path)} />
                ) : (
                  <ImageIcon aria-hidden className="asset-inspector__fallback" />
                )}
              </div>
              {showOutfitGroupBar ? (
                <label className="field-row field-row--stack">
                  <span className="field-row__label">{t("spriteGroup.assignLabel")}</span>
                  <span className="field-row__control">
                    <Select
                      aria-label={t("spriteGroup.assignLabel")}
                      disabled={spriteGroupsPending}
                      onChange={(event) =>
                        onApplySpriteGroups?.({
                          assignments: { [String(selectedSpriteIndex)]: event.target.value },
                        })
                      }
                      value={selectedSpriteGroup}
                    >
                      {spriteGroups.map((group) => (
                        <option key={group} value={group}>
                          {group}
                        </option>
                      ))}
                    </Select>
                  </span>
                </label>
              ) : null}
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.tag")}</span>
                <span className="field-row__control">
                  <div className="input-group sprite-tag-row">
                    <TextInput
                      className="sprite-tag-input"
                      onChange={(event) => onSpriteTagChange(event.target.value)}
                      value={selectedSpriteTag}
                    />
                    <AsyncButton loading={emotionTagsPending} onClick={onSaveTags} variant="default">
                      {t("character.sprite.saveTags")}
                    </AsyncButton>
                  </div>
                </span>
              </label>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.path")}</span>
                <span className="field-row__control">
                  <PathDisplay className="path-display--input" path={selectedSprite.path} />
                </span>
              </label>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.voicePath")}</span>
                <span className="field-row__control">
                  <PathDisplay className="path-display--input" path={selectedSprite.voice_path ?? ""} />
                  {selectedSprite.voice_path ? (
                    <AudioPlayer
                      className="sprite-voice-player"
                      label={t("character.sprite.voicePath")}
                      preload="metadata"
                      src={fileUrl(selectedSprite.voice_path)}
                    />
                  ) : null}
                </span>
              </label>
              <div className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.voiceType")}</span>
                <span className="field-row__control">
                  <SegmentedRadio
                    ariaLabel={t("character.sprite.voiceType")}
                    className="voice-type-selector"
                    name="voiceType"
                    onChange={onSpriteVoiceTypeChange}
                    options={[
                      { label: t("character.sprite.voiceTypeReference"), value: "reference" },
                      { label: t("character.sprite.voiceTypePreset"), value: "preset" },
                      { label: t("character.sprite.voiceTypeFallback"), value: "fallback" },
                    ]}
                    value={voiceType}
                  />
                  <p className="field-row__hint field-row__hint--voice-type">{t(voiceTypeHintKey)}</p>
                </span>
              </div>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.voiceUploadPath")}</span>
                <span className="field-row__control">
                  <FilePicker
                    acceptedExtensions={
                      voiceType === "reference" ? [".wav"] : [".flac", ".m4a", ".mp3", ".ogg", ".wav"]
                    }
                    onPathChange={onPendingVoicePathChange}
                    pickLabel={t("common.chooseFile")}
                    pickerTitle={t("character.sprite.voiceUploadPath")}
                    value={pendingVoicePath}
                  />
                </span>
              </label>
              {voiceType !== "fallback" ? (
                <label className="field-row field-row--stack">
                  <span className="field-row__label">{t("character.sprite.voiceText")}</span>
                  <span className="field-row__control">
                    <div className="input-group sprite-tag-row">
                      <TextInput
                        className="sprite-tag-input"
                        onBlur={(event) => onSpriteVoiceTextBlur(event.currentTarget.value)}
                        onChange={(event) => onSpriteVoiceTextChange(event.target.value)}
                        value={selectedSprite.voice_text ?? ""}
                      />
                      <AsyncButton
                        onClick={() => onSpriteVoiceTextBlur(selectedSprite?.voice_text ?? "")}
                        variant="default"
                      >
                        {t("character.sprite.saveVoiceText")}
                      </AsyncButton>
                    </div>
                  </span>
                </label>
              ) : null}
              <div className="asset-inspector__actions">
                <AsyncButton
                  icon={<Trash2 aria-hidden className="button__icon" />}
                  loading={spriteDeletePending}
                  onClick={onSpriteDelete}
                  variant="danger"
                >
                  {t("common.remove")}
                </AsyncButton>
                <AsyncButton loading={voiceDeletePending} onClick={onSpriteVoiceDelete} variant="ghost">
                  {t("character.sprite.deleteVoice")}
                </AsyncButton>
                <AsyncButton loading={voiceUploadPending} onClick={onSpriteVoiceUpload} variant="default">
                  {t("character.sprite.uploadVoice")}
                </AsyncButton>
              </div>
            </aside>
          </div>
        ) : null}
      </div>
      <div className="inline-status">
        <Volume2 aria-hidden className="button__icon" />
        {t("character.sprite.voiceHint")}
      </div>
      <AlertDialog
        body={t("spriteGroup.deleteConfirmBody", { group: pendingDeleteGroup ?? "" })}
        cancelLabel={t("common.cancel")}
        closeLabel={t("common.close")}
        confirmLabel={t("spriteGroup.delete")}
        onCancel={() => setPendingDeleteGroup(null)}
        onConfirm={handleConfirmDeleteGroup}
        open={Boolean(pendingDeleteGroup)}
        title={t("spriteGroup.delete")}
      />
    </section>
  );
}
