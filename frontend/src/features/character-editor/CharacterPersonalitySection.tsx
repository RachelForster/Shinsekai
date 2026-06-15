import { Languages, Sparkles } from "lucide-react";

import type { Character } from "../../entities/config/types";
import { useI18n } from "../../shared/i18n";
import { AsyncButton, TextArea } from "../../shared/ui";
import type { CharacterFieldChange } from "./characterEditorUtils";

interface CharacterPersonalitySectionProps {
  aiPending: boolean;
  draft: Character;
  id?: string;
  onAiWrite: () => void;
  onChange: CharacterFieldChange;
  onTranslate: () => void;
  translatePending: boolean;
}

export function CharacterPersonalitySection({
  aiPending,
  draft,
  id,
  onAiWrite,
  onChange,
  onTranslate,
  translatePending,
}: CharacterPersonalitySectionProps) {
  const { t } = useI18n();

  return (
    <section className="section character-personality-section page-section-anchor" id={id}>
      <div className="section__header">
        <h2 className="section__title">{t("character.section.personality")}</h2>
        <div className="page__actions">
          <AsyncButton icon={<Sparkles aria-hidden className="button__icon" />} loading={aiPending} onClick={onAiWrite}>
            {t("character.action.aiWrite")}
          </AsyncButton>
          <AsyncButton
            icon={<Languages aria-hidden className="button__icon" />}
            loading={translatePending}
            onClick={onTranslate}
            variant="ghost"
          >
            {t("character.action.aiTranslate")}
          </AsyncButton>
        </div>
      </div>
      <div className="form-grid character-personality-section__body">
        <label className="field-row character-personality-section__field">
          <span className="field-row__label">{t("character.field.characterSetting")}</span>
          <span className="field-row__control">
            <TextArea
              className="character-personality-section__textarea"
              onChange={(event) => onChange("character_setting", event.target.value)}
              value={draft.character_setting}
            />
          </span>
        </label>
      </div>
    </section>
  );
}
