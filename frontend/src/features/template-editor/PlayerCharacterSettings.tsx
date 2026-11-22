import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Crop, Upload } from "lucide-react";

import { charactersQueryKey, saveCharacter, uploadCharacterSprites } from "../../entities/character/repository";
import { tagContents } from "../../shared/assets/assetText";
import { VISUAL_MEDIA_EXTENSIONS } from "../../shared/assets/visualMedia";
import { Portrait, applyPortraitCrop, resolveSpritePortraitCrop } from "../../shared/components/Portrait";
import { PortraitCropDialog } from "../../shared/components/PortraitCropDialog";
import { useI18n } from "../../shared/i18n";
import { getCharacterDisplayName, SELF_PERSONA_NAME } from "../../shared/playerCharacterOptions";
import type { Character } from "../../shared/platform/types";
import { AsyncButton, Button, Dialog, PathPickerDialog, Select, Switch } from "../../shared/ui";
import "./PlayerCharacterSettings.css";

export { applyPortraitCrop };

function clampPortraitSpriteIndex(value: number | undefined, spriteCount: number): number {
  if (spriteCount <= 0) {
    return 0;
  }
  const parsed = Number.isFinite(value) ? Number(value) : 0;
  return Math.min(Math.max(0, Math.trunc(parsed)), spriteCount - 1);
}

export function PlayerCharacterFields({
  characters,
  selected,
  onSelect,
  readSpeech,
  onReadSpeech,
  allowDialogue,
  onAllowDialogue,
  disabled = false,
}: {
  characters: Character[];
  selected: string;
  onSelect: (name: string) => void;
  readSpeech: boolean;
  onReadSpeech: (enabled: boolean) => void;
  allowDialogue: boolean;
  onAllowDialogue: (enabled: boolean) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const selectId = useId();
  const avatarSelectId = useId();
  const allowDialogueId = useId();
  const readSpeechId = useId();
  const [cropOpen, setCropOpen] = useState(false);
  const [uploadPickerOpen, setUploadPickerOpen] = useState(false);
  const [avatarSavedNotice, setAvatarSavedNotice] = useState(false);
  const queryClient = useQueryClient();
  const character = characters.find((item) => item.name === selected);
  const sprites = character?.sprites ?? [];
  const activeSpriteIndex = clampPortraitSpriteIndex(character?.portrait_sprite_index, sprites.length);
  const activeSprite = sprites[activeSpriteIndex];
  const activeCrop = resolveSpritePortraitCrop(character, activeSpriteIndex);
  const spriteTags = character ? tagContents(character.emotion_tags ?? "", sprites.length) : [];

  const updateCatalogCharacter = (saved: Character) => {
    queryClient.setQueryData<Character[]>(charactersQueryKey, (current = []) => {
      const exists = current.some((item) => item.name === saved.name);
      return exists ? current.map((item) => (item.name === saved.name ? saved : item)) : [...current, saved];
    });
    void queryClient.invalidateQueries({ queryKey: charactersQueryKey });
  };

  const save = useMutation({
    mutationFn: (nextCharacter: Character) => saveCharacter(nextCharacter, nextCharacter.name),
    onSuccess: (saved) => {
      updateCatalogCharacter(saved);
      setAvatarSavedNotice(true);
      setCropOpen(false);
    },
  });

  const selectSpriteMutation = useMutation({
    mutationFn: (nextIndex: number) => {
      if (!character) {
        throw new Error("No character selected");
      }
      return saveCharacter({ ...character, portrait_sprite_index: nextIndex }, character.name);
    },
    onSuccess: (saved) => {
      updateCatalogCharacter(saved);
      setAvatarSavedNotice(true);
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (paths: string[]) => {
      if (!character || !paths.length) {
        throw new Error("No image selected");
      }
      const ensured =
        character.name === SELF_PERSONA_NAME && !sprites.length
          ? await saveCharacter(
              { ...character, sprite_prefix: character.sprite_prefix || "__self__" },
              character.name,
            ).catch(() => character)
          : character;
      const uploaded = await uploadCharacterSprites({
        emotionTags: ensured.emotion_tags || "",
        name: ensured.name,
        paths,
      });
      const uploadedIndex = Math.max(0, (uploaded.sprites?.length ?? 1) - 1);
      if (uploadedIndex !== (uploaded.portrait_sprite_index ?? 0)) {
        return saveCharacter({ ...uploaded, portrait_sprite_index: uploadedIndex }, uploaded.name);
      }
      return uploaded;
    },
    onSuccess: (saved) => {
      updateCatalogCharacter(saved);
      setAvatarSavedNotice(true);
    },
  });

  const busy = disabled || save.isPending || selectSpriteMutation.isPending || uploadMutation.isPending;
  const actionError =
    (uploadMutation.isError && String(uploadMutation.error)) ||
    (selectSpriteMutation.isError && String(selectSpriteMutation.error)) ||
    "";

  return (
    <>
      <div className="player-character-fields">
        <label className="player-character-fields__select-field" htmlFor={selectId}>
          <span className="player-character-fields__label">{t("player.select")}</span>
          <Select
            aria-label={t("player.select")}
            disabled={busy}
            id={selectId}
            onChange={(event) => {
              setAvatarSavedNotice(false);
              onSelect(event.target.value);
            }}
            value={character ? selected : ""}
          >
            <option value="">{t("player.none")}</option>
            {characters.map((item) => (
              <option key={item.name} value={item.name}>
                {getCharacterDisplayName(item)}
              </option>
            ))}
          </Select>
        </label>

        {character ? (
          <>
            <div className="player-character-fields__avatar-card">
              <button
                aria-label={t("player.avatarLabel")}
                className="player-character-fields__portrait-btn"
                disabled={busy}
                onClick={() => {
                  setAvatarSavedNotice(false);
                  if (sprites.length > 0) {
                    save.reset();
                    setCropOpen(true);
                  } else {
                    uploadMutation.reset();
                    setUploadPickerOpen(true);
                  }
                }}
                title={t(sprites.length > 0 ? "player.adjust" : "player.uploadAvatar")}
                type="button"
              >
                <Portrait
                  crop={activeCrop}
                  name={getCharacterDisplayName(character)}
                  path={activeSprite?.path}
                  shape="square"
                  size="100%"
                />
              </button>

              <div className="player-character-fields__avatar-main">
                <p className="player-character-fields__hint">{t("player.hint")}</p>

                {sprites.length > 1 ? (
                  <div className="player-character-fields__sprite-row">
                    <label className="player-character-fields__label" htmlFor={avatarSelectId}>
                      {t("player.avatarLabel")}
                    </label>
                    <Select
                      aria-label={t("player.avatarLabel")}
                      disabled={busy}
                      id={avatarSelectId}
                      onChange={(event) => {
                        setAvatarSavedNotice(false);
                        selectSpriteMutation.reset();
                        selectSpriteMutation.mutate(Number(event.target.value));
                      }}
                      value={String(activeSpriteIndex)}
                    >
                      {sprites.map((sprite, spriteIndex) => {
                        const fileLabel = sprite.path.split(/[\\/]/).pop() || `${spriteIndex + 1}`;
                        const tagLabel = spriteTags[spriteIndex]?.trim();
                        return (
                          <option key={`${sprite.path}-${spriteIndex}`} value={String(spriteIndex)}>
                            {spriteIndex + 1} · {fileLabel}
                            {tagLabel ? ` (${tagLabel})` : ""}
                          </option>
                        );
                      })}
                    </Select>
                  </div>
                ) : sprites.length === 0 ? (
                  <p className="player-character-fields__hint">{t("player.noSpritesHint")}</p>
                ) : null}

                <div className="player-character-fields__avatar-actions">
                  <AsyncButton
                    disabled={busy}
                    icon={<Upload aria-hidden className="button__icon" />}
                    loading={uploadMutation.isPending}
                    onClick={() => {
                      setAvatarSavedNotice(false);
                      uploadMutation.reset();
                      setUploadPickerOpen(true);
                    }}
                    variant="ghost"
                  >
                    {t("player.uploadAvatar")}
                  </AsyncButton>
                  <Button
                    disabled={busy || !sprites.length}
                    icon={<Crop aria-hidden className="button__icon" />}
                    onClick={() => {
                      setAvatarSavedNotice(false);
                      save.reset();
                      setCropOpen(true);
                    }}
                    variant="ghost"
                  >
                    {t("player.adjust")}
                  </Button>
                </div>

                {avatarSavedNotice ? (
                  <p className="player-character-fields__status" role="status">
                    {t("player.avatarUploaded")}
                  </p>
                ) : null}
                {actionError ? (
                  <p className="field-error" role="alert">
                    {actionError}
                  </p>
                ) : null}
              </div>
            </div>

            <div className="player-character-fields__toggles">
              <div className="player-character-fields__option-row">
                <label className="player-character-fields__option-copy" htmlFor={allowDialogueId}>
                  <strong>{t("player.allowDialogue")}</strong>
                  <span>{t("player.allowDialogueHint")}</span>
                </label>
                <Switch
                  aria-label={t("player.allowDialogue")}
                  checked={allowDialogue}
                  disabled={disabled}
                  id={allowDialogueId}
                  onChange={(event) => onAllowDialogue(event.target.checked)}
                />
              </div>

              <div className="player-character-fields__option-row">
                <label className="player-character-fields__option-copy" htmlFor={readSpeechId}>
                  <strong>{t("player.readSpeech")}</strong>
                  <span>{t("player.speechHint")}</span>
                </label>
                <Switch
                  aria-label={t("player.readSpeech")}
                  checked={readSpeech}
                  disabled={disabled}
                  id={readSpeechId}
                  onChange={(event) => onReadSpeech(event.target.checked)}
                />
              </div>
            </div>
          </>
        ) : null}
      </div>

      <PathPickerDialog
        acceptedExtensions={VISUAL_MEDIA_EXTENSIONS}
        mode="file"
        onClose={() => setUploadPickerOpen(false)}
        onSelect={(path) => uploadMutation.mutate([path])}
        open={uploadPickerOpen}
        title={t("player.uploadAvatar")}
      />

      <PortraitCropDialog
        character={character ?? null}
        error={save.isError ? String(save.error) : undefined}
        initialSpriteIndex={activeSpriteIndex}
        onClose={() => setCropOpen(false)}
        onSave={(nextCharacter) => save.mutate(nextCharacter)}
        open={cropOpen}
        saveSelectedAsDefaultPortrait
        saving={save.isPending}
        title={t("player.adjust")}
      />
    </>
  );
}

export function PlayerCharacterSettings({
  characters,
  selected,
  onSelect,
  readSpeech,
  onReadSpeech,
  allowDialogue,
  onAllowDialogue,
  open,
  onClose,
}: {
  characters: Character[];
  selected: string;
  onSelect: (name: string) => void;
  readSpeech: boolean;
  onReadSpeech: (enabled: boolean) => void;
  allowDialogue: boolean;
  onAllowDialogue: (enabled: boolean) => void;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n();

  return (
    <Dialog
      closeLabel={t("common.close")}
      footer={
        <Button onClick={onClose} variant="primary">
          {t("common.confirm")}
        </Button>
      }
      onClose={onClose}
      open={open}
      title={t("player.select")}
    >
      <PlayerCharacterFields
        allowDialogue={allowDialogue}
        characters={characters}
        onAllowDialogue={onAllowDialogue}
        onReadSpeech={onReadSpeech}
        onSelect={onSelect}
        readSpeech={readSpeech}
        selected={selected}
      />
    </Dialog>
  );
}
