import { useEffect, useMemo, useState } from "react";
import { Crop, Sparkles, Tags, Trash2, Upload, Volume2 } from "lucide-react";

import type { Character, Sprite } from "../../entities/config/types";
import { VISUAL_MEDIA_EXTENSIONS } from "../../shared/assets/visualMedia";
import { useI18n } from "../../shared/i18n";
import type { SpriteVoiceType } from "../../shared/platform/types";
import type { ImageAssetGalleryItem } from "../../shared/ui";
import { AlertDialog, AsyncButton, Button, EmptyState, ImageAssetGallery, PathPickerDialog } from "../../shared/ui";
import { DEFAULT_SPRITE_GROUP, normalizeSpriteGroupName, resolveCharacterSpriteGroups } from "./characterEditorUtils";

import { CharacterSpriteGroups } from "./CharacterSpriteGroups";
import { CharacterSpriteInspector } from "./CharacterSpriteInspector";

export interface SpriteGroupsPatch {
  assignments?: Record<string, string>;
  defaultSpriteGroup?: string;
  deleteGroup?: string;
  fallbackToDefaultGroup?: boolean;
  spriteGroups?: string[];
}

export interface CharacterSpritesSectionProps {
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
  onSpriteVoiceProfileChange?: (id: string | null) => void;
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
  onSpriteVoiceProfileChange,
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
          <CharacterSpriteGroups
            activeSpriteGroup={activeSpriteGroup}
            draft={draft}
            spriteGroups={spriteGroups}
            groupCounts={groupCounts}
            defaultGroup={defaultGroup}
            fallbackToDefault={fallbackToDefault}
            spriteGroupsPending={spriteGroupsPending}
            onApplySpriteGroups={onApplySpriteGroups}
            onOpenSmartGroup={onOpenSmartGroup}
            isSavedCharacter={isSavedCharacter}
            batchSelectMode={batchSelectMode}
            setBatchSelectMode={setBatchSelectMode}
            setCheckedIndices={setCheckedIndices}
            setCreatingGroupOpen={setCreatingGroupOpen}
            creatingGroupOpen={creatingGroupOpen}
            newGroupInput={newGroupInput}
            setNewGroupInput={setNewGroupInput}
            handleSelectGroupTab={handleSelectGroupTab}
            handleCreateGroup={handleCreateGroup}
            setPendingDeleteGroup={setPendingDeleteGroup}
            renamingGroup={renamingGroup}
            setRenamingGroup={setRenamingGroup}
            renameInput={renameInput}
            setRenameInput={setRenameInput}
            handleConfirmRename={handleConfirmRename}
            handleSelectVisible={handleSelectVisible}
            checkedIndices={checkedIndices}
            batchTargetGroup={batchTargetGroup}
            setBatchTargetGroup={setBatchTargetGroup}
            handleBatchMove={handleBatchMove}
          />
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
            <CharacterSpriteInspector
              draft={draft}
              selectedSprite={selectedSprite}
              selectedSpriteIndex={selectedSpriteIndex}
              selectedSpriteTag={selectedSpriteTag}
              selectedSpriteGroup={selectedSpriteGroup}
              spriteGroups={spriteGroups}
              showOutfitGroupBar={showOutfitGroupBar}
              spriteGroupsPending={spriteGroupsPending}
              emotionTagsPending={emotionTagsPending}
              pendingVoicePath={pendingVoicePath}
              spriteDeletePending={spriteDeletePending}
              voiceDeletePending={voiceDeletePending}
              voiceUploadPending={voiceUploadPending}
              onApplySpriteGroups={onApplySpriteGroups}
              onSpriteTagChange={onSpriteTagChange}
              onSaveTags={onSaveTags}
              onSpriteVoiceProfileChange={onSpriteVoiceProfileChange}
              onSpriteVoiceTypeChange={onSpriteVoiceTypeChange}
              onPendingVoicePathChange={onPendingVoicePathChange}
              onSpriteVoiceTextBlur={onSpriteVoiceTextBlur}
              onSpriteVoiceTextChange={onSpriteVoiceTextChange}
              onSpriteDelete={onSpriteDelete}
              onSpriteVoiceDelete={onSpriteVoiceDelete}
              onSpriteVoiceUpload={onSpriteVoiceUpload}
            />
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
