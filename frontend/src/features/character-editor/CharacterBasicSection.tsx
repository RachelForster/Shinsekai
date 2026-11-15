import { Palette, Trash2 } from "lucide-react";

import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { Button, TextArea, TextInput } from "../../shared/ui";
import { isSelfPersonaCharacter, type CharacterFieldChange } from "./characterEditorUtils";

interface CharacterBasicSectionProps {
  colorPickerValue: string;
  draft: Character;
  id?: string;
  nameError: string;
  onChange: CharacterFieldChange;
  onColorInputRef: (element: HTMLInputElement | null) => void;
  onDelete: () => void;
  onPickColor: () => void;
  onPronunciationTextChange: (value: string) => void;
  pronunciationText: string;
}

export function CharacterBasicSection({
  colorPickerValue,
  draft,
  id,
  nameError,
  onChange,
  onColorInputRef,
  onDelete,
  onPickColor,
  onPronunciationTextChange,
  pronunciationText,
}: CharacterBasicSectionProps) {
  const { t } = useI18n();
  const lockedPersona = isSelfPersonaCharacter(draft);

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
        <label className="field-row">
          <span className="field-row__label">{t("character.field.name")}</span>
          <span className="field-row__control">
            <TextInput
              className={nameError ? "input--error" : ""}
              disabled={lockedPersona}
              onChange={(event) => onChange("name", event.target.value)}
              readOnly={lockedPersona}
              value={draft.name}
            />
            {lockedPersona ? <span className="field-row__hint">{t("character.selfPersona.lockedFieldHint")}</span> : null}
            {nameError ? <span className="field-error">{nameError}</span> : null}
          </span>
        </label>
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
        <label className="field-row">
          <span className="field-row__label">{t("character.field.spritePrefix")}</span>
          <span className="field-row__control">
            <TextInput
              disabled={lockedPersona}
              onChange={(event) => onChange("sprite_prefix", event.target.value)}
              readOnly={lockedPersona}
              value={draft.sprite_prefix}
            />
            {lockedPersona ? <span className="field-row__hint">{t("character.selfPersona.lockedFieldHint")}</span> : null}
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.pronunciationMap")}</span>
          <span className="field-row__control">
            <TextArea
              onChange={(event) => onPronunciationTextChange(event.target.value)}
              placeholder="名前=なまえ"
              rows={4}
              value={pronunciationText}
            />
          </span>
        </label>
      </div>
    </section>
  );
}
