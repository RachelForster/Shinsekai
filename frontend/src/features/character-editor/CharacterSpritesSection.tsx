import type { WheelEventHandler } from "react";
import { Image as ImageIcon, Tags, Trash2, Upload, Volume2 } from "lucide-react";

import type { Character, Sprite } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import type { ImageAssetGalleryItem } from "../../shared/ui";
import {
  AsyncButton,
  AudioPlayer,
  Button,
  EmptyState,
  FilePicker,
  ImageAssetGallery,
  NumberInput,
  PathDisplay,
  TextInput,
} from "../../shared/ui";
import {
  SPRITE_SCALE_MAX,
  SPRITE_SCALE_MIN,
  SPRITE_SCALE_STEP,
  type CharacterFieldChange,
} from "./characterEditorUtils";

interface CharacterSpritesSectionProps {
  draft: Character;
  emotionTagsPending: boolean;
  id?: string;
  onClearSprites: () => void;
  onOpenBulkTags: () => void;
  onPendingSpritePathsChange: (paths: string[]) => void;
  onPendingVoicePathChange: (path: string) => void;
  onSaveScale: () => void;
  onSaveTags: () => void;
  onScaleChange: CharacterFieldChange;
  onScaleWheel: WheelEventHandler<HTMLDivElement>;
  onSelectSprite: (index: number) => void;
  onSpriteDelete: () => void;
  onSpriteTagChange: (value: string) => void;
  onSpriteUpload: () => void;
  onSpriteVoiceDelete: () => void;
  onSpriteVoiceTextBlur: (text: string) => void;
  onSpriteVoiceTextChange: (value: string) => void;
  onSpriteVoiceUpload: () => void;
  pendingSpritePaths: string[];
  pendingVoicePath: string;
  selectedSprite?: Sprite;
  selectedSpriteIndex: number;
  selectedSpriteTag: string;
  spriteDeletePending: boolean;
  spriteGalleryItems: ImageAssetGalleryItem[];
  spriteScalePending: boolean;
  spriteUploadPending: boolean;
  voiceDeletePending: boolean;
  voiceUploadPending: boolean;
}

export function CharacterSpritesSection({
  draft,
  emotionTagsPending,
  id,
  onClearSprites,
  onOpenBulkTags,
  onPendingSpritePathsChange,
  onPendingVoicePathChange,
  onSaveScale,
  onSaveTags,
  onScaleChange,
  onScaleWheel,
  onSelectSprite,
  onSpriteDelete,
  onSpriteTagChange,
  onSpriteUpload,
  onSpriteVoiceDelete,
  onSpriteVoiceTextBlur,
  onSpriteVoiceTextChange,
  onSpriteVoiceUpload,
  pendingSpritePaths,
  pendingVoicePath,
  selectedSprite,
  selectedSpriteIndex,
  selectedSpriteTag,
  spriteDeletePending,
  spriteGalleryItems,
  spriteScalePending,
  spriteUploadPending,
  voiceDeletePending,
  voiceUploadPending,
}: CharacterSpritesSectionProps) {
  const { t } = useI18n();

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("character.section.sprites")}</h2>
        <div className="page__actions">
          <AsyncButton
            icon={<Upload aria-hidden className="button__icon" />}
            loading={spriteUploadPending}
            onClick={onSpriteUpload}
            variant="ghost"
          >
            {t("character.sprite.uploadImages")}
          </AsyncButton>
          <Button
            disabled={!draft.sprites.length}
            icon={<Tags aria-hidden className="button__icon" />}
            onClick={onOpenBulkTags}
            variant="ghost"
          >
            {t("character.sprite.batchTags")}
          </Button>
          <Button icon={<Trash2 aria-hidden className="button__icon" />} onClick={onClearSprites} variant="ghost">
            {t("character.sprite.clear")}
          </Button>
        </div>
      </div>
      <div className="asset-editor">
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("character.sprite.selectImages")}</span>
          <span className="field-row__control">
            <FilePicker
              acceptedExtensions={[".gif", ".jpeg", ".jpg", ".png", ".webp"]}
              multiple
              onPathsChange={(paths) => {
                if (paths.length) {
                  onPendingSpritePathsChange(paths);
                }
              }}
              pickLabel={t("common.chooseFile")}
              pickerTitle={t("character.sprite.selectImages")}
              value={
                pendingSpritePaths.length
                  ? t("character.sprite.selectedFiles", { count: pendingSpritePaths.length })
                  : ""
              }
            />
          </span>
        </label>
        <label className="field-row field-row--stack">
          <span className="field-row__label">{t("character.field.spriteScale")}</span>
          <span className="field-row__control">
            <div className="input-group character-scale-control" onWheel={onScaleWheel}>
              <NumberInput
                max={SPRITE_SCALE_MAX}
                min={SPRITE_SCALE_MIN}
                onChange={(event) => onScaleChange("sprite_scale", Number(event.target.value))}
                step={SPRITE_SCALE_STEP}
                value={draft.sprite_scale}
              />
              <AsyncButton loading={spriteScalePending} onClick={onSaveScale}>
                {t("character.sprite.saveScale")}
              </AsyncButton>
            </div>
          </span>
        </label>
        {!draft.sprites.length ? <EmptyState title={t("character.sprite.empty")} /> : null}
        {selectedSprite ? (
          <div className="asset-gallery-layout asset-gallery-layout--character">
            <ImageAssetGallery
              items={spriteGalleryItems}
              onSelect={onSelectSprite}
              selectedIndex={selectedSpriteIndex}
            />
            <aside className="asset-inspector">
              <div className="asset-inspector__preview asset-inspector__preview--character">
                {selectedSprite.path ? (
                  <img alt="" decoding="async" src={fileUrl(selectedSprite.path)} />
                ) : (
                  <ImageIcon aria-hidden className="asset-inspector__fallback" />
                )}
              </div>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.tag")}</span>
                <span className="field-row__control">
                  <div className="input-group sprite-tag-row">
                    <TextInput
                      className="sprite-tag-input"
                      onChange={(event) => onSpriteTagChange(event.target.value)}
                      value={selectedSpriteTag}
                    />
                    <AsyncButton loading={emotionTagsPending} onClick={onSaveTags} variant="ghost">
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
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.voiceUploadPath")}</span>
                <span className="field-row__control">
                  <FilePicker
                    acceptedExtensions={[".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
                    onPathChange={onPendingVoicePathChange}
                    pickLabel={t("common.chooseFile")}
                    pickerTitle={t("character.sprite.voiceUploadPath")}
                    value={pendingVoicePath}
                  />
                </span>
              </label>
              <label className="field-row field-row--stack">
                <span className="field-row__label">{t("character.sprite.voiceText")}</span>
                <span className="field-row__control">
                  <TextInput
                    onBlur={(event) => onSpriteVoiceTextBlur(event.currentTarget.value)}
                    onChange={(event) => onSpriteVoiceTextChange(event.target.value)}
                    value={selectedSprite.voice_text ?? ""}
                  />
                </span>
              </label>
              <div className="asset-inspector__actions">
                <AsyncButton loading={voiceUploadPending} onClick={onSpriteVoiceUpload} variant="ghost">
                  {t("character.sprite.uploadVoice")}
                </AsyncButton>
                <AsyncButton loading={voiceDeletePending} onClick={onSpriteVoiceDelete} variant="ghost">
                  {t("character.sprite.deleteVoice")}
                </AsyncButton>
                <AsyncButton
                  icon={<Trash2 aria-hidden className="button__icon" />}
                  loading={spriteDeletePending}
                  onClick={onSpriteDelete}
                  variant="ghost"
                >
                  {t("common.remove")}
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
    </section>
  );
}
