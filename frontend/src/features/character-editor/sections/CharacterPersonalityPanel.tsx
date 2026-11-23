import type { PageSectionProps } from "../../../shared/ui";
import { CharacterPersonalitySection } from "../CharacterPersonalitySection";
import type { CharacterPageContext } from "../characterContext";
import { useCharacterPersonalityController } from "../controllers/useCharacterPersonalityController";

export function CharacterPersonalityPanel({ ctx, id }: PageSectionProps<CharacterPageContext>) {
  const personality = useCharacterPersonalityController(ctx);

  return (
    <CharacterPersonalitySection
      actionsDisabled={ctx.identityPending}
      aiPending={personality.aiPending}
      briefPending={personality.briefPending}
      draft={ctx.draft}
      id={id}
      onAiBrief={personality.generateBrief}
      onAiWrite={personality.generateSetting}
      onChange={ctx.updateField}
      onTranslate={personality.translateDraft}
      translatePending={personality.translatePending}
    />
  );
}
