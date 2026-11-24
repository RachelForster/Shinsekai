import type { PageSectionProps } from "../../../shared/ui";
import { CharacterVoiceSection } from "../CharacterVoiceSection";
import type { CharacterPageContext } from "../characterContext";

export function CharacterVoicePanel({ ctx, id }: PageSectionProps<CharacterPageContext>) {
  return (
    <CharacterVoiceSection
      draft={ctx.draft}
      id={id}
      onChange={ctx.updateField}
      voiceReferenceReadOnly={ctx.voiceReferenceReadOnly}
    />
  );
}
