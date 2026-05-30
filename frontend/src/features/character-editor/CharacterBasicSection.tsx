import { Palette, Trash2 } from "lucide-react";

import type { Character } from "../../entities/config/types";
import { DEFAULT_CHARACTER_COLOR } from "../../shared/constants";
import { useI18n } from "../../shared/i18n";
import { Button, TextArea, TextInput } from "../../shared/ui";
import type { CharacterFieldChange } from "./characterEditorUtils";

interface CharacterBasicSectionProps {
  colorPickerValue: string;
  draft: Character;
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
  nameError,
  onChange,
  onColorInputRef,
  onDelete,
  onPickColor,
  onPronunciationTextChange,
  pronunciationText,
}: CharacterBasicSectionProps) {
  const { t } = useI18n();
  const swatchColor = draft.color || DEFAULT_CHARACTER_COLOR;

  return (
    <section className="section">
      <div className="section__header">
        <h2 className="section__title">{t("character.section.basic")}</h2>
        <Button icon={<Trash2 aria-hidden className="button__icon" />} onClick={onDelete} variant="danger">
          {t("common.delete")}
        </Button>
      </div>
      <div className="form-grid form-grid--two">
        <label className="field-row">
          <span className="field-row__label">{t("character.field.name")}</span>
          <span className="field-row__control">
            <TextInput
              className={nameError ? "input--error" : ""}
              onChange={(event) => onChange("name", event.target.value)}
              value={draft.name}
            />
            {nameError ? <span className="field-error">{nameError}</span> : null}
          </span>
        </label>
        <label className="field-row">
          <span className="field-row__label">{t("character.field.color")}</span>
          <span className="field-row__control">
            <div className="input-group character-color-control">
              <TextInput onChange={(event) => onChange("color", event.target.value)} value={draft.color} />
              <span aria-hidden className="swatch" style={{ background: swatchColor }} />
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
              onChange={(event) => onChange("sprite_prefix", event.target.value)}
              value={draft.sprite_prefix}
            />
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
