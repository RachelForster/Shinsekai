import { Users } from "lucide-react";
import type { Character } from "../../shared/platform/types";
import { useI18n } from "../../shared/i18n";
import { Button } from "../../shared/ui";
import { getCharacterChipStyle } from "./templateFlow";
import "./CharacterPicker.css";

export function CharacterPicker({
  characters,
  selected,
  onChange,
  disabled = false,
}: {
  characters: Character[];
  selected: string[];
  onChange: (names: string[]) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const names = new Set(selected);
  return (
    <div className="template-character-picker">
      <div className="template-character-picker__header">
        <span className="template-character-picker__label">{t("template.field.characters")}</span>
        <Button
          disabled={disabled || !characters.length}
          icon={<Users aria-hidden className="button__icon" />}
          onClick={() => onChange(characters.map((character) => character.name))}
          variant="ghost"
        >
          {t("template.action.selectAllCharacters")}
        </Button>
      </div>
      <div aria-label={t("template.field.characters")} className="template-character-grid" role="group">
        {characters.map((character) => (
          <button
            key={character.name}
            aria-pressed={names.has(character.name)}
            className={`template-character-card${names.has(character.name) ? " template-character-card--selected" : ""}`}
            disabled={disabled}
            style={getCharacterChipStyle(character.color ?? "")}
            title={character.name}
            type="button"
            onClick={() =>
              onChange(
                names.has(character.name)
                  ? selected.filter((name) => name !== character.name)
                  : [...selected, character.name],
              )
            }
          >
            <span aria-hidden className="template-character-card__dot" />
            <span className="template-character-card__name">{character.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
