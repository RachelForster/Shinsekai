import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { Select } from "../../shared/ui";

interface CharacterSelectionSectionProps {
  characters: Character[];
  isCreating: boolean;
  isLoading: boolean;
  onSelect: (name: string) => void;
  selectedName: string;
}

export function CharacterSelectionSection({
  characters,
  isCreating,
  isLoading,
  onSelect,
  selectedName,
}: CharacterSelectionSectionProps) {
  const { t } = useI18n();

  return (
    <section className="section character-page__file-box">
      <div className="form-grid">
        <label className="field-row">
          <span className="field-row__label">{t("character.row.current")}</span>
          <span className="field-row__control">
            <Select
              disabled={isLoading || !characters.length}
              onChange={(event) => onSelect(event.target.value)}
              value={isCreating ? "" : selectedName || characters[0]?.name || ""}
            >
              {isCreating ? <option value="">{t("common.new")}</option> : null}
              {characters.map((character) => (
                <option key={character.name} value={character.name}>
                  {character.name}
                </option>
              ))}
            </Select>
          </span>
        </label>
      </div>
    </section>
  );
}
