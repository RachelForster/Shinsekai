import type { CSSProperties } from "react";
import { Pencil } from "lucide-react";

import { useI18n } from "../../../shared/i18n";
import { getCharacterDisplayName } from "../../../shared/playerCharacterOptions";
import { Button, type PageSectionProps } from "../../../shared/ui";
import { CharacterConfigDialog } from "../CharacterConfigDialog";
import type { TemplateEditorContext } from "../templateContext";

export function TemplateCharactersSection({ ctx }: PageSectionProps<TemplateEditorContext>) {
  const { t } = useI18n();

  return (
    <>
      <section className="template-summary-bar" data-section="characters">
        <div className="template-summary-bar__header">
          <div className="template-summary-bar__title-group">
            <span className="template-panel__label">{t("template.field.characters")}</span>
            {ctx.showRoleSummary ? <span className="template-summary-pill">{ctx.roleSummaryText}</span> : null}
          </div>
          <Button
            aria-label={t("template.bar.editCharacters")}
            icon={<Pencil aria-hidden className="button__icon" />}
            onClick={ctx.openCharacterDialog}
            variant="ghost"
          >
            {t("template.mode.edit")}
          </Button>
        </div>
        <div className="template-summary-bar__body">
          {ctx.selectedCharacters.length === 0 ? (
            <span className="template-summary-bar__empty">{t("template.bar.charactersEmpty")}</span>
          ) : (
            <div className="template-summary-chips" role="list">
              {ctx.selectedCharacters.map((name) => {
                const character = ctx.characterByName.get(name);
                const isPlayer = name === ctx.effectivePlayerCharacter;
                return (
                  <span
                    className={`template-summary-chip${!character ? " is-unavailable" : ""}`}
                    key={name}
                    role="listitem"
                    style={
                      {
                        "--template-character-color": character?.color || "#5b8def",
                      } as CSSProperties
                    }
                  >
                    <span aria-hidden className="template-character-card__dot" />
                    <span className="template-summary-chip__name">
                      {character ? getCharacterDisplayName(character) : t("template.character.unavailable", { name })}
                    </span>
                    {isPlayer ? (
                      <span className="template-summary-chip__badge">{t("template.bar.playerBadge")}</span>
                    ) : null}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      </section>

      <CharacterConfigDialog
        allowPlayerDialogue={ctx.allowPlayerDialogue}
        characterPromptMode={ctx.characterPromptMode}
        characters={ctx.characters}
        error={ctx.characterDialogError}
        onClose={() => ctx.setCharacterDialogOpen(false)}
        onConfirm={ctx.confirmCharacterConfig}
        open={ctx.characterDialogOpen}
        pending={ctx.ensureBriefsPending}
        playerCharacter={ctx.effectivePlayerCharacter}
        primaryCharacters={ctx.primaryCharacters}
        readPlayerSpeech={ctx.readPlayerSpeech}
        selectedCharacters={ctx.selectedCharacters}
      />
    </>
  );
}
