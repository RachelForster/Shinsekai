import { Palette, Trash2 } from "lucide-react";

import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { Button, handleIdentityKeyDown, InlineIdentityConfirm, TextArea, TextInput } from "../../shared/ui";
import { isSelfPersonaCharacter, type CharacterFieldChange } from "./characterEditorUtils";

interface CharacterBasicSectionProps {
  colorPickerValue: string;
  draft: Character;
  id?: string;
  identityConfirmDisabled?: boolean;
  identitySavingField?: "name" | "sprite_prefix" | null;
  nameDirty?: boolean;
  nameError: string;
  onCancelName?: () => void;
  onCancelSpritePrefix?: () => void;
  onChange: CharacterFieldChange;
  onColorInputRef: (element: HTMLInputElement | null) => void;
  onConfirmName?: () => void;
  onConfirmSpritePrefix?: () => void;
  onDelete: () => void;
  onPickColor: () => void;
  onPronunciationTextChange: (value: string) => void;
  pronunciationText: string;
  spritePrefixDirty?: boolean;
  spritePrefixError?: string;
}

export function CharacterBasicSection({
  colorPickerValue,
  draft,
  id,
  identityConfirmDisabled = false,
  identitySavingField = null,
  nameDirty = false,
  nameError,
  onCancelName,
  onCancelSpritePrefix,
  onChange,
  onColorInputRef,
  onConfirmName,
  onConfirmSpritePrefix,
  onDelete,
  onPickColor,
  onPronunciationTextChange,
  pronunciationText,
  spritePrefixDirty = false,
  spritePrefixError = "",
}: CharacterBasicSectionProps) {
  const { t } = useI18n();
  const lockedPersona = isSelfPersonaCharacter(draft);
  const nameFieldLabel = t("character.field.name");
  const spritePrefixLabel = t("character.field.spritePrefix");

  return (
    <section className="section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("character.section.basic")}</h2>
        {lockedPersona ? (
          <span className="character-builtin-badge">{t("character.selfPersona.badge")}</span>
        ) : (
          <Button icon={<Trash2 aria-hidden className="button__icon" />} onClick={onDelete} variant="danger">
            {t("common.delete")}
          </Button>
        )}
      </div>
      {lockedPersona ? (
        <div className="character-self-persona-banner" role="note">
          <strong>{t("character.selfPersona.bannerTitle")}</strong>
          <p>{t("character.selfPersona.bannerBody")}</p>
        </div>
      ) : null}
      <div className="form-grid form-grid--two">
        <div className="field-row">
          <label className="field-row__label" htmlFor="character-basic-name-input">
            {nameFieldLabel}
          </label>
          <span className="field-row__control">
            <div className="identity-field-group">
              <TextInput
                className={nameError ? "input--error" : ""}
                id="character-basic-name-input"
                onChange={(event) => onChange("name", event.target.value)}
                onKeyDown={(event) =>
                  handleIdentityKeyDown(event, {
                    canConfirm: !nameError && identitySavingField === null && !identityConfirmDisabled,
                    disabled: identitySavingField !== null,
                    isDirty: nameDirty,
                    onCancel: () => onCancelName?.(),
                    onConfirm: () => onConfirmName?.(),
                  })
                }
                value={draft.name}
              />
              <InlineIdentityConfirm
                confirmDisabled={Boolean(nameError) || identityConfirmDisabled}
                disabled={identitySavingField !== null && identitySavingField !== "name"}
                fieldLabel={nameFieldLabel}
                loading={identitySavingField === "name"}
                onCancel={() => onCancelName?.()}
                onConfirm={() => onConfirmName?.()}
                visible={nameDirty}
              />
            </div>
            {nameError ? <span className="field-error">{nameError}</span> : null}
          </span>
        </div>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.color")}</span>
          <span className="field-row__control">
            <div className="input-group character-color-control">
              <TextInput onChange={(event) => onChange("color", event.target.value)} value={draft.color} />
              <span aria-hidden className="swatch" style={{ background: draft.color }} />
              <Button icon={<Palette aria-hidden className="button__icon" />} onClick={onPickColor} variant="ghost">
                {t("character.action.pickColor")}
              </Button>
              <input
                className="visually-hidden"
                onChange={(event) => onChange("color", event.target.value)}
                ref={onColorInputRef}
                type="color"
                value={colorPickerValue}
              />
            </div>
          </span>
        </label>
        <div className="field-row">
          <label className="field-row__label" htmlFor="character-basic-prefix-input">
            {spritePrefixLabel}
          </label>
          <span className="field-row__control">
            <div className="identity-field-group">
              <TextInput
                className={spritePrefixError ? "input--error" : ""}
                disabled={lockedPersona}
                id="character-basic-prefix-input"
                onChange={(event) => onChange("sprite_prefix", event.target.value)}
                onKeyDown={
                  !lockedPersona
                    ? (event) =>
                        handleIdentityKeyDown(event, {
                          canConfirm: !spritePrefixError && identitySavingField === null && !identityConfirmDisabled,
                          disabled: identitySavingField !== null,
                          isDirty: spritePrefixDirty,
                          onCancel: () => onCancelSpritePrefix?.(),
                          onConfirm: () => onConfirmSpritePrefix?.(),
                        })
                    : undefined
                }
                readOnly={lockedPersona}
                value={draft.sprite_prefix}
              />
              {!lockedPersona ? (
                <InlineIdentityConfirm
                  confirmDisabled={Boolean(spritePrefixError) || identityConfirmDisabled}
                  disabled={identitySavingField !== null && identitySavingField !== "sprite_prefix"}
                  fieldLabel={spritePrefixLabel}
                  loading={identitySavingField === "sprite_prefix"}
                  onCancel={() => onCancelSpritePrefix?.()}
                  onConfirm={() => onConfirmSpritePrefix?.()}
                  visible={spritePrefixDirty}
                />
              ) : null}
            </div>
            {spritePrefixError ? <span className="field-error">{spritePrefixError}</span> : null}
            {lockedPersona ? (
              <span className="field-row__hint">{t("character.selfPersona.lockedFieldHint")}</span>
            ) : null}
          </span>
        </div>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.pronunciationMap")}</span>
          <span className="field-row__control">
            <TextArea
              onChange={(event) => onPronunciationTextChange(event.target.value)}
              placeholder={t("ops.character.pronunciationPlaceholder")}
              rows={4}
              value={pronunciationText}
            />
          </span>
        </label>
      </div>
    </section>
  );
}
