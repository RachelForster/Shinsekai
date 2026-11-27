import { Image as ImageIcon, Trash2 } from "lucide-react";
import type { Character, Sprite } from "../../entities/config/types";
import { fileUrl } from "../../entities/files/repository";
import { useI18n } from "../../shared/i18n";
import {
  AsyncButton,
  AudioPlayer,
  FilePicker,
  PathDisplay,
  SegmentedRadio,
  Select,
  TextInput,
  VisualMedia,
} from "../../shared/ui";
import type { CharacterSpritesSectionProps } from "./CharacterSpritesSection";

interface Props {
  draft: Character;
  selectedSprite: Sprite;
  selectedSpriteIndex: number;
  selectedSpriteTag: string;
  selectedSpriteGroup: string;
  spriteGroups: string[];
  showOutfitGroupBar: boolean;
  spriteGroupsPending: boolean;
  emotionTagsPending: boolean;
  pendingVoicePath: string;
  spriteDeletePending: boolean;
  voiceDeletePending: boolean;
  voiceUploadPending: boolean;
  onApplySpriteGroups: CharacterSpritesSectionProps["onApplySpriteGroups"];
  onSpriteTagChange: CharacterSpritesSectionProps["onSpriteTagChange"];
  onSaveTags: CharacterSpritesSectionProps["onSaveTags"];
  onSpriteVoiceProfileChange: CharacterSpritesSectionProps["onSpriteVoiceProfileChange"];
  onSpriteVoiceTypeChange: CharacterSpritesSectionProps["onSpriteVoiceTypeChange"];
  onPendingVoicePathChange: CharacterSpritesSectionProps["onPendingVoicePathChange"];
  onSpriteVoiceTextBlur: CharacterSpritesSectionProps["onSpriteVoiceTextBlur"];
  onSpriteVoiceTextChange: CharacterSpritesSectionProps["onSpriteVoiceTextChange"];
  onSpriteDelete: CharacterSpritesSectionProps["onSpriteDelete"];
  onSpriteVoiceDelete: CharacterSpritesSectionProps["onSpriteVoiceDelete"];
  onSpriteVoiceUpload: CharacterSpritesSectionProps["onSpriteVoiceUpload"];
}

export function CharacterSpriteInspector({
  draft,
  selectedSprite,
  selectedSpriteIndex,
  selectedSpriteTag,
  selectedSpriteGroup,
  spriteGroups,
  showOutfitGroupBar,
  spriteGroupsPending,
  emotionTagsPending,
  pendingVoicePath,
  spriteDeletePending,
  voiceDeletePending,
  voiceUploadPending,
  onApplySpriteGroups,
  onSpriteTagChange,
  onSaveTags,
  onSpriteVoiceProfileChange,
  onSpriteVoiceTypeChange,
  onPendingVoicePathChange,
  onSpriteVoiceTextBlur,
  onSpriteVoiceTextChange,
  onSpriteDelete,
  onSpriteVoiceDelete,
  onSpriteVoiceUpload,
}: Props) {
  const { t } = useI18n();
  const voiceType = selectedSprite?.voice_type ?? "fallback";
  const voiceTypeHintKey =
    voiceType === "reference"
      ? "character.sprite.voiceRefHint"
      : voiceType === "preset"
        ? "character.sprite.voicePresetHint"
        : "character.sprite.voiceFallbackHint";
  return (
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
      {onSpriteVoiceProfileChange && Object.keys(draft.voice_profiles ?? {}).length > 0 && (
        <label className="field-row">
          {t("character.voice.profile")}
          <span className="field-row__control">
            <Select
              aria-label={t("character.voice.profile")}
              value={
                draft.voice_profiles?.[selectedSprite.voice_profile_id ?? ""]
                  ? (selectedSprite.voice_profile_id ?? "")
                  : ""
              }
              onChange={(event) => onSpriteVoiceProfileChange(event.target.value || null)}
            >
              <option value="">
                {draft.default_voice_name?.trim()
                  ? t("character.voice.namedDefaultProfile", { name: draft.default_voice_name.trim() })
                  : t("character.voice.useDefaultProfile")}
              </option>
              {Object.entries(draft.voice_profiles ?? {}).map(([profileId, voice]) => (
                <option key={profileId} value={profileId}>
                  {voice.name.trim() || t("character.voice.unnamedProfile")}
                </option>
              ))}
            </Select>
          </span>
        </label>
      )}
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
            acceptedExtensions={voiceType === "reference" ? [".wav"] : [".flac", ".m4a", ".mp3", ".ogg", ".wav"]}
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
              <AsyncButton onClick={() => onSpriteVoiceTextBlur(selectedSprite?.voice_text ?? "")} variant="default">
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
  );
}
